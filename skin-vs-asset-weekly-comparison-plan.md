# Plan: Skin Vs Asset Weekly Comparison

**Generated**: 2026-04-04
**Estimated Complexity**: High

## Overview
Expand the current Streamlit portfolio app into a comparison platform where a user can compare any CS2 skin against any financial asset such as stocks, ETFs, indexes, REITs, or crypto using normalized weekly history, percentage return, absolute value change, and profit/loss calculations.

The key architectural decision is to split the feature into two data tracks:

- **Assets**: fetch weekly time-series from official financial APIs.
- **Skins**: build our own weekly historical series from safe local snapshots because current official CSFloat docs expose listing and item data but do not clearly expose a weekly historical price API.

This plan keeps the app aligned with its current safety model:

- no aggressive scraping
- no hidden high-frequency polling
- cache and cooldown aware refreshes
- manual and scheduled snapshot collection only
- local persistence for comparison history

## Assumptions
- The user wants support for comparing a skin against any user-selected asset symbol, not just a small curated list.
- The comparison baseline should work in BRL across both domains.
- Weekly history is the required primary timeframe for V1.
- Streamlit remains the frontend for now.
- SQLite is acceptable as the first local database.
- Any automation or recurring snapshot job will be planned but not implemented in this phase.

## Research Summary
- **CSFloat official docs** expose active listings, listing detail, item attributes, listing metadata, seller statistics, watchers, and SCM reference fields.
- **Alpha Vantage official docs** expose `TIME_SERIES_WEEKLY_ADJUSTED` for global equities with adjusted weekly history.
- **Twelve Data official docs** expose historical time-series retrieval with `start_date`, `end_date`, and `outputsize`, and their docs/catalog support articles describe instrument discovery and broad market coverage.
- **Streamlit guidance** supports this feature well with forms, session state, caching, and dashboard composition patterns, but data fetching must remain explicit and bounded to avoid rerun-driven API storms.

## Product Scope
### In scope
- Compare one skin versus one asset over a weekly timeline.
- Show weekly normalized performance in BRL.
- Show absolute value change, percentage change, and profit/loss for both sides.
- Support asset discovery, symbol resolution, and asset quote metadata.
- Persist local history for skins and assets in SQLite.
- Display a comparison dashboard with charts, tables, and summary insights.
- Add tests for time-series normalization, currency conversion, comparison math, persistence, and API fallbacks.

### Out of scope for V1
- Intraday comparison.
- Portfolio-level multi-asset benchmark blending.
- Brokerage connectivity.
- Automatic trading actions.
- Real-time websocket streaming.
- Fully automated cron setup inside this implementation phase.

## Architecture
### Data domains
- **Skin market domain**
  - source: CSFloat listing snapshots
  - fallback/reference: Steam `priceoverview` and `scm` fields when available
  - history source: local snapshots only
- **Asset market domain**
  - primary source: Twelve Data
  - fallback source: Alpha Vantage weekly adjusted
  - optional later source: Polygon or FMP if scale/rate limits require it

### Persistence
- local SQLite database for canonical series and metadata
- existing JSON storage remains for current app state
- JSON can still store quick snapshots, but SQLite becomes the source of truth for weekly comparisons

### Comparison model
- normalize both domains into one weekly series shape:
  - `instrument_id`
  - `date_week`
  - `close_brl`
  - `source`
  - `source_quality`
  - `volume_like`
  - `note`

### Comparison math
- `initial_value_brl`
- `current_value_brl`
- `value_change_brl = current - initial`
- `return_pct = (current / initial) - 1`
- `position_value_current = unit_count * current`
- `position_cost_brl`
- `profit_loss_brl = position_value_current - position_cost_brl`
- `profit_loss_pct = profit_loss_brl / position_cost_brl`

Support two viewing modes:

- **Normalized capital mode**
  - compare as if both started with the same capital, e.g. R$ 1,000
- **Real holding mode**
  - compare the user’s actual skin purchase price against a user-entered asset position

