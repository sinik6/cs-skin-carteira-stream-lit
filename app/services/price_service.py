"""Servico de busca de precos com cache persistente e fallback seguro."""

from __future__ import annotations

import logging
from typing import Callable
from datetime import datetime
from statistics import median

from app.config import (
    CSFLOAT_CACHE_TTL_SECONDS,
    CSFLOAT_DELAY_SECONDS,
    PLATFORM_PROVIDER_HINTS,
    STEAM_CACHE_TTL_SECONDS,
    STEAM_COOLDOWN_SECONDS,
    STEAM_DELAY_SECONDS,
    STEAM_FAILURE_THRESHOLD,
)
from app.models import ApiConfig, Skin
from app.services.price_providers import (
    CSFloatProvider,
    PriceResult,
    SteamMarketProvider,
)
from app.services.runtime_state import (
    build_price_cache_key,
    get_cached_price,
    provider_is_in_cooldown,
    record_provider_failure,
    record_provider_success,
    touch_provider_request,
    wait_for_provider_slot,
)

logger = logging.getLogger(__name__)

PROVIDER_DELAYS = {
    "steam": STEAM_DELAY_SECONDS,
    "csfloat": CSFLOAT_DELAY_SECONDS,
}

PROVIDER_TTLS = {
    "steam": STEAM_CACHE_TTL_SECONDS,
    "csfloat": CSFLOAT_CACHE_TTL_SECONDS,
}


