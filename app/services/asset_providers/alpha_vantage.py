"""Provider fallback de ativos via Alpha Vantage."""

from __future__ import annotations

from datetime import datetime

import requests

from app.models import AssetSearchResult, WeeklyPricePoint
from app.services.asset_providers.base import AssetProvider, AssetQuoteResult

ALPHAVANTAGE_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageProvider(AssetProvider):
    provider_name = "alphavantage"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "CS2-Skin-Tracker/1.0", "Accept": "application/json"})

    def esta_configurado(self) -> bool:
        return bool(self._api_key)

    def search_assets(self, query: str) -> list[AssetSearchResult]:
        if not self._api_key:
            return []
        query = query.strip()
        if not query:
            return []

        resp = self._session.get(
            ALPHAVANTAGE_BASE_URL,
            params={"function": "SYMBOL_SEARCH", "keywords": query, "apikey": self._api_key},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("bestMatches", [])
        if not isinstance(rows, list):
            return []

        results: list[AssetSearchResult] = []
        for item in rows[:15]:
            results.append(
                AssetSearchResult(
                    symbol=str(item.get("1. symbol", "")),
                    name=str(item.get("2. name", "")),
                    instrument_type=str(item.get("3. type", "")),
                    exchange=str(item.get("4. region", "")),
                    currency=str(item.get("8. currency", "USD")),
                    country=str(item.get("4. region", "")),
                    provider=self.provider_name,
                )
            )
        return results

    def get_weekly_series(self, symbol: str, outputsize: int = 52) -> list[WeeklyPricePoint]:
        if not self._api_key:
            return []
        resp = self._session.get(
            ALPHAVANTAGE_BASE_URL,
            params={
                "function": "TIME_SERIES_WEEKLY_ADJUSTED",
                "symbol": symbol,
                "apikey": self._api_key,
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        series = payload.get("Weekly Adjusted Time Series", {})
        if not isinstance(series, dict):
            return []

        points: list[WeeklyPricePoint] = []
        for date_key in sorted(series.keys())[-outputsize:]:
            item = series.get(date_key, {})
            try:
                close_native = float(item.get("5. adjusted close", item.get("4. close")))
            except (TypeError, ValueError):
                continue
            try:
                volume_like = float(item.get("6. volume")) if item.get("6. volume") is not None else None
            except (TypeError, ValueError):
                volume_like = None
            points.append(
                WeeklyPricePoint(
                    instrument_id=symbol,
                    week_end_date=date_key,
                    close_native=close_native,
                    fx_rate_to_brl=1.0,
                    close_brl=close_native,
                    volume_like=volume_like,
                    provider=self.provider_name,
                    quality="adjusted",
                    collected_at=datetime.now().isoformat(),
                )
            )
        return points

    def get_quote(self, symbol: str) -> AssetQuoteResult | None:
        weekly = self.get_weekly_series(symbol, outputsize=1)
        if not weekly:
            return None
        latest = weekly[-1]
        return AssetQuoteResult(
            symbol=symbol,
            price=latest.close_native,
            currency="USD",
            exchange="",
            provider=self.provider_name,
        )