## Proposed Database Schema
### Table: `instruments`
- `id` TEXT PK
- `kind` TEXT (`skin`, `stock`, `etf`, `reit`, `index`, `crypto`)
- `display_name` TEXT
- `symbol` TEXT NULL
- `market_hash_name` TEXT NULL
- `currency` TEXT
- `exchange` TEXT NULL
- `provider_primary` TEXT
- `provider_fallback` TEXT NULL
- `is_active` INTEGER
- `created_at` TEXT
- `updated_at` TEXT

### Table: `instrument_metadata`
- `instrument_id` TEXT FK
- `payload_json` TEXT
- `updated_at` TEXT

### Table: `weekly_prices`
- `instrument_id` TEXT FK
- `week_end_date` TEXT
- `close_native` REAL
- `fx_rate_to_brl` REAL
- `close_brl` REAL
- `volume_like` REAL NULL
- `provider` TEXT
- `quality` TEXT
- `collected_at` TEXT
- unique key on (`instrument_id`, `week_end_date`, `provider`)

### Table: `skin_snapshots`
- `skin_id` TEXT
- `market_hash_name` TEXT
- `snapshot_at` TEXT
- `benchmark_price_brl` REAL
- `best_offer_brl` REAL
- `comparables_count` INTEGER
- `confidence` TEXT
- `watchers_total` INTEGER
- `scm_price_brl` REAL
- `scm_volume` INTEGER
- `details_json` TEXT

### Table: `asset_search_cache`
- `query` TEXT
- `results_json` TEXT
- `provider` TEXT
- `updated_at` TEXT

### Table: `comparison_profiles`
- `id` TEXT PK
- `skin_instrument_id` TEXT
- `asset_instrument_id` TEXT
- `mode` TEXT
- `asset_units` REAL
- `base_capital_brl` REAL
- `created_at` TEXT
- `updated_at` TEXT

## Integration Strategy
### Asset provider abstraction
Create an asset provider interface similar to current price providers:

- `search_assets(query)`
- `get_asset_quote(symbol)`
- `get_weekly_series(symbol, start_date, end_date)`
- `get_asset_metadata(symbol)`

Implementations:

- `TwelveDataProvider`
- `AlphaVantageProvider`

### Skin history service
Create a new service that converts periodic CSFloat snapshots into weekly points.

Rules:
- one canonical weekly point per `market_hash_name`
- prefer latest snapshot inside that ISO week
- use benchmark median as weekly close
- keep best listing and confidence in side metadata

### FX normalization
Continue normalizing to BRL.

Rules:
- use stored daily or weekly FX snapshots
- weekly asset close should be converted using corresponding weekly FX
- skin values already in BRL can keep `fx_rate_to_brl = 1`

### Safe refresh policy
- asset search: on explicit search submit only
- asset history: cache by symbol and date range with TTL
- skin weekly rebuild: from local snapshots only unless user explicitly refreshes
- no auto-refresh on slider changes
- backoff on provider failures
- clear cooldown status in UI

## UI Plan
### New page: `Comparar Skin vs Ativo`
**Goal**: user selects a skin and any asset, then compares weekly performance.

Sections:
- search and selection bar
- comparison mode selector
- asset metadata card
- skin metadata card
- normalized weekly chart
- absolute BRL chart
- summary KPI row
- detailed weekly table
- local history freshness/cooldown status

### Key interactions
- select existing skin from wallet
- search asset by ticker/name
- choose comparison mode:
  - same capital
  - real holding
- choose window:
  - 4 weeks
  - 8 weeks
  - 12 weeks
  - YTD
  - custom
- choose anchor:
  - purchase week
  - first common week
  - latest N weeks

### UI constraints
- all expensive fetches must be wrapped in forms
- use session state only for current selection and view controls
- use cached fetch functions for provider reads
- use tabs sparingly because hidden tab content still renders

## Code Organization Plan
### New files
- `app/services/db.py`
- `app/services/asset_providers/base.py`
- `app/services/asset_providers/twelve_data.py`
- `app/services/asset_providers/alpha_vantage.py`
- `app/services/asset_service.py`
- `app/services/skin_history_service.py`
- `app/services/fx_service.py`
- `app/services/comparison_history_service.py`
- `app/ui/comparar_ativo.py`
- `tests/test_asset_service.py`
- `tests/test_skin_history_service.py`
- `tests/test_comparison_math.py`
- `tests/test_db_schema.py`

