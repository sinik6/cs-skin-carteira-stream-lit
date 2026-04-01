"""Cliente leve para consumir o catalogo publico do ByMykel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from app.config import DATA_DIR
from app.models import Skin

RAW_API_BASE_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api"
DEFAULT_LANGUAGE = "en"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_CACHE_DIR = DATA_DIR / "catalog_cache"

SOURCE_FILES = (
    "skins_not_grouped.json",
    "stickers.json",
    "keychains.json",
    "agents.json",
    "graffiti.json",
    "patches.json",
    "music_kits.json",
    "crates.json",
    "tools.json",
    "collectibles.json",
)

TYPE_TO_SOURCE = {
    "Arma": ("skins_not_grouped.json",),
    "Faca": ("skins_not_grouped.json",),
    "Luva": ("skins_not_grouped.json",),
    "Adesivo": ("stickers.json",),
    "Agente": ("agents.json",),
    "Charm": ("keychains.json",),
    "Grafite": ("graffiti.json",),
    "Patch": ("patches.json",),
    "Music Kit": ("music_kits.json",),
    "Caixa": ("crates.json",),
    "Outro": ("collectibles.json", "tools.json"),
}

COLOR_SUFFIXES = {
    "(Roxo)",
    "(Azul)",
    "(Rosa)",
    "(Vermelho)",
    "(Dourado)",
    "(Verde)",
    "(Laranja)",
    "(Amarelo)",
    "(Branco)",
    "(Preto)",
}


def strip_color_suffixes(name: str) -> str:
    text = (name or "").strip()
    changed = True
    while changed:
        changed = False
        for suffix in COLOR_SUFFIXES:
            token = f" {suffix}"
            if text.endswith(token):
                text = text[: -len(token)].strip()
                changed = True
    return text


def lookup_candidates(raw_skin: dict[str, Any]) -> list[str]:
    allowed_fields = {key: value for key, value in raw_skin.items() if key in Skin.model_fields}
    skin = Skin(**allowed_fields)
    base_name = strip_color_suffixes(skin.nome)
    candidates: list[str] = []

    if skin.market_hash_name:
        candidates.append(skin.market_hash_name.strip())

    generated = skin.gerar_market_hash_name().strip()
    if generated:
        candidates.append(generated)

    if skin.tipo == "Adesivo":
        candidates.append(f"Sticker | {base_name}")
    elif skin.tipo == "Charm":
        candidates.append(f"Charm | {base_name}")
    else:
        candidates.append(base_name)

    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def infer_required_sources(raw_skins: list[dict[str, Any]]) -> list[str]:
    selected: list[str] = []
    for raw_skin in raw_skins:
        skin_type = str(raw_skin.get("tipo", "")).strip()
        for source_file in TYPE_TO_SOURCE.get(skin_type, ("collectibles.json", "tools.json")):
            if source_file not in selected:
                selected.append(source_file)
    return selected


def build_indexes(items: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_lookup: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}

    for item in items:
        market_hash_name = str(item.get("market_hash_name", "")).strip()
        if market_hash_name and market_hash_name not in by_lookup:
            by_lookup[market_hash_name] = item

        name = str(item.get("name", "")).strip()
        if name and name not in by_name:
            by_name[name] = item

    return by_lookup, by_name


def select_catalog_item(item: dict[str, Any]) -> dict[str, Any]:
    collections = [{"id": entry.get("id", ""), "name": entry.get("name", "")} for entry in item.get("collections", [])]
    crates = [{"id": entry.get("id", ""), "name": entry.get("name", "")} for entry in item.get("crates", [])]
    return {
        "market_hash_name": item.get("market_hash_name", ""),
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "image": item.get("image", ""),
        "rarity": item.get("rarity", {}),
        "weapon": item.get("weapon", {}),
        "category": item.get("category", {}),
        "pattern": item.get("pattern", {}),
        "wear": item.get("wear", {}),
        "team": item.get("team", {}),
        "collections": collections,
        "crates": crates,
        "stattrak": item.get("stattrak", False),
        "souvenir": item.get("souvenir", False),
        "paint_index": item.get("paint_index", ""),
        "source_file": item.get("_source_file", ""),
    }


class ByMykelCatalogClient:
    """Baixa apenas os arquivos necessarios do catalogo publico, com cache local."""

    def __init__(
        self,
        language: str = DEFAULT_LANGUAGE,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        local_api_root: Path | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        self._language = language
        self._cache_dir = cache_dir
        self._local_api_root = local_api_root
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", "CS2-Skin-Tracker/1.0")

    def load_catalog_items(
        self,
        source_files: list[str],
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for source_file in source_files:
            for item in self.load_source_items(source_file, force_refresh=force_refresh):
                cloned_item = dict(item)
                cloned_item["_source_file"] = source_file
                items.append(cloned_item)
        return items

    def load_source_items(
        self,
        source_file: str,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        if source_file not in SOURCE_FILES:
            raise ValueError(f"Arquivo de catalogo nao suportado: {source_file}")

        if self._local_api_root:
            return self._read_local_source(source_file)

        cache_file = self._cache_dir / self._language / source_file
        if cache_file.exists() and not force_refresh:
            return json.loads(cache_file.read_text(encoding="utf-8"))

        payload = self._download_source(source_file)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = cache_file.with_suffix(cache_file.suffix + ".tmp")
        temp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_file.replace(cache_file)
        return payload

    def _read_local_source(self, source_file: str) -> list[dict[str, Any]]:
        if not self._local_api_root:
            raise RuntimeError("local_api_root nao configurado")
        source_path = self._local_api_root / source_file
        if not source_path.exists():
            return []
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []

    def _download_source(self, source_file: str) -> list[dict[str, Any]]:
        url = self.build_source_url(source_file)
        response = self._session.get(url, timeout=self._timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Resposta invalida para {source_file}: esperado array JSON")
        return payload

    def build_source_url(self, source_file: str) -> str:
        return f"{RAW_API_BASE_URL}/{self._language}/{source_file}"
