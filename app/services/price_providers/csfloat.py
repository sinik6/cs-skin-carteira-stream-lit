"""Provider de preco via CSFloat API."""

from __future__ import annotations

import logging
import time
from statistics import median

import requests

from app.config import CSFLOAT_DELAY_SECONDS, FX_CACHE_TTL_SECONDS
from app.services.price_providers.base import PriceProvider, PriceResult
from app.services.runtime_state import build_fx_cache_key, get_cached_price, set_cached_price

logger = logging.getLogger(__name__)

CSFLOAT_LISTINGS_URL = "https://csfloat.com/api/v1/listings"
USD_BRL_FALLBACK = 5.80
COMPARABLES_LIMIT = 20
MIN_RELIABLE_COMPARABLES = 3
PREFERRED_COMPARABLES = 5
WIDE_FLOAT_MARGIN = 0.03


class CSFloatProvider(PriceProvider):
    """Busca precos via CSFloat Marketplace API."""

    nome = "CSFloat"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._last_request: float = 0.0

    def esta_configurado(self) -> bool:
        return bool(self._api_key)

    def set_api_key(self, key: str) -> None:
        self._api_key = key

    def buscar_preco(
        self,
        market_hash_name: str,
        float_value: float = 0.0,
        margem: float = 0.01,
        paint_seed: str = "",
    ) -> PriceResult:
        if not self._api_key:
            return PriceResult.falha(self.nome, "API key nao configurada")

        if not market_hash_name:
            return PriceResult.falha(self.nome, "market_hash_name vazio")

        cenarios = self._build_search_scenarios(
            market_hash_name=market_hash_name,
            float_value=float_value,
            margem=margem,
            paint_seed=paint_seed,
        )

        melhor_parcial: tuple[float, int, str] | None = None

        try:
            for label, params, usar_float_alvo in cenarios:
                listings = self._buscar_listings(params)
                if not listings:
                    continue

                preco_usd, usados = self._estimar_preco_usd(
                    listings=listings,
                    target_float=float_value if usar_float_alvo else 0.0,
                )
                if preco_usd <= 0:
                    continue

                if usados >= MIN_RELIABLE_COMPARABLES:
                    return self._build_success_result(preco_usd, label, usados)

                if melhor_parcial is None or usados > melhor_parcial[1]:
                    melhor_parcial = (preco_usd, usados, label)

            if melhor_parcial:
                preco_usd, usados, label = melhor_parcial
                return self._build_success_result(preco_usd, f"{label}, baixa amostra", usados)

            return PriceResult.falha(
                self.nome,
                f"Nenhum listing encontrado: {market_hash_name}",
            )

        except requests.exceptions.Timeout:
            return PriceResult.falha(self.nome, "Timeout na requisicao")
        except requests.exceptions.RequestException as e:
            return PriceResult.falha(self.nome, f"Erro HTTP: {e}")
        except Exception as e:
            logger.exception("Erro inesperado CSFloat")
            return PriceResult.falha(self.nome, str(e))

    def _build_search_scenarios(
        self,
        market_hash_name: str,
        float_value: float,
        margem: float,
        paint_seed: str,
    ) -> list[tuple[str, dict, bool]]:
        base_params = {
            "market_hash_name": market_hash_name,
            "sort_by": "lowest_price",
            "type": "buy_now",
            "limit": COMPARABLES_LIMIT,
        }

        scenarios: list[tuple[str, dict, bool]] = []
        seen: set[tuple] = set()

        def add_scenario(label: str, params: dict, usar_float_alvo: bool) -> None:
            key = tuple(sorted(params.items()))
            if key not in seen:
                seen.add(key)
                scenarios.append((label, params, usar_float_alvo))

        if float_value > 0 and paint_seed:
            params = dict(base_params)
            params["min_float"] = max(0.0, round(float_value - margem, 4))
            params["max_float"] = min(1.0, round(float_value + margem, 4))
            params["paint_seed"] = paint_seed
            add_scenario("mediana por float + pattern", params, True)

        if float_value > 0:
            params = dict(base_params)
            params["min_float"] = max(0.0, round(float_value - margem, 4))
            params["max_float"] = min(1.0, round(float_value + margem, 4))
            add_scenario("mediana por float", params, True)

            wide_margin = max(margem * 2, WIDE_FLOAT_MARGIN)
            params = dict(base_params)
            params["min_float"] = max(0.0, round(float_value - wide_margin, 4))
            params["max_float"] = min(1.0, round(float_value + wide_margin, 4))
            add_scenario("mediana por float ampliado", params, True)

        add_scenario("mediana de mercado", dict(base_params), False)
        return scenarios

    def _buscar_listings(self, params: dict) -> list[dict]:
        self._rate_limit()

        resp = requests.get(
            CSFLOAT_LISTINGS_URL,
            headers={"Authorization": self._api_key},
            params=params,
            timeout=15,
        )

        if resp.status_code == 401:
            raise requests.exceptions.RequestException("API key invalida")
        if resp.status_code == 429:
            raise requests.exceptions.RequestException("Rate limit excedido")

        resp.raise_for_status()
        data = resp.json()
        listings = data if isinstance(data, list) else data.get("data", [])
        return listings if isinstance(listings, list) else []

    def _estimar_preco_usd(self, listings: list[dict], target_float: float = 0.0) -> tuple[float, int]:
        comparaveis: list[tuple[float, float | None]] = []

        for listing in listings:
            price_cents = listing.get("price", 0)
            price_usd = price_cents / 100.0 if price_cents > 0 else 0.0
            if price_usd <= 0:
                continue

            item = listing.get("item") or {}
            listing_float = item.get("float_value")
            if not isinstance(listing_float, (int, float)):
                listing_float = None

            comparaveis.append((price_usd, listing_float))

        if not comparaveis:
            return 0.0, 0

        selecionados: list[tuple[float, float | None]]

        if target_float > 0:
            com_float = [item for item in comparaveis if item[1] is not None]
            if len(com_float) >= MIN_RELIABLE_COMPARABLES:
                com_float.sort(key=lambda item: abs((item[1] or 0.0) - target_float))
                selecionados = com_float[: min(PREFERRED_COMPARABLES, len(com_float))]
            else:
                comparaveis.sort(key=lambda item: item[0])
                selecionados = comparaveis[: min(PREFERRED_COMPARABLES, len(comparaveis))]
        else:
            comparaveis.sort(key=lambda item: item[0])
            selecionados = comparaveis[: min(PREFERRED_COMPARABLES, len(comparaveis))]

        precos = [item[0] for item in selecionados]
        return round(float(median(precos)), 2), len(precos)

    def _build_success_result(self, preco_usd: float, label: str, usados: int) -> PriceResult:
        taxa = self._buscar_cambio()
        preco_brl = round(preco_usd * taxa, 2)
        if "pattern" in label and usados >= 3:
            confianca = "Alta"
        elif "float" in label and usados >= 3:
            confianca = "Media"
        else:
            confianca = "Baixa"
        return PriceResult(
            preco=preco_brl,
            moeda="BRL",
            provider=self.nome,
            metodo=label,
            amostra=usados,
            confianca=confianca,
        )

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < CSFLOAT_DELAY_SECONDS:
            time.sleep(CSFLOAT_DELAY_SECONDS - elapsed)
        self._last_request = time.time()

    @staticmethod
    def _buscar_cambio() -> float:
        """Tenta buscar cambio USD/BRL; usa fallback se falhar."""
        cache_key = build_fx_cache_key("USD", "BRL")
        cache = get_cached_price(cache_key)
        if cache and cache.preco > 0:
            return cache.preco

        try:
            resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
            if resp.ok:
                rates = resp.json().get("rates", {})
                taxa = rates.get("BRL", USD_BRL_FALLBACK)
                set_cached_price(
                    cache_key,
                    preco=taxa,
                    provider="fx",
                    ttl_seconds=FX_CACHE_TTL_SECONDS,
                )
                return taxa
        except Exception:
            pass
        return USD_BRL_FALLBACK
