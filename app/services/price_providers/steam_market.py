"""Provider de preço via Steam Community Market."""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote

import requests

from app.config import STEAM_DELAY_SECONDS
from app.services.price_providers.base import PriceProvider, PriceResult

logger = logging.getLogger(__name__)

STEAM_URL = "https://steamcommunity.com/market/priceoverview/"
APPID_CS2 = 730
CURRENCY_BRL = 7


def _parse_brl(valor_str: str) -> float:
    """Converte 'R$ 1.234,56' para float."""
    limpo = re.sub(r"[^\d,.]", "", valor_str)
    # Steam BRL usa '.' como milhar e ',' como decimal
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return 0.0


class SteamMarketProvider(PriceProvider):
    """Busca preços no Steam Community Market (sem API key)."""

    nome = "Steam Market"

    def __init__(self) -> None:
        self._last_request: float = 0.0

    def esta_configurado(self) -> bool:
        return True

    def buscar_preco(self, market_hash_name: str, float_value: float = 0.0, margem: float = 0.01, paint_seed: str = "") -> PriceResult:
        if not market_hash_name:
            return PriceResult.falha(self.nome, "market_hash_name vazio")

        self._rate_limit()

        params = {
            "appid": APPID_CS2,
            "currency": CURRENCY_BRL,
            "market_hash_name": market_hash_name,
        }

        try:
            resp = requests.get(STEAM_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                return PriceResult.falha(self.nome, f"Item não encontrado: {market_hash_name}")

            preco_str = data.get("lowest_price") or data.get("median_price", "0")
            preco = _parse_brl(preco_str)

            if preco <= 0:
                return PriceResult.falha(self.nome, "Preço retornado inválido")

            metodo = "lowest_price" if data.get("lowest_price") else "median_price"
            return PriceResult(
                preco=preco,
                moeda="BRL",
                provider=self.nome,
                metodo=metodo,
                amostra=1,
                confianca="Baixa",
            )

        except requests.exceptions.Timeout:
            return PriceResult.falha(self.nome, "Timeout na requisição")
        except requests.exceptions.RequestException as e:
            return PriceResult.falha(self.nome, f"Erro HTTP: {e}")
        except Exception as e:
            logger.exception("Erro inesperado Steam Market")
            return PriceResult.falha(self.nome, str(e))

    def _rate_limit(self) -> None:
        """Respeita rate limit do Steam (~20 req/min)."""
        elapsed = time.time() - self._last_request
        if elapsed < STEAM_DELAY_SECONDS:
            time.sleep(STEAM_DELAY_SECONDS - elapsed)
        self._last_request = time.time()
