from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.models import ComparisonProfile, InstrumentKind, InstrumentMetadata, MarketInstrument, WeeklyPricePoint
from app.services import db


class DatabaseFoundationTests(unittest.TestCase):
    def test_initialize_database_creates_core_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            created = db.initialize_database(db_path)
            self.assertEqual(created, db_path)
            self.assertTrue(db_path.exists())

            with db.get_connection(db_path) as conn:
                tables = {
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }

            self.assertIn("instruments", tables)
            self.assertIn("instrument_metadata", tables)
            self.assertIn("weekly_prices", tables)
            self.assertIn("comparison_profiles", tables)

    def test_upsert_and_read_instrument(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            instrument = MarketInstrument(
                id="inst001",
                kind=InstrumentKind.STOCK,
                display_name="Apple Inc.",
                symbol="AAPL",
                currency="USD",
                exchange="NASDAQ",
                provider_primary="twelvedata",
                provider_fallback="alphavantage",
            )
            db.upsert_instrument(instrument, db_path)

            loaded = db.get_instrument("inst001", db_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.symbol, "AAPL")
            self.assertEqual(loaded.provider_primary, "twelvedata")

    def test_upsert_and_read_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            db.upsert_instrument(
                MarketInstrument(
                    id="inst_meta",
                    kind=InstrumentKind.SKIN,
                    display_name="AK-47 | Slate",
                    market_hash_name="AK-47 | Slate (Factory New)",
                    provider_primary="csfloat",
                ),
                db_path,
            )
            metadata = InstrumentMetadata(
                instrument_id="inst_meta",
                payload_json='{"collection":"The Bank Collection"}',
            )
            db.upsert_instrument_metadata(metadata, db_path)

            loaded = db.get_instrument_metadata("inst_meta", db_path)
            self.assertIsNotNone(loaded)
            self.assertIn("The Bank Collection", loaded.payload_json)

    def test_get_instrument_metadata_map_reads_multiple_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            for instrument_id in ["inst_a", "inst_b"]:
                db.upsert_instrument(
                    MarketInstrument(
                        id=instrument_id,
                        kind=InstrumentKind.STOCK,
                        display_name=instrument_id,
                        symbol=instrument_id.upper(),
                        provider_primary="twelvedata",
                    ),
                    db_path,
                )
                db.upsert_instrument_metadata(
                    InstrumentMetadata(
                        instrument_id=instrument_id,
                        payload_json=f'{{"sector":"{instrument_id}"}}',
                    ),
                    db_path,
                )

            metadata_map = db.get_instrument_metadata_map(["inst_a", "inst_b"], db_path)
            self.assertEqual(set(metadata_map.keys()), {"inst_a", "inst_b"})
            self.assertIn("inst_a", metadata_map["inst_a"].payload_json)

    def test_upsert_and_read_weekly_prices(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            db.upsert_instrument(
                MarketInstrument(
                    id="inst_price",
                    kind=InstrumentKind.ETF,
                    display_name="IVVB11",
                    symbol="IVVB11",
                    currency="BRL",
                    exchange="B3",
                    provider_primary="twelvedata",
                ),
                db_path,
            )
            points = [
                WeeklyPricePoint(
                    instrument_id="inst_price",
                    week_end_date="2026-03-20",
                    close_native=320.5,
                    fx_rate_to_brl=1.0,
                    close_brl=320.5,
                    volume_like=1000,
                    provider="twelvedata",
                    quality="high",
                ),
                WeeklyPricePoint(
                    instrument_id="inst_price",
                    week_end_date="2026-03-27",
                    close_native=330.2,
                    fx_rate_to_brl=1.0,
                    close_brl=330.2,
                    volume_like=1200,
                    provider="twelvedata",
                    quality="high",
                ),
            ]
            db.upsert_weekly_prices(points, db_path)

            loaded = db.get_weekly_prices("inst_price", db_path)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0].week_end_date, "2026-03-20")
            self.assertAlmostEqual(loaded[1].close_brl, 330.2)

    def test_save_and_read_comparison_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            db.upsert_instrument(
                MarketInstrument(
                    id="skin001",
                    kind=InstrumentKind.SKIN,
                    display_name="AK-47 | Slate",
                    market_hash_name="AK-47 | Slate (Factory New)",
                    provider_primary="csfloat",
                ),
                db_path,
            )
            db.upsert_instrument(
                MarketInstrument(
                    id="asset001",
                    kind=InstrumentKind.STOCK,
                    display_name="Apple Inc.",
                    symbol="AAPL",
                    currency="USD",
                    exchange="NASDAQ",
                    provider_primary="twelvedata",
                ),
                db_path,
            )

            profile = ComparisonProfile(
                id="cmp001",
                skin_instrument_id="skin001",
                asset_instrument_id="asset001",
                mode="same_capital",
                base_capital_brl=1500.0,
            )
            db.save_comparison_profile(profile, db_path)

            loaded = db.get_comparison_profile("cmp001", db_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.skin_instrument_id, "skin001")
            self.assertEqual(loaded.base_capital_brl, 1500.0)

    def test_seed_asset_catalog_imports_real_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            seed_path = Path("C:/Users/Administrator/Downloads/cs-skin-carteira-stream-lit/app/data/asset_seed.json")
            inserted = db.seed_asset_catalog(seed_path, db_path)

            instruments = db.list_instruments(db_path=db_path)
            self.assertGreaterEqual(inserted, 10)
            self.assertTrue(any(item.symbol == "AAPL" for item in instruments))
            self.assertTrue(any(item.symbol == "PETR4" for item in instruments))
            self.assertTrue(any(item.symbol == "BTC/USD" for item in instruments))

    def test_seed_weekly_price_cache_imports_asset_series(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            asset_seed_path = Path("C:/Users/Administrator/Downloads/cs-skin-carteira-stream-lit/app/data/asset_seed.json")
            weekly_seed_path = Path("C:/Users/Administrator/Downloads/cs-skin-carteira-stream-lit/app/data/asset_weekly_seed.json")
            db.seed_asset_catalog(asset_seed_path, db_path)
            inserted = db.seed_weekly_price_cache(weekly_seed_path, db_path)

            points = db.get_weekly_prices("asset_seed_googl", db_path)
            self.assertGreater(inserted, 20)
            self.assertEqual(len(points), 4)
            self.assertAlmostEqual(points[-1].close_brl, 917.22)

    def test_get_latest_weekly_price_map_returns_last_point(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_data.db"
            db.upsert_instrument(
                MarketInstrument(
                    id="asset_seed_test",
                    kind=InstrumentKind.STOCK,
                    display_name="Test Asset",
                    symbol="TEST",
                    currency="BRL",
                    provider_primary="seed_local",
                ),
                db_path,
            )
            db.upsert_weekly_prices(
                [
                    WeeklyPricePoint(
                        instrument_id="asset_seed_test",
                        week_end_date="2026-03-21",
                        close_native=10.0,
                        fx_rate_to_brl=1.0,
                        close_brl=10.0,
                        provider="seed_local",
                        quality="seed_local",
                    ),
                    WeeklyPricePoint(
                        instrument_id="asset_seed_test",
                        week_end_date="2026-03-28",
                        close_native=12.5,
                        fx_rate_to_brl=1.0,
                        close_brl=12.5,
                        provider="seed_local",
                        quality="seed_local",
                    ),
                ],
                db_path,
            )

            latest_map = db.get_latest_weekly_price_map(["asset_seed_test"], db_path)
            self.assertIn("asset_seed_test", latest_map)
            self.assertEqual(latest_map["asset_seed_test"].week_end_date, "2026-03-28")
            self.assertEqual(latest_map["asset_seed_test"].close_brl, 12.5)


if __name__ == "__main__":
    unittest.main()
