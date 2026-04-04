"""Servico de persistencia em JSON com escrita atomica e fallback por backup."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import DATA_DIR, DATA_FILE, DATA_FILE_BACKUP, MARKET_INTELLIGENCE_FILE, MARKET_INTELLIGENCE_HISTORY_LIMIT
from app.models import AppData, MarketIntelligenceRecord, Skin

logger = logging.getLogger(__name__)
_APP_DATA_CACHE: dict[Path, tuple[float, AppData]] = {}


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_app_data(path: Path) -> AppData:
    raw = path.read_text(encoding="utf-8")
    return AppData.model_validate_json(raw)


def _get_cached_app_data(path: Path) -> AppData | None:
    if not path.exists():
        _APP_DATA_CACHE.pop(path, None)
        return None

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None

    cached = _APP_DATA_CACHE.get(path)
    if not cached or cached[0] != mtime:
        return None

    return cached[1].model_copy(deep=True)


def _set_cached_app_data(path: Path, data: AppData) -> None:
    try:
        mtime = path.stat().st_mtime if path.exists() else 0.0
    except OSError:
        _APP_DATA_CACHE.pop(path, None)
        return

    _APP_DATA_CACHE[path] = (mtime, data.model_copy(deep=True))


def _atomic_write(path: Path, content: str) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def carregar_dados() -> AppData:
    """Carrega os dados do arquivo JSON. Usa backup se o principal falhar."""
    _ensure_dir()
    if not DATA_FILE.exists():
        return AppData()

    cached = _get_cached_app_data(DATA_FILE)
    if cached is not None:
        return cached

    try:
        data = _read_app_data(DATA_FILE)
        _set_cached_app_data(DATA_FILE, data)
        return data
    except Exception:
        logger.exception("Erro ao carregar %s", DATA_FILE)

    if DATA_FILE_BACKUP.exists():
        try:
            logger.warning("Tentando recuperar dados do backup %s", DATA_FILE_BACKUP)
            data = _read_app_data(DATA_FILE_BACKUP)
            salvar_dados(data)
            return data
        except Exception:
            logger.exception("Erro ao carregar backup %s", DATA_FILE_BACKUP)

    return AppData()


def salvar_dados(data: AppData) -> None:
    """Salva os dados com escrita atomica e backup do ultimo estado valido."""
    _ensure_dir()
    content = data.model_dump_json(indent=2)

    if DATA_FILE.exists():
        try:
            _atomic_write(DATA_FILE_BACKUP, DATA_FILE.read_text(encoding="utf-8"))
            _APP_DATA_CACHE.pop(DATA_FILE_BACKUP, None)
        except Exception:
            logger.exception("Nao foi possivel atualizar backup %s", DATA_FILE_BACKUP)

    _atomic_write(DATA_FILE, content)
    _set_cached_app_data(DATA_FILE, data)


def adicionar_skin(skin: Skin) -> AppData:
    """Adiciona uma skin e persiste."""
    data = carregar_dados()
    data.skins.append(skin)
    salvar_dados(data)
    return data


def remover_skin(skin_id: str) -> AppData:
    """Remove uma skin pelo ID e persiste."""
    data = carregar_dados()
    data.skins = [s for s in data.skins if s.id != skin_id]
    salvar_dados(data)
    return data


def atualizar_skin(skin: Skin) -> AppData:
    """Atualiza uma skin existente."""
    data = carregar_dados()
    data.skins = [skin if s.id == skin.id else s for s in data.skins]
    salvar_dados(data)
    return data


def salvar_config(data: AppData) -> None:
    """Salva apenas as configuracoes."""
    salvar_dados(data)


def importar_seed_data(seed_path: Path) -> AppData:
    """Importa dados iniciais de um JSON seed se o arquivo principal nao existir."""
    _ensure_dir()
    if DATA_FILE.exists():
        return carregar_dados()

    if not seed_path.exists():
        return AppData()

    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
        skins = [Skin.model_validate(s) for s in raw.get("skins", [])]
        data = AppData(skins=skins)
        salvar_dados(data)
        return data
    except Exception:
        logger.exception("Erro ao importar seed %s", seed_path)
        return AppData()


def carregar_market_intelligence() -> dict[str, MarketIntelligenceRecord]:
    _ensure_dir()
    if not MARKET_INTELLIGENCE_FILE.exists():
        return {}

    try:
        raw = json.loads(MARKET_INTELLIGENCE_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Erro ao carregar inteligencia de mercado %s", MARKET_INTELLIGENCE_FILE)
        return {}

    registros: dict[str, MarketIntelligenceRecord] = {}
    for key, value in raw.items():
        try:
            registros[key] = MarketIntelligenceRecord.model_validate(value)
        except Exception:
            logger.warning("Registro de inteligencia invalido ignorado: %s", key)
    return registros


def salvar_market_intelligence(registros: dict[str, MarketIntelligenceRecord]) -> None:
    _ensure_dir()
    serializable = {key: value.model_dump() for key, value in registros.items()}
    _atomic_write(MARKET_INTELLIGENCE_FILE, json.dumps(serializable, indent=2))


def salvar_market_snapshot(record: MarketIntelligenceRecord) -> None:
    registros = carregar_market_intelligence()
    existente = registros.get(record.skin_id)
    if existente:
        history = [record.snapshot] + existente.history
        record.history = history[:MARKET_INTELLIGENCE_HISTORY_LIMIT]
    else:
        record.history = [record.snapshot][:MARKET_INTELLIGENCE_HISTORY_LIMIT]

    registros[record.skin_id] = record
    salvar_market_intelligence(registros)


def obter_market_snapshot(skin_id: str) -> MarketIntelligenceRecord | None:
    return carregar_market_intelligence().get(skin_id)