### Existing files to update
- `app/config.py`
- `app/models.py`
- `app/main.py`
- `app/services/storage.py`
- `requirements.txt`

## Sprint Plan
## Sprint 1: Data Foundation
**Goal**: Introduce durable storage and domain models for cross-market comparison.
**Demo/Validation**:
- SQLite database initializes correctly.
- Core tables exist and can persist/retrieve normalized weekly rows.
- Existing app still boots without using new comparison features.

### Task 1.1: Add database bootstrap and migrations-lite
- **Location**: `app/services/db.py`, `app/config.py`
- **Description**: Add SQLite connection management, schema creation, and safe startup initialization.
- **Dependencies**: None
- **Acceptance Criteria**:
  - Database file path is configurable.
  - Tables for instruments, weekly_prices, snapshots, and profiles are created idempotently.
  - Writes are atomic and safe for local single-user usage.
- **Validation**:
  - Unit tests for schema existence.
  - Manual DB bootstrap check.

### Task 1.2: Add comparison domain models
- **Location**: `app/models.py`
- **Description**: Add Pydantic models for asset instruments, weekly series rows, comparison requests, comparison outputs, and asset metadata.
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Models cover both skin and asset domains cleanly.
  - Validation prevents missing key fields such as symbol or market hash name.
- **Validation**:
  - Model tests for serialization and invalid input cases.

### Task 1.3: Add repository layer for weekly series
- **Location**: `app/services/db.py`, `app/services/comparison_history_service.py`
- **Description**: Encapsulate reads/writes for weekly prices and search cache.
- **Dependencies**: Task 1.1, Task 1.2
- **Acceptance Criteria**:
  - Can upsert weekly points without duplicates.
  - Can query common date range between two instruments.
- **Validation**:
  - Unit tests for upsert, dedupe, and date alignment.

## Sprint 2: Asset Market Integration
**Goal**: Fetch and persist asset metadata and weekly price history.
**Demo/Validation**:
- User can search a symbol and fetch weekly history.
- Data lands in SQLite and can be reloaded without refetching.

### Task 2.1: Create asset provider interface
- **Location**: `app/services/asset_providers/base.py`
- **Description**: Define search, quote, metadata, and time-series methods.
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Interface matches our caching and fallback strategy.
- **Validation**:
  - Interface contract tests with mocks.

### Task 2.2: Implement Twelve Data provider
- **Location**: `app/services/asset_providers/twelve_data.py`
- **Description**: Add search and weekly series fetch using official docs and bounded query parameters.
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Asset search supports arbitrary user input.
  - Weekly history can be pulled over a bounded date range.
  - Caching prevents repeated identical searches.
- **Validation**:
  - Mocked response tests.
  - Error handling tests for empty search, invalid symbol, timeout.

### Task 2.3: Implement Alpha Vantage fallback provider
- **Location**: `app/services/asset_providers/alpha_vantage.py`
- **Description**: Add weekly adjusted series fallback and symbol search support if needed.
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Fallback can fill weekly adjusted history when primary fails or lacks data.
  - Response is normalized into the same weekly schema.
- **Validation**:
  - Mocked fallback tests.
  - Merge precedence tests between providers.

### Task 2.4: Build asset orchestration service
- **Location**: `app/services/asset_service.py`
- **Description**: Add provider ordering, cache, TTL, fallback, and persistence to SQLite.
- **Dependencies**: Task 2.2, Task 2.3
- **Acceptance Criteria**:
  - Search, quote, and weekly fetch all route through one safe service.
  - Provider errors do not crash the app.
- **Validation**:
  - Integration-style mocked tests for success, cache hit, fallback, and cooldown scenarios.

## Sprint 3: Skin Weekly History Engine
**Goal**: Convert safe skin snapshots into a normalized weekly history series.
**Demo/Validation**:
- Existing skin snapshots can be rolled up into weekly points.
- Weekly history is persisted and queryable.

### Task 3.1: Formalize skin snapshot persistence
- **Location**: `app/services/storage.py`, `app/services/comparison_service.py`
- **Description**: Ensure each comparison snapshot has stable fields needed for weekly rollup.
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Snapshots persist benchmark, best offer, confidence, and details.
  - Snapshot timestamps are reliable for weekly aggregation.
