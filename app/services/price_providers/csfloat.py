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
STEAM_IMAGE_BASE_URL = "https://community.cloudflare.steamstatic.com/economy/image"


class CSFloatProvider(PriceProvider):
    """Busca precos via CSFloat Marketplace API."""

    nome = "CSFloat"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._last_request: float = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "CS2-Skin-Tracker/1.0",
                "Accept": "application/json",
            }
        )

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

        melhor_parcial: tuple[float, int, str, list[dict]] | None = None

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
                    return self._build_success_result(preco_usd, label, usados, listings)

                if melhor_parcial is None or usados > melhor_parcial[1]:
                    melhor_parcial = (preco_usd, usados, label, listings)

            if melhor_parcial:
                preco_usd, usados, label, partial_listings = melhor_parcial
                return self._build_success_result(preco_usd, f"{label}, baixa amostra", usados, partial_listings)

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

    def buscar_comparaveis(
        self,
        market_hash_name: str,
        float_value: float = 0.0,
        margem: float = 0.01,
        paint_seed: str = "",
        limit: int = PREFERRED_COMPARABLES,
    ) -> tuple[str, list[dict], bool]:
        if not self._api_key:
            raise requests.exceptions.RequestException("API key nao configurada")

        cenarios = self._build_search_scenarios(
            market_hash_name=market_hash_name,
            float_value=float_value,
            margem=margem,
            paint_seed=paint_seed,
        )

        melhor_parcial: tuple[str, list[dict], bool] | None = None

        for label, params, usar_float_alvo in cenarios:
            listings = self._buscar_listings(params)
            selecionados = self._selecionar_listings(
                listings,
                target_float=float_value if usar_float_alvo else 0.0,
                limit=limit,
            )
            if not selecionados:
                continue
            if len(selecionados) >= MIN_RELIABLE_COMPARABLES:
                return label, selecionados, usar_float_alvo
            if melhor_parcial is None or len(selecionados) > len(melhor_parcial[1]):
                melhor_parcial = (label, selecionados, usar_float_alvo)

        if melhor_parcial is not None:
            return melhor_parcial

        raise requests.exceptions.RequestException(f"Nenhum listing encontrado: {market_hash_name}")

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

        resp = self._session.get(
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

    def _selecionar_listings(
        self,
        listings: list[dict],
        target_float: float = 0.0,
        limit: int = PREFERRED_COMPARABLES,
    ) -> list[dict]:
        comparaveis: list[tuple[dict, float, float | None]] = []

        for listing in listings:
            price_usd = self._listing_price_usd(listing)
            if price_usd <= 0:
                continue

            item = listing.get("item") or {}
            listing_float = item.get("float_value")
            if not isinstance(listing_float, (int, float)):
                listing_float = None

            comparaveis.append((listing, price_usd, listing_float))

        if not comparaveis:
            return []

        selecionados: list[tuple[dict, float, float | None]]

        if target_float > 0:
            com_float = [item for item in comparaveis if item[2] is not None]
            if len(com_float) >= MIN_RELIABLE_COMPARABLES:
                com_float.sort(key=lambda item: (abs((item[2] or 0.0) - target_float), item[1]))
                selecionados = com_float[: min(limit, len(com_float))]
            else:
                comparaveis.sort(key=lambda item: item[1])
                selecionados = comparaveis[: min(limit, len(comparaveis))]
        else:
            comparaveis.sort(key=lambda item: item[1])
            selecionados = comparaveis[: min(limit, len(comparaveis))]

        return [item[0] for item in selecionados]

    def _estimar_preco_usd(self, listings: list[dict], target_float: float = 0.0) -> tuple[float, int]:
        selecionados = self._selecionar_listings(
            listings,
            target_float=target_float,
            limit=PREFERRED_COMPARABLES,
        )
        if not selecionados:
            return 0.0, 0

        precos = [self._listing_price_usd(item) for item in selecionados]
        return round(float(median(precos)), 2), len(precos)

    def _build_success_result(self, preco_usd: float, label: str, usados: int, listings: list[dict] | None = None) -> PriceResult:
        taxa = self._buscar_cambio()
        preco_brl = round(preco_usd * taxa, 2)
        if "pattern" in label and usados >= 3:
            confianca = "Alta"
        elif "float" in label and usados >= 3:
            confianca = "Media"
        else:
            confianca = "Baixa"
        imagem_url = self._extrair_imagem_url(listings or [])
        return PriceResult(
            preco=preco_brl,
            moeda="BRL",
            provider=self.nome,
            metodo=label,
            amostra=usados,
            confianca=confianca,
            imagem_url=imagem_url,
        )

    @staticmethod
    def _extrair_imagem_url(listings: list[dict]) -> str:
        for listing in listings:
            item = listing.get("item") or {}
            icon_url = item.get("icon_url")
            if icon_url:
                return f"{STEAM_IMAGE_BASE_URL}/{icon_url}/160fx160f"
        return ""

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < CSFLOAT_DELAY_SECONDS:
            time.sleep(CSFLOAT_DELAY_SECONDS - elapsed)
        self._last_request = time.time()

    @staticmethod
    def _listing_price_usd(listing: dict) -> float:
        price_cents = listing.get("price", 0)
        return round(price_cents / 100.0, 2) if price_cents > 0 else 0.0

    @classmethod
    def listing_price_brl(cls, listing: dict, fx_rate: float | None = None) -> float:
        taxa = fx_rate if fx_rate and fx_rate > 0 else cls._buscar_cambio()
        return round(cls._listing_price_usd(listing) * taxa, 2)

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
