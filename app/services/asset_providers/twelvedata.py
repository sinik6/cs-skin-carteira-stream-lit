"""Provider de ativos via Twelve Data."""

from __future__ import annotations

import logging
from datetime import datetime

import requests

from app.models import AssetSearchResult, WeeklyPricePoint
from app.services.asset_providers.base import AssetProvider, AssetQuoteResult

logger = logging.getLogger(__name__)

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"


class TwelveDataProvider(AssetProvider):
    provider_name = "twelvedata"

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
            f"{TWELVE_DATA_BASE_URL}/stocks",
            params={"symbol": query, "apikey": self._api_key},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data", payload if isinstance(payload, list) else [])
        if not isinstance(rows, list):
            return []

        results: list[AssetSearchResult] = []
        for item in rows[:15]:
            results.append(
                AssetSearchResult(
                    symbol=str(item.get("symbol", "")),
                    name=str(item.get("name", "")),
                    instrument_type=str(item.get("type", item.get("instrument_type", "stock"))),
                    exchange=str(item.get("exchange", "")),
                    currency=str(item.get("currency", "USD")),
                    country=str(item.get("country", "")),
                    provider=self.provider_name,
                )
            )
        return results

    def get_weekly_series(self, symbol: str, outputsize: int = 52) -> list[WeeklyPricePoint]:
        if not self._api_key:
            return []
        resp = self._session.get(
            f"{TWELVE_DATA_BASE_URL}/time_series",
            params={
                "symbol": symbol,
                "interval": "1week",
                "outputsize": outputsize,
                "apikey": self._api_key,
                "format": "JSON",
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        values = payload.get("values", [])
        meta = payload.get("meta", {})
        currency = str(meta.get("currency", "USD"))
        if not isinstance(values, list):
            return []

        points: list[WeeklyPricePoint] = []
        for item in reversed(values):
            try:
                close_native = float(item.get("close"))
            except (TypeError, ValueError):
                continue
            volume_like = item.get("volume")
            try:
                volume_like = float(volume_like) if volume_like is not None else None
            except (TypeError, ValueError):
                volume_like = None
            points.append(
                WeeklyPricePoint(
                    instrument_id=symbol,
                    week_end_date=str(item.get("datetime", "")),
                    close_native=close_native,
                    fx_rate_to_brl=1.0,
                    close_brl=close_native,
                    volume_like=volume_like,
                    provider=self.provider_name,
                    quality=f"currency:{currency}",
                    collected_at=datetime.now().isoformat(),
                )
            )
        return points

    def get_quote(self, symbol: str) -> AssetQuoteResult | None:
        if not self._api_key:
            return None
        resp = self._session.get(
            f"{TWELVE_DATA_BASE_URL}/quote",
            params={"symbol": symbol, "apikey": self._api_key},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        try:
            price = float(payload.get("close"))
        except (TypeError, ValueError):
            return None
        return AssetQuoteResult(
            symbol=symbol,
            price=price,
            currency=str(payload.get("currency", "USD")),
            exchange=str(payload.get("exchange", "")),
            provider=self.provider_name,
        )
