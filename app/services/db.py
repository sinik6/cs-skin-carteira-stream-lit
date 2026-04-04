"""Camada SQLite para historico semanal de skins e ativos."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.config import DATA_DIR, MARKET_DATA_DB_FILE
from app.models import AssetSearchResult, ComparisonProfile, InstrumentMetadata, MarketInstrument, WeeklyPricePoint


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def resolve_db_path(db_path: Path | None = None) -> Path:
    _ensure_dir()
    return db_path or MARKET_DATA_DB_FILE


@contextmanager
def get_connection(db_path: Path | None = None):
    path = resolve_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database(db_path: Path | None = None) -> Path:
    path = resolve_db_path(db_path)
    with get_connection(path) as conn:
        conn.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS instruments (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                display_name TEXT NOT NULL,
                symbol TEXT NOT NULL DEFAULT '',
                market_hash_name TEXT NOT NULL DEFAULT '',
                currency TEXT NOT NULL DEFAULT 'BRL',
                exchange TEXT NOT NULL DEFAULT '',
                provider_primary TEXT NOT NULL DEFAULT '',
                provider_fallback TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS instrument_metadata (
                instrument_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (instrument_id) REFERENCES instruments(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS weekly_prices (
                instrument_id TEXT NOT NULL,
                week_end_date TEXT NOT NULL,
                close_native REAL NOT NULL,
                fx_rate_to_brl REAL NOT NULL,
                close_brl REAL NOT NULL,
                volume_like REAL,
                provider TEXT NOT NULL DEFAULT '',
                quality TEXT NOT NULL DEFAULT '',
                collected_at TEXT NOT NULL,
                PRIMARY KEY (instrument_id, week_end_date, provider),
                FOREIGN KEY (instrument_id) REFERENCES instruments(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS comparison_profiles (
                id TEXT PRIMARY KEY,
                skin_instrument_id TEXT NOT NULL,
                asset_instrument_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                asset_units REAL NOT NULL DEFAULT 0,
                base_capital_brl REAL NOT NULL DEFAULT 1000,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (skin_instrument_id) REFERENCES instruments(id) ON DELETE CASCADE,
                FOREIGN KEY (asset_instrument_id) REFERENCES instruments(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS asset_search_cache (
                query TEXT NOT NULL,
                provider TEXT NOT NULL,
                results_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (query, provider)
            );

            CREATE INDEX IF NOT EXISTS idx_instruments_kind_symbol
                ON instruments(kind, symbol);

            CREATE INDEX IF NOT EXISTS idx_weekly_prices_instrument_week
                ON weekly_prices(instrument_id, week_end_date);
            """
        )
    return path


def upsert_instrument(instrument: MarketInstrument, db_path: Path | None = None) -> None:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO instruments (
                id, kind, display_name, symbol, market_hash_name, currency, exchange,
                provider_primary, provider_fallback, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                kind = excluded.kind,
                display_name = excluded.display_name,
                symbol = excluded.symbol,
                market_hash_name = excluded.market_hash_name,
                currency = excluded.currency,
                exchange = excluded.exchange,
                provider_primary = excluded.provider_primary,
                provider_fallback = excluded.provider_fallback,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            (
                instrument.id,
                instrument.kind,
                instrument.display_name,
                instrument.symbol,
                instrument.market_hash_name,
                instrument.currency,
                instrument.exchange,
                instrument.provider_primary,
                instrument.provider_fallback,
                1 if instrument.is_active else 0,
                instrument.created_at,
                instrument.updated_at,
            ),
        )


def get_instrument(instrument_id: str, db_path: Path | None = None) -> MarketInstrument | None:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM instruments WHERE id = ?", (instrument_id,)).fetchone()
    if not row:
        return None
    payload = dict(row)
    payload["is_active"] = bool(payload["is_active"])
    return MarketInstrument.model_validate(payload)