- **Validation**:
  - Snapshot persistence tests.

### Task 3.2: Create skin history rollup service
- **Location**: `app/services/skin_history_service.py`
- **Description**: Build a weekly close series from stored snapshots.
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - One weekly row per skin instrument.
  - Uses clear precedence rules when multiple snapshots exist in one week.
  - Handles missing weeks gracefully.
- **Validation**:
  - Unit tests for weekly bucketing and dedupe.

### Task 3.3: Add optional CSV import for legacy skin history
- **Location**: `app/services/skin_history_service.py`, `app/ui/comparar_ativo.py`
- **Description**: Allow importing older weekly skin price data to backfill tests and demos.
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - CSV import validates columns and normalizes to weekly schema.
  - Import is optional and does not disturb live snapshots.
- **Validation**:
  - CSV parser tests.
  - Invalid file rejection tests.

## Sprint 4: Comparison Engine
**Goal**: Produce aligned weekly comparison results between a skin and an asset.
**Demo/Validation**:
- Given one skin and one asset, the system returns aligned weekly rows plus summary KPIs.

### Task 4.1: Build weekly alignment logic
- **Location**: `app/services/comparison_history_service.py`
- **Description**: Align asset and skin weekly series on common dates.
- **Dependencies**: Sprint 2, Sprint 3
- **Acceptance Criteria**:
  - Supports first-common-week and latest-N-weeks modes.
  - Handles unequal history lengths.
- **Validation**:
  - Tests for partial overlaps and empty intersections.

### Task 4.2: Build comparison math engine
- **Location**: `app/services/comparison_history_service.py`
- **Description**: Calculate normalized capital and real holding comparison outputs.
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Returns BRL value change, percent return, and profit/loss for both sides.
  - Results remain stable with zero or missing initial values.
- **Validation**:
  - Edge-case tests for division by zero, missing first point, and negative PnL.

### Task 4.3: Add FX normalization service
- **Location**: `app/services/fx_service.py`
- **Description**: Persist and reuse FX rates for weekly normalization.
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - Assets fetched in non-BRL currencies can be compared in BRL.
  - FX fetches are cached and bounded.
- **Validation**:
  - Mocked FX service tests.
  - Normalization tests for USD to BRL weekly conversion.

## Sprint 5: Streamlit Comparison UI
**Goal**: Deliver a usable dashboard page for skin-vs-asset weekly comparison.
**Demo/Validation**:
- User can select a skin, search an asset, choose a mode, and view charts and tables.

### Task 5.1: Add page shell and state model
- **Location**: `app/ui/comparar_ativo.py`, `app/main.py`
- **Description**: Add the page, initialize session state, and structure the layout with forms and cards.
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - UI does not trigger heavy fetches outside explicit submit actions.
  - State persists correctly across reruns in the same session.
- **Validation**:
  - UI import smoke tests.
  - Session-state tests where practical.

### Task 5.2: Add asset search and selection UI
- **Location**: `app/ui/comparar_ativo.py`
- **Description**: Provide search box, result list, and selection summary card.
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Arbitrary search terms can resolve to asset candidates.
  - Selected asset metadata is visible before comparison.
- **Validation**:
  - Mocked service tests and manual demo checklist.

### Task 5.3: Add comparison dashboard blocks
- **Location**: `app/ui/comparar_ativo.py`
- **Description**: Add normalized chart, BRL chart, KPI row, and weekly breakdown table.
- **Dependencies**: Task 5.1, Sprint 4
- **Acceptance Criteria**:
  - Dashboard clearly shows both sides and comparison outcome.
  - Hidden tabs do not trigger unnecessary fetches.
- **Validation**:
  - Manual UI validation with seeded datasets.

### Task 5.4: Add freshness, provider, and confidence indicators
- **Location**: `app/ui/comparar_ativo.py`
- **Description**: Show snapshot age, provider source, fallback usage, and confidence.
- **Dependencies**: Task 5.3
- **Acceptance Criteria**:
  - User can see if the skin side is based on fresh snapshots or local history only.
  - User can see which provider supplied asset history.
- **Validation**:
  - UI state tests and manual checklist.

