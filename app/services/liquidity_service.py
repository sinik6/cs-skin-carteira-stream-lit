"""Servico leve para score de liquidez e historico local por skin."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import LIQUIDITY_HISTORY_FILE, LIQUIDITY_MAX_POINTS_PER_SKIN
from app.models import Skin


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _safe_fromiso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _provider_count(provider_label: str) -> int:
    label = (provider_label or "").strip()
    if not label:
        return 0
    if label.startswith("Agregado (") and label.endswith(")"):
        inside = label[len("Agregado (") : -1]
        parts = [part.strip() for part in inside.split("+") if part.strip()]
        return len(parts)
    return 1


def _confidence_to_score(confidence: str) -> float:
    mapping = {
        "Alta": 100.0,
        "Media": 68.0,
        "Baixa": 36.0,
    }
    return mapping.get((confidence or "").strip(), 45.0)


def _sample_to_score(sample: int) -> float:
    if sample <= 0:
        return 20.0
    if sample >= 20:
        return 100.0
    return 20.0 + (sample / 20.0) * 80.0


def _recency_to_score(updated_at: str) -> float:
    parsed = _safe_fromiso(updated_at)
    if not parsed:
        return 20.0
    hours = (datetime.now() - parsed).total_seconds() / 3600.0
    if hours <= 2:
        return 100.0
    if hours <= 6:
        return 82.0
    if hours <= 24:
        return 58.0
    if hours <= 72:
        return 34.0
    return 18.0


def _sources_to_score(source_count: int) -> float:
    if source_count <= 0:
        return 15.0
    if source_count == 1:
        return 52.0
    if source_count == 2:
        return 86.0
    return 100.0


def compute_liquidity(skin: Skin) -> dict[str, Any]:
    """Calcula score de liquidez em cima dos metadados de preco atuais."""
    source_count = _provider_count(skin.preco_provider)
    sample_score = _sample_to_score(skin.preco_amostra)
    confidence_score = _confidence_to_score(skin.preco_confianca)
    recency_score = _recency_to_score(skin.preco_atualizado_em)
    sources_score = _sources_to_score(source_count)

    score = (
        0.35 * sample_score
        + 0.30 * confidence_score
        + 0.20 * recency_score
        + 0.15 * sources_score
    )

    if source_count <= 1:
        score = min(score, 65.0)

    score = round(max(0.0, min(100.0, score)), 1)
    if score >= 75:
        level = "Alta"
    elif score >= 50:
        level = "Media"
    else:
        level = "Baixa"

    return {
        "score": score,
        "nivel": level,
        "fontes": source_count,
        "amostra": skin.preco_amostra,
        "atualizado_em": skin.preco_atualizado_em,
        "preco": skin.preco_atual,
    }


def _load_history(path: Path = LIQUIDITY_HISTORY_FILE) -> dict[str, list[dict[str, Any]]]:
    _ensure_parent(path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, list[dict[str, Any]]] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            parsed[key] = [item for item in value if isinstance(item, dict)]
    return parsed


def _save_history(history: dict[str, list[dict[str, Any]]], path: Path = LIQUIDITY_HISTORY_FILE) -> None:
    _ensure_parent(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def record_liquidity_snapshot(skin: Skin, path: Path = LIQUIDITY_HISTORY_FILE) -> None:
    """Registra snapshot de liquidez sem criar spam de pontos repetidos."""
    if skin.preco_atual <= 0:
        return
    metrics = compute_liquidity(skin)
    timestamp = skin.preco_atualizado_em or datetime.now().isoformat()
    history = _load_history(path)
    points = history.get(skin.id, [])

    if points:
        last = points[-1]
        same_timestamp = (last.get("timestamp", "") == timestamp)
        same_price = float(last.get("preco", 0.0)) == float(metrics["preco"])
        if same_timestamp or same_price:
            return

    points.append(
        {
            "timestamp": timestamp,
            "preco": metrics["preco"],
            "score": metrics["score"],
            "nivel": metrics["nivel"],
            "fontes": metrics["fontes"],
            "amostra": metrics["amostra"],
        }
    )
    if len(points) > LIQUIDITY_MAX_POINTS_PER_SKIN:
        points = points[-LIQUIDITY_MAX_POINTS_PER_SKIN :]
    history[skin.id] = points
    _save_history(history, path)


def get_liquidity_history(skin_id: str, path: Path = LIQUIDITY_HISTORY_FILE) -> list[dict[str, Any]]:
    history = _load_history(path)
    return history.get(skin_id, [])