def upsert_instrument_metadata(metadata: InstrumentMetadata, db_path: Path | None = None) -> None:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO instrument_metadata (instrument_id, payload_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(instrument_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (metadata.instrument_id, metadata.payload_json, metadata.updated_at),
        )


def get_instrument_metadata(instrument_id: str, db_path: Path | None = None) -> InstrumentMetadata | None:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM instrument_metadata WHERE instrument_id = ?", (instrument_id,)).fetchone()
    return InstrumentMetadata.model_validate(dict(row)) if row else None


def get_instrument_metadata_map(instrument_ids: list[str], db_path: Path | None = None) -> dict[str, InstrumentMetadata]:
    initialize_database(db_path)
    normalized_ids = [item for item in instrument_ids if item]
    if not normalized_ids:
        return {}

    placeholders = ",".join("?" for _ in normalized_ids)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM instrument_metadata WHERE instrument_id IN ({placeholders})",
            tuple(normalized_ids),
        ).fetchall()
    return {
        row["instrument_id"]: InstrumentMetadata.model_validate(dict(row))
        for row in rows
    }


def upsert_weekly_prices(points: list[WeeklyPricePoint], db_path: Path | None = None) -> None:
    if not points:
        return
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO weekly_prices (
                instrument_id, week_end_date, close_native, fx_rate_to_brl, close_brl,
                volume_like, provider, quality, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instrument_id, week_end_date, provider) DO UPDATE SET
                close_native = excluded.close_native,
                fx_rate_to_brl = excluded.fx_rate_to_brl,
                close_brl = excluded.close_brl,
                volume_like = excluded.volume_like,
                quality = excluded.quality,
                collected_at = excluded.collected_at
            """,
            [
                (
                    point.instrument_id,
                    point.week_end_date,
                    point.close_native,
                    point.fx_rate_to_brl,
                    point.close_brl,
                    point.volume_like,
                    point.provider,
                    point.quality,
                    point.collected_at,
                )
                for point in points
            ],
        )


def get_weekly_prices(instrument_id: str, db_path: Path | None = None) -> list[WeeklyPricePoint]:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT instrument_id, week_end_date, close_native, fx_rate_to_brl, close_brl,
                   volume_like, provider, quality, collected_at
            FROM weekly_prices
            WHERE instrument_id = ?
            ORDER BY week_end_date ASC, provider ASC
            """,
            (instrument_id,),
        ).fetchall()
    return [WeeklyPricePoint.model_validate(dict(row)) for row in rows]


def get_latest_weekly_price_map(instrument_ids: list[str], db_path: Path | None = None) -> dict[str, WeeklyPricePoint]:
    initialize_database(db_path)
    normalized_ids = [item for item in instrument_ids if item]
    if not normalized_ids:
        return {}

    placeholders = ",".join("?" for _ in normalized_ids)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT wp.instrument_id, wp.week_end_date, wp.close_native, wp.fx_rate_to_brl, wp.close_brl,
                   wp.volume_like, wp.provider, wp.quality, wp.collected_at
            FROM weekly_prices wp
            INNER JOIN (
                SELECT instrument_id, MAX(week_end_date) AS max_week
                FROM weekly_prices
                WHERE instrument_id IN ({placeholders})
                GROUP BY instrument_id
            ) latest
            ON wp.instrument_id = latest.instrument_id AND wp.week_end_date = latest.max_week
            ORDER BY wp.instrument_id ASC, wp.provider ASC
            """,
            tuple(normalized_ids),
        ).fetchall()

    latest_by_id: dict[str, WeeklyPricePoint] = {}
    for row in rows:
        instrument_id = row["instrument_id"]
        if instrument_id not in latest_by_id:
            latest_by_id[instrument_id] = WeeklyPricePoint.model_validate(dict(row))
    return latest_by_id


def save_comparison_profile(profile: ComparisonProfile, db_path: Path | None = None) -> None:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO comparison_profiles (
                id, skin_instrument_id, asset_instrument_id, mode,
                asset_units, base_capital_brl, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                skin_instrument_id = excluded.skin_instrument_id,
                asset_instrument_id = excluded.asset_instrument_id,
                mode = excluded.mode,
                asset_units = excluded.asset_units,
                base_capital_brl = excluded.base_capital_brl,
                updated_at = excluded.updated_at
            """,
            (
                profile.id,
                profile.skin_instrument_id,
                profile.asset_instrument_id,
                profile.mode,
                profile.asset_units,
                profile.base_capital_brl,
                profile.created_at,
                profile.updated_at,
            ),
        )


