from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.models import ApiConfig, AssetSearchResult, MarketInstrument, WeeklyPricePoint
from app.services import db
from app.services.asset_providers.alpha_vantage import AlphaVantageProvider
from app.services.asset_providers.twelvedata import TwelveDataProvider
from app.services.asset_service import AssetService


class TwelveDataProviderTests(unittest.TestCase):
    def test_search_assets_maps_response(self) -> None:
        provider = TwelveDataProvider("key")
        response = Mock()
        response.json.return_value = {
            "data": [
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc",
                    "exchange": "NASDAQ",
                    "currency": "USD",
                    "country": "United States",
                    "type": "Common Stock",
                }
            ]
        }
        response.raise_for_status.return_value = None

        with patch.object(provider._session, "get", return_value=response):
            results = provider.search_assets("AAPL")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].symbol, "AAPL")
        self.assertEqual(results[0].provider, "twelvedata")

    def test_weekly_series_maps_values(self) -> None:
        provider = TwelveDataProvider("key")
        response = Mock()
        response.json.return_value = {
            "meta": {"currency": "USD"},
            "values": [
                {"datetime": "2026-03-28", "close": "102.5", "volume": "1000"},
                {"datetime": "2026-03-21", "close": "100.0", "volume": "900"},
            ],
        }
        response.raise_for_status.return_value = None

        with patch.object(provider._session, "get", return_value=response):
            points = provider.get_weekly_series("AAPL", outputsize=2)

        self.assertEqual(len(points), 2)
        self.assertEqual(points[0].week_end_date, "2026-03-21")
        self.assertAlmostEqual(points[1].close_native, 102.5)


class AlphaVantageProviderTests(unittest.TestCase):
    def test_search_assets_maps_best_matches(self) -> None:
        provider = AlphaVantageProvider("key")
        response = Mock()
        response.json.return_value = {
            "bestMatches": [
                {
                    "1. symbol": "MSFT",
                    "2. name": "Microsoft Corporation",
                    "3. type": "Equity",
                    "4. region": "United States",
                    "8. currency": "USD",
                }
            ]
        }
        response.raise_for_status.return_value = None

        with patch.object(provider._session, "get", return_value=response):
            results = provider.search_assets("MSFT")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].symbol, "MSFT")
        self.assertEqual(results[0].provider, "alphavantage")


class AssetServiceTests(unittest.TestCase):
    def test_search_assets_uses_primary_then_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            db.initialize_database(db_path)
            service = AssetService(ApiConfig(twelvedata_api_key="td_key", alphavantage_api_key="av_key"))

            result = AssetSearchResult(
                symbol="AAPL",
                name="Apple Inc.",
                instrument_type="Common Stock",
                exchange="NASDAQ",
                currency="USD",
                country="United States",
                provider="twelvedata",
            )

            with patch("app.services.asset_service.db.get_asset_search_cache", return_value=None), \
                 patch.object(service._twelvedata, "search_assets", return_value=[result]) as mock_primary, \
                 patch("app.services.asset_service.db.save_asset_search_cache") as mock_save:
                results = service.search_assets("AAPL")

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].symbol, "AAPL")
            self.assertEqual(mock_primary.call_count, 1)
            self.assertEqual(mock_save.call_count, 1)

    def test_search_assets_falls_back_to_alpha_vantage(self) -> None:
        service = AssetService(ApiConfig(twelvedata_api_key="td_key", alphavantage_api_key="av_key"))
        fallback = AssetSearchResult(
            symbol="PETR4",
            name="Petrobras",
            instrument_type="Equity",
            exchange="Brazil",
            currency="BRL",
            country="Brazil",
            provider="alphavantage",
        )

        with patch("app.services.asset_service.db.get_asset_search_cache", return_value=None), \
             patch.object(service._twelvedata, "search_assets", return_value=[]), \
             patch.object(service._alphavantage, "search_assets", return_value=[fallback]) as mock_fallback:
            results = service.search_assets("PETR4")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].provider, "alphavantage")
        self.assertEqual(mock_fallback.call_count, 1)

    def test_fetch_weekly_series_persists_points(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            original_db_file = db.MARKET_DATA_DB_FILE
            try:
                db.MARKET_DATA_DB_FILE = db_path
                db.initialize_database(db_path)

                service = AssetService(ApiConfig(twelvedata_api_key="td_key"))
                instrument = MarketInstrument(
                    id="asset_twelvedata_aapl",
                    kind="stock",
                    display_name="Apple Inc.",
                    symbol="AAPL",
                    currency="USD",
                    exchange="NASDAQ",
                    provider_primary="twelvedata",
                )
                db.upsert_instrument(instrument, db_path)

                with patch.object(
                    service._twelvedata,
                    "get_weekly_series",
                    return_value=[
                        WeeklyPricePoint(
                            instrument_id="AAPL",
                            week_end_date="2026-03-21",
                            close_native=100.0,
                            fx_rate_to_brl=1.0,
                            close_brl=100.0,
                            provider="twelvedata",
                            quality="currency:USD",
                        )
                    ],
                ):
                    points = service.fetch_weekly_series(instrument, outputsize=1)

                self.assertEqual(len(points), 1)
                saved = db.get_weekly_prices(instrument.id, db_path)
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0].instrument_id, instrument.id)
            finally:
                db.MARKET_DATA_DB_FILE = original_db_file

    def test_list_catalog_assets_reads_seeded_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            original_db_file = db.MARKET_DATA_DB_FILE
            try:
                db.MARKET_DATA_DB_FILE = db_path
                db.seed_asset_catalog(
                    Path("C:/Users/Administrator/Downloads/cs-skin-carteira-stream-lit/app/data/asset_seed.json"),
                    db_path,
                )
                service = AssetService(ApiConfig())
                assets = service.list_catalog_assets()
                self.assertTrue(any(item.symbol == "IVVB11" for item in assets))
                self.assertTrue(any(item.symbol == "QQQ" for item in assets))
            finally:
                db.MARKET_DATA_DB_FILE = original_db_file


if __name__ == "__main__":
    unittest.main()