class PriceService:
    """Busca precos usando os providers configurados, com cache e fallback."""

    def __init__(
        self,
        config: ApiConfig,
        considerar_float: bool = False,
        margem_float: float = 0.01,
        considerar_pattern: bool = False,
    ) -> None:
        self._steam = SteamMarketProvider()
        self._csfloat = CSFloatProvider(api_key=config.csfloat_api_key)
        self._config = config
        self._considerar_float = considerar_float
        self._margem_float = margem_float
        self._considerar_pattern = considerar_pattern

    def atualizar_config(self, config: ApiConfig) -> None:
        self._config = config
        self._csfloat.set_api_key(config.csfloat_api_key)

    @property
    def providers_disponiveis(self) -> list[str]:
        disponiveis = []
        if self._config.steam_enabled and self._steam.esta_configurado():
            disponiveis.append("steam")
        if self._csfloat.esta_configurado():
            disponiveis.append("csfloat")
        return disponiveis

    def buscar_preco(self, skin: Skin) -> PriceResult:
        """Busca preco com cache persistente, protecao de cooldown e fallback."""
        market_name = skin.gerar_market_hash_name()
        if not market_name:
            return PriceResult.falha("", "Nao foi possivel gerar market_hash_name")

        float_val = skin.float_value if self._considerar_float else 0.0
        margem = self._margem_float
        seed = skin.pattern_seed if self._considerar_pattern else ""

        stale_candidates: list[tuple[float, PriceResult]] = []
        successful_results: list[PriceResult] = []
        last_failure: PriceResult | None = None

        for provider_name in self._provider_order(skin.plataforma):
            cache_key = build_price_cache_key(provider_name, market_name, float_val, margem, seed)
            cached = get_cached_price(cache_key)
            if cached and cached.preco > 0:
                successful_results.append(
                    PriceResult(
                        preco=cached.preco,
                        moeda=cached.moeda,
                        provider=cached.provider,
                        cache_hit=True,
                        metodo=cached.metodo,
                        amostra=cached.amostra,
                        confianca=cached.confianca,
                        atualizado_em=datetime.fromtimestamp(cached.atualizado_em_ts).isoformat(),
                        imagem_url=cached.imagem_url,
                    )
                )
                continue

            stale_cache = get_cached_price(cache_key, allow_stale=True)
            if stale_cache and stale_cache.preco > 0:
                stale_candidates.append(
                    (
                        stale_cache.atualizado_em_ts,
                        PriceResult(
                            preco=stale_cache.preco,
                            moeda=stale_cache.moeda,
                            provider=stale_cache.provider,
                            cache_hit=True,
                            stale=True,
                            metodo=stale_cache.metodo,
                            amostra=stale_cache.amostra,
                            confianca=stale_cache.confianca,
                            atualizado_em=datetime.fromtimestamp(stale_cache.atualizado_em_ts).isoformat(),
                            imagem_url=stale_cache.imagem_url,
                        ),
                    )
                )

            if provider_is_in_cooldown(provider_name):
                last_failure = PriceResult.falha(
                    provider_name,
                    "Provider temporariamente em cooldown por falhas repetidas",
                )
                continue

            live_result = self._buscar_preco_live(
                provider_name,
                market_name,
                float_val,
                margem,
                seed,
                cache_key,
            )
            if live_result.sucesso and live_result.preco > 0:
                successful_results.append(live_result)
                continue
            last_failure = live_result

        if successful_results:
            return self._aggregate_results(successful_results)

        if stale_candidates:
            stale_candidates.sort(key=lambda item: item[0], reverse=True)
            return stale_candidates[0][1]

        return last_failure or PriceResult.falha("", "Nenhum provider disponivel")

    @staticmethod
    def _aggregate_results(results: list[PriceResult]) -> PriceResult:
        """Combina resultados validos de forma robusta e simples."""
        valid = [result for result in results if result.sucesso and result.preco > 0]
        if not valid:
            return PriceResult.falha("", "Nenhum preco valido para agregacao")

        if len(valid) == 1:
            return valid[0]

        prices = [result.preco for result in valid]
        median_price = median(prices)
        mean_price = sum(prices) / len(prices)
        spread_pct = ((max(prices) - min(prices)) / median_price) if median_price > 0 else 0.0

        if spread_pct <= 0.15:
            final_price = round(mean_price, 2)
            confidence = "Alta"
            method = "media_simples"
        elif spread_pct <= 0.35:
            final_price = round(median_price, 2)
            confidence = "Media"
            method = "mediana_robusta"
        else:
            final_price = round(median_price, 2)
            confidence = "Baixa"
            method = "mediana_robusta"

        providers = " + ".join(sorted({result.provider or "desconhecido" for result in valid}))
        image_url = next((result.imagem_url for result in valid if result.imagem_url), "")

        return PriceResult(
            preco=final_price,
            moeda=valid[0].moeda,
            provider=f"Agregado ({providers})",
            cache_hit=all(result.cache_hit for result in valid),
            stale=all(result.stale for result in valid),
            metodo=method,
            amostra=len(valid),
            confianca=confidence,
            imagem_url=image_url,
        )

    def buscar_precos_lote(
        self,
        skins: list[Skin],
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, PriceResult]:
        """Busca precos para varias skins com callback de progresso."""
        resultados: dict[str, PriceResult] = {}
        total = len(skins)

        for i, skin in enumerate(skins):
            if on_progress:
                on_progress(i + 1, total, skin.nome)

            resultado = self.buscar_preco(skin)
            resultados[skin.id] = resultado

        return resultados

    def _provider_order(self, plataforma_compra: str = "") -> list[str]:
        csfloat_ok = self._csfloat.esta_configurado()
        steam_ok = self._config.steam_enabled and self._steam.esta_configurado()

        ordered: list[str] = []
        hinted_provider = self._provider_hint_from_platform(plataforma_compra)

        if hinted_provider == "csfloat" and csfloat_ok:
            ordered.append("csfloat")
        elif hinted_provider == "steam" and steam_ok:
            ordered.append("steam")

        # Prioriza CSFloat sempre que houver API key, para reduzir dependencia do Steam.
        if csfloat_ok and "csfloat" not in ordered:
            ordered.append("csfloat")
        if steam_ok and "steam" not in ordered:
            ordered.append("steam")

        if not ordered and self._config.provider_preferido == "steam" and self._steam.esta_configurado():
            ordered.append("steam")

        return ordered

    @staticmethod
    def _provider_hint_from_platform(plataforma_compra: str) -> str:
        if not plataforma_compra:
            return ""
        return PLATFORM_PROVIDER_HINTS.get(plataforma_compra.strip(), "")

    def _buscar_preco_live(
        self,
        provider_name: str,
        market_name: str,
        float_val: float,
        margem: float,
        seed: str,
        cache_key: str,
    ) -> PriceResult:
        provider = self._resolve_provider(provider_name)
        wait_for_provider_slot(provider_name, PROVIDER_DELAYS[provider_name])
        touch_provider_request(provider_name)

        if provider_name == "csfloat":
            result = provider.buscar_preco(market_name, float_val, margem, seed)
        else:
            result = provider.buscar_preco(market_name)

        if result.sucesso and result.preco > 0:
            from app.services.runtime_state import set_cached_price

            set_cached_price(
                cache_key,
                preco=result.preco,
                provider=result.provider or provider_name,
                ttl_seconds=PROVIDER_TTLS[provider_name],
                moeda=result.moeda,
                metodo=result.metodo,
                amostra=result.amostra,
                confianca=result.confianca,
                imagem_url=result.imagem_url,
            )
            record_provider_success(provider_name)
            return result

        threshold = STEAM_FAILURE_THRESHOLD if provider_name == "steam" else 1000
        cooldown = STEAM_COOLDOWN_SECONDS if provider_name == "steam" else 0
        record_provider_failure(
            provider_name,
            result.erro or "Falha desconhecida",
            failure_threshold=threshold,
            cooldown_seconds=cooldown,
        )
        logger.info("Falha no provider %s: %s", provider_name, result.erro)
        return result

    def _resolve_provider(self, provider_name: str):
        if provider_name == "csfloat":
            return self._csfloat
        return self._steam