## Sprint 6: Quality, Safety, and Test Depth
**Goal**: Harden the system against bad data, provider outages, and regression risk.
**Demo/Validation**:
- Full test suite passes.
- Failure modes degrade clearly and safely.

### Task 6.1: Add provider throttling and bounded caching for assets
- **Location**: `app/services/asset_service.py`, `app/config.py`
- **Description**: Mirror current safe patterns: TTL, request spacing, fallback rules, and circuit breaking if needed.
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - Repeated asset searches do not hammer providers.
  - Time-series fetches are cached by symbol and date range.
- **Validation**:
  - Caching tests and rate-limit handling tests.

### Task 6.2: Add seeded demo data for weekly comparison
- **Location**: `app/data/`, `tests/fixtures/`
- **Description**: Provide sample weekly rows for one skin and one asset so the feature can be demoed and tested offline.
- **Dependencies**: Sprint 1, Sprint 4
- **Acceptance Criteria**:
  - UI can demo comparison without live API calls.
- **Validation**:
  - Fixture-driven tests.

### Task 6.3: Add regression tests for alignment and PnL correctness
- **Location**: `tests/test_comparison_math.py`, `tests/test_asset_service.py`, `tests/test_skin_history_service.py`
- **Description**: Expand coverage for weekly alignment, fallback paths, and math invariants.
- **Dependencies**: Sprint 4
- **Acceptance Criteria**:
  - Core comparison calculations are deterministic.
  - Tests cover common and failure paths.
- **Validation**:
  - CI/local unit suite.

## Testing Strategy
### Unit tests
- Pydantic model validation
- DB schema initialization
- weekly upsert and dedupe
- weekly alignment logic
- comparison math
- FX normalization
- CSV import validation
- provider response parsing

### Integration-style mocked tests
- Twelve Data search + weekly history
- Alpha Vantage fallback usage
- asset service cache hit vs live hit
- skin snapshot to weekly rollup
- comparison result generation from stored series

### UI smoke tests
- import each new page/module
- seed local DB and verify page renders
- ensure comparison form does not fetch until submit

### Manual verification checklist
- search arbitrary symbols like `AAPL`, `PETR4`, `IVVB11`, `BTC/USD`
- compare one skin with one stock in same-capital mode
- compare one skin with one stock in real-holding mode
- verify weekly chart aligns on common dates only
- verify all values are displayed in BRL
- verify provider/freshness/confidence badges
- verify stale or missing skin history produces graceful messaging

## Potential Risks & Gotchas
- **No official skin weekly history endpoint found**
  - Mitigation: build local weekly history from snapshots and optionally import CSV backfill.
- **Asset API rate limits**
  - Mitigation: bounded search, cached series, provider fallback, explicit submit-only fetches.
- **Symbol ambiguity**
  - Mitigation: store exchange and instrument metadata, show candidate selection UI.
- **Currency mismatch**
  - Mitigation: normalize all series into BRL with stored FX rates.
- **Corporate actions on assets**
  - Mitigation: prefer adjusted weekly series where available.
- **Sparse skin history early on**
  - Mitigation: message clearly, allow CSV import, and preserve local snapshot history from now on.
- **Streamlit reruns causing accidental refetches**
  - Mitigation: use forms, session state, and cached service boundaries.
- **Database and JSON dual-storage confusion**
  - Mitigation: define SQLite as the canonical source for weekly comparison features only.

## Rollback Plan
- Keep existing wallet, comparison, and JSON storage flows untouched.
- Ship new weekly comparison behind a new page and new service layer.
- If the feature underperforms, disable the page from `app/main.py` and leave DB unused.
- Because no existing core pricing flow is replaced, rollback is low-risk.

## Sources
- [CSFloat API Reference](https://docs.csfloat.com/)
- [Alpha Vantage Documentation](https://www.alphavantage.co/documentation/)
- [Twelve Data Docs](https://twelvedata.com/docs)
- [Twelve Data historical data article](https://support.twelvedata.com/en/articles/5214728-getting-historical-data)
- [Streamlit Dataframes Docs](https://docs.streamlit.io/develop/concepts/design/dataframes)
- [Streamlit API Reference](https://docs.streamlit.io/develop/api-reference)
