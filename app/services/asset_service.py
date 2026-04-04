"""Orquestrador de busca e histórico semanal de ativos."""

from __future__ import annotations

import json
from datetime import datetime

from app.models import ApiConfig, AssetSearchResult, InstrumentKind, InstrumentMetadata, MarketInstrument, WeeklyPricePoint
from app.services import db
from app.services.asset_providers import AlphaVantageProvider, TwelveDataProvider


class AssetService:
    """Busca ativos com cache local, fallback e persistência em SQLite."""

    def __init__(self, config: ApiConfig) -> None:
        self._config = config
        self._twelvedata = TwelveDataProvider(config.twelvedata_api_key)
        self._alphavantage = AlphaVantageProvider(config.alphavantage_api_key)

    def search_assets(self, query: str) -> list[AssetSearchResult]:
        query = query.strip()
        if not query:
            return []

        cached = db.get_asset_search_cache(query, self._twelvedata.provider_name)
        if cached:
            return cached[0]

        primary_results = self._twelvedata.search_assets(query) if self._twelvedata.esta_configurado() else []
        if primary_results:
            db.save_asset_search_cache(query, self._twelvedata.provider_name, primary_results, datetime.now().isoformat())
            return primary_results

        fallback_results = self._alphavantage.search_assets(query) if self._alphavantage.esta_configurado() else []
        if fallback_results:
            db.save_asset_search_cache(query, self._alphavantage.provider_name, fallback_results, datetime.now().isoformat())
        return fallback_results

    def get_or_create_instrument(self, result: AssetSearchResult) -> MarketInstrument:
        instrument = MarketInstrument(
            id=f"asset_{result.provider}_{result.symbol.replace('/', '_').replace(':', '_')}".lower(),
            kind=self._map_kind(result.instrument_type),
            display_name=result.name or result.symbol,
            symbol=result.symbol,
            currency=result.currency or "USD",
            exchange=result.exchange,
            provider_primary=result.provider or self._twelvedata.provider_name,
            provider_fallback=self._alphavantage.provider_name if result.provider != self._alphavantage.provider_name else "",
        )
        db.upsert_instrument(instrument)
        db.upsert_instrument_metadata(
            InstrumentMetadata(
                instrument_id=instrument.id,
                payload_json=json.dumps(result.model_dump()),
            )
        )
        return instrument

    def list_catalog_assets(self) -> list[MarketInstrument]:
        return [
            item
            for item in db.list_instruments()
            if item.kind != InstrumentKind.SKIN
        ]

    def fetch_weekly_series(self, instrument: MarketInstrument, outputsize: int = 52) -> list[WeeklyPricePoint]:
        provider_name = instrument.provider_primary or self._twelvedata.provider_name
        provider = self._resolve_provider(provider_name)
        points = provider.get_weekly_series(instrument.symbol, outputsize=outputsize) if provider else []

        if not points and provider_name != self._alphavantage.provider_name:
            fallback = self._resolve_provider(self._alphavantage.provider_name)
            points = fallback.get_weekly_series(instrument.symbol, outputsize=outputsize) if fallback else []

        normalized = [
            point.model_copy(update={"instrument_id": instrument.id})
            for point in points
        ]
        if normalized:
            db.upsert_weekly_prices(normalized)
        return normalized

    @staticmethod
    def _map_kind(instrument_type: str) -> str:
        lowered = (instrument_type or "").strip().lower()
        if lowered in {"common stock", "stock", "equity"}:
            return InstrumentKind.STOCK
        if lowered in {"etf"}:
            return InstrumentKind.ETF
        if lowered in {"reit"}:
            return InstrumentKind.REIT
        if lowered in {"index"}:
            return InstrumentKind.INDEX
        if lowered in {"crypto", "digital currency"}:
            return InstrumentKind.CRYPTO
        return InstrumentKind.OTHER

    def _resolve_provider(self, provider_name: str):
        if provider_name == self._twelvedata.provider_name and self._twelvedata.esta_configurado():
            return self._twelvedata
        if provider_name == self._alphavantage.provider_name and self._alphavantage.esta_configurado():
            return self._alphavantage
        return None
