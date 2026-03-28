"""Persistencia auxiliar para cache de precos e estado dos providers."""

from __future__ import annotations

import json
import logging
import time

from app.config import PRICE_CACHE_FILE, PROVIDER_STATE_FILE
from app.models import PriceCacheEntry, ProviderState

logger = logging.getLogger(__name__)


def _ensure_parent_files() -> None:
    PRICE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_json(path) -> dict:
    _ensure_parent_files()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Erro ao carregar arquivo auxiliar %s", path)
        return {}


def _save_json(path, data: dict) -> None:
    _ensure_parent_files()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def build_price_cache_key(
    provider: str,
    market_hash_name: str,
    float_value: float = 0.0,
    margem: float = 0.01,
    paint_seed: str = "",
) -> str:
    return "|".join(
        [
            provider,
            market_hash_name.strip().lower(),
            f"{float_value:.4f}",
            f"{margem:.4f}",
            paint_seed.strip(),
        ]
    )


def build_fx_cache_key(base_currency: str, quote_currency: str) -> str:
    return f"fx|{base_currency.upper()}|{quote_currency.upper()}"


def load_price_cache() -> dict[str, PriceCacheEntry]:
    raw = _load_json(PRICE_CACHE_FILE)
    entries: dict[str, PriceCacheEntry] = {}
    for key, value in raw.items():
        try:
            entries[key] = PriceCacheEntry.model_validate(value)
        except Exception:
            logger.warning("Ignorando cache invalido: %s", key)
    return entries


def save_price_cache(entries: dict[str, PriceCacheEntry]) -> None:
    serializable = {key: value.model_dump() for key, value in entries.items()}
    _save_json(PRICE_CACHE_FILE, serializable)


def get_cached_price(key: str, allow_stale: bool = False) -> PriceCacheEntry | None:
    entries = load_price_cache()
    entry = entries.get(key)
    if not entry:
        return None
    age = time.time() - entry.atualizado_em_ts
    if allow_stale or age <= entry.ttl_seconds:
        return entry
    return None


def set_cached_price(
    key: str,
    preco: float,
    provider: str,
    ttl_seconds: int,
    moeda: str = "BRL",
    metodo: str = "",
    amostra: int = 0,
    confianca: str = "",
) -> PriceCacheEntry:
    entries = load_price_cache()
    entry = PriceCacheEntry(
        key=key,
        preco=preco,
        moeda=moeda,
        provider=provider,
        metodo=metodo,
        amostra=amostra,
        confianca=confianca,
        ttl_seconds=ttl_seconds,
        atualizado_em_ts=time.time(),
    )
    entries[key] = entry
    save_price_cache(entries)
    return entry


def load_provider_states() -> dict[str, ProviderState]:
    raw = _load_json(PROVIDER_STATE_FILE)
    states: dict[str, ProviderState] = {}
    for key, value in raw.items():
        try:
            states[key] = ProviderState.model_validate(value)
        except Exception:
            logger.warning("Ignorando estado invalido do provider: %s", key)
    return states


def save_provider_states(states: dict[str, ProviderState]) -> None:
    serializable = {key: value.model_dump() for key, value in states.items()}
    _save_json(PROVIDER_STATE_FILE, serializable)


def get_provider_state(provider: str) -> ProviderState:
    states = load_provider_states()
    return states.get(provider, ProviderState())


def wait_for_provider_slot(provider: str, min_delay_seconds: float) -> None:
    states = load_provider_states()
    state = states.get(provider, ProviderState())
    elapsed = time.time() - state.last_request_ts
    if elapsed < min_delay_seconds:
        time.sleep(min_delay_seconds - elapsed)


def touch_provider_request(provider: str) -> None:
    states = load_provider_states()
    state = states.get(provider, ProviderState())
    state.last_request_ts = time.time()
    states[provider] = state
    save_provider_states(states)


def record_provider_success(provider: str) -> None:
    states = load_provider_states()
    state = states.get(provider, ProviderState())
    now = time.time()
    state.last_request_ts = now
    state.last_success_ts = now
    state.consecutive_failures = 0
    state.cooldown_until_ts = 0.0
    state.last_error = ""
    states[provider] = state
    save_provider_states(states)


def record_provider_failure(
    provider: str,
    error: str,
    failure_threshold: int,
    cooldown_seconds: int,
) -> ProviderState:
    states = load_provider_states()
    state = states.get(provider, ProviderState())
    now = time.time()
    state.last_request_ts = now
    state.consecutive_failures += 1
    state.last_error = error
    if state.consecutive_failures >= failure_threshold:
        state.cooldown_until_ts = now + cooldown_seconds
    states[provider] = state
    save_provider_states(states)
    return state


def provider_is_in_cooldown(provider: str) -> bool:
    state = get_provider_state(provider)
    return time.time() < state.cooldown_until_ts