def get_comparison_profile(profile_id: str, db_path: Path | None = None) -> ComparisonProfile | None:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM comparison_profiles WHERE id = ?", (profile_id,)).fetchone()
    return ComparisonProfile.model_validate(dict(row)) if row else None


def save_asset_search_cache(query: str, provider: str, results: list[AssetSearchResult], updated_at: str, db_path: Path | None = None) -> None:
    initialize_database(db_path)
    payload = json.dumps([item.model_dump() for item in results])
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO asset_search_cache (query, provider, results_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(query, provider) DO UPDATE SET
                results_json = excluded.results_json,
                updated_at = excluded.updated_at
            """,
            (query.strip().lower(), provider, payload, updated_at),
        )


def get_asset_search_cache(query: str, provider: str, db_path: Path | None = None) -> tuple[list[AssetSearchResult], str] | None:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT results_json, updated_at FROM asset_search_cache WHERE query = ? AND provider = ?",
            (query.strip().lower(), provider),
        ).fetchone()
    if not row:
        return None
    payload = json.loads(row["results_json"])
    return ([AssetSearchResult.model_validate(item) for item in payload], row["updated_at"])


def list_instruments(kind: str | None = None, db_path: Path | None = None) -> list[MarketInstrument]:
    initialize_database(db_path)
    query = "SELECT * FROM instruments"
    params: tuple = ()
    if kind:
        query += " WHERE kind = ?"
        params = (kind,)
    query += " ORDER BY display_name ASC"
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    instruments: list[MarketInstrument] = []
    for row in rows:
        payload = dict(row)
        payload["is_active"] = bool(payload["is_active"])
        instruments.append(MarketInstrument.model_validate(payload))
    return instruments


def seed_asset_catalog(seed_path: Path, db_path: Path | None = None) -> int:
    initialize_database(db_path)
    if not seed_path.exists():
        return 0

    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        return 0

    inserted = 0
    for raw in assets:
        metadata_payload = raw.pop("metadata", {})
        instrument = MarketInstrument.model_validate(
            {
                **raw,
                "created_at": raw.get("created_at", datetime.now().isoformat()),
                "updated_at": datetime.now().isoformat(),
            }
        )
        upsert_instrument(instrument, db_path)
        upsert_instrument_metadata(
            InstrumentMetadata(
                instrument_id=instrument.id,
                payload_json=json.dumps(metadata_payload or {}),
                updated_at=datetime.now().isoformat(),
            ),
            db_path,
        )
        inserted += 1
    return inserted


def seed_weekly_price_cache(seed_path: Path, db_path: Path | None = None) -> int:
    initialize_database(db_path)
    if not seed_path.exists():
        return 0

    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    series_entries = payload.get("series", [])
    if not isinstance(series_entries, list):
        return 0

    points: list[WeeklyPricePoint] = []
    for entry in series_entries:
        instrument_id = str(entry.get("instrument_id", ""))
        provider = str(entry.get("provider", "seed_local"))
        quality = str(entry.get("quality", "seed_local"))
        point_rows = entry.get("points", [])
        if not instrument_id or not isinstance(point_rows, list):
            continue

        for row in point_rows:
            if not isinstance(row, list) or len(row) < 3:
                continue
            week_end_date = str(row[0])
            close_native = float(row[1])
            fx_rate = float(row[2])
            close_brl = round(close_native * fx_rate, 2)
            points.append(
                WeeklyPricePoint(
                    instrument_id=instrument_id,
                    week_end_date=week_end_date,
                    close_native=close_native,
                    fx_rate_to_brl=fx_rate,
                    close_brl=close_brl,
                    volume_like=None,
                    provider=provider,
                    quality=quality,
                )
            )

    upsert_weekly_prices(points, db_path)
    return len(points)
