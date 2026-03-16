# Tasks.md

Phased implementation plan. MVP-first: get one market working end-to-end before adding the second. KRX is chosen as the first market because `pykrx` (the selected v1 Korea source) requires no API key, provides adjusted prices, and has minimal rate-limit overhead (bulk per-date fetch; polite pacing sufficient). The official KRX Open API was evaluated and deferred to fallback/future role — see PRD.md and TRD.md for rationale.

---

## Phase 1: Project Skeleton & Config

### Repository Setup

- [x]Initialize Python project structure:
  ```
  getstock/
  ├── __init__.py
  ├── __main__.py          # CLI entry point (`python -m getstock`)
  ├── cli.py               # Click CLI definitions
  ├── config.py            # Config + env loading
  ├── schema.py            # Canonical schema constants (column names, types)
  ├── sources/
  │   ├── __init__.py
  │   ├── krx.py           # KRX fetcher via pykrx
  │   └── tiingo.py        # Tiingo fetcher via requests
  ├── normalize.py         # Source → canonical schema mapping
  ├── validate.py          # Validation rules (V1–V8)
  ├── universe.py          # Universe management & delisting detection
  ├── quarantine.py        # Quarantine handling
  ├── storage.py           # Parquet read/write with atomic writes
  ├── pipeline.py          # Orchestration: ties ingestion → normalize → validate → store
  ├── query.py             # DuckDB query helpers
  └── logging_config.py    # Logging setup
  tests/
  ├── __init__.py
  ├── conftest.py          # Shared fixtures (tmp data dirs, sample DataFrames)
  ├── fixtures/            # Recorded API responses
  ├── test_config.py
  ├── test_schema.py
  ├── test_normalize.py
  ├── test_validate.py
  ├── test_storage.py
  ├── test_universe.py
  ├── test_quarantine.py
  ├── test_pipeline.py
  ├── test_sources/
  │   ├── test_krx.py
  │   └── test_tiingo.py
  └── test_query.py
  config.yaml
  .env.example
  .gitignore
  pyproject.toml
  ```
- [x]Create `pyproject.toml` with dependencies: `pandas`, `pyarrow`, `duckdb`, `pykrx`, `requests`, `python-dotenv`, `pyyaml`, `exchange-calendars`, `click`. Dev dependencies: `pytest`, `responses` (HTTP mocking).
- [x]Create `.gitignore`: `data/`, `.env`, `__pycache__/`, `*.egg-info/`, `.venv/`, `dist/`
- [x]Create `.env.example`: `TIINGO_API_KEY=your_api_key_here`

### Config & Logging

- [x]Implement `config.py`: Load `config.yaml` and `.env` via `python-dotenv`. Validate at startup: `TIINGO_API_KEY` required only when `--market us`. Expose config as a dataclass or typed dict.
- [x]Create `config.yaml` per TRD spec (markets, exchange calendars, universe filter, backfill lookback, validation thresholds, delisting safety threshold, logging settings).
- [x]Implement `logging_config.py`: Configure Python `logging` with format `%(asctime)s | %(levelname)s | %(name)s | %(message)s`. Stdout always; file to `data/logs/{date}_{market}.log` if enabled.

### Schema Constants

- [x]Implement `schema.py`: Define canonical column names and dtypes as constants for OHLCV, dividends, splits, instrument metadata, quarantine. Used by normalize, validate, and storage modules for consistency.

### CLI Scaffold

- [x]Implement `cli.py` with `click` commands (stubs that log and exit):
  - `python -m getstock run --market {krx|us} [--date YYYY-MM-DD]`
  - `python -m getstock backfill --market {krx|us} --start YYYY-MM-DD --end YYYY-MM-DD`
  - `python -m getstock query --market {krx|us} [--ticker TICKER] [--start DATE] [--end DATE]`
- [x]Implement `__main__.py` to invoke CLI.
- [x]`run` command: Use `exchange_calendars` to determine if `--date` (or today) is a trading day. Exit 0 with log message if not.

### Milestone check: `python -m getstock run --market krx` exits cleanly with "not a trading day" or "stub: would run pipeline".

---

## Phase 2: Storage & Validation Foundation

Build the write/read layer and validation before ingestion, so the first real data fetch can immediately go through the full path.

### Parquet Storage (`storage.py`)

- [x]Implement `write_parquet(df, path)`: Atomic write (write to `{path}.tmp`, then `os.replace` to `{path}`). Create parent directories. Enforce schema dtypes from `schema.py`.
- [x]Implement `read_parquet(path) → DataFrame`: Read single Parquet file.
- [x]Implement path builders: `ohlcv_path(data_dir, market, date)`, `dividends_path(...)`, `splits_path(...)`, `universe_path(...)`, `instruments_path(...)`, `quarantine_path(...)`, `run_manifest_path(...)`. All return absolute paths matching the TRD directory layout.
- [x]Implement `write_ohlcv(df, market, date, data_dir)`: Sort by `source_id`, enforce schema, write atomically.
- [x]Implement `write_instruments(df, market, data_dir)`: Overwrite metadata file.
- [x]Implement `write_quarantine(df, market, date, data_dir)`: Write quarantine log for date+market.
- [x]Implement `write_run_manifest(summary, market, date, data_dir)`: Write JSON run manifest to `data/meta/runs/{YYYY-MM-DD}_{market}.json`. Contains: market, date, status, started_at, finished_at, duration_seconds, universe_size, fetched_count, quarantined_count, files_written, errors. Overwritten on re-run.

### Validation (`validate.py`)

- [x]Implement `validate_ohlcv(df, target_date) → (valid_df, quarantine_df)`:
  - V1: Positive prices (open, high, low, close > 0) → quarantine
  - V2: high >= low → quarantine
  - V3: high >= open and high >= close → quarantine
  - V4: low <= open and low <= close → quarantine
  - V5: volume >= 0 → quarantine
  - V6: date matches target_date → warning only
  - V7: unique (source_id, date) → keep last, warn
  - V8: price spike > 50% from previous close → warning only
- [x]Validate adjusted prices if present (adj_close > 0, adj_high >= adj_low) → quarantine
- [x]Return `(clean_df, quarantine_df)`. Quarantine df has columns: `source_id, ticker, date, stage, error_type, error_detail`.

### Quarantine (`quarantine.py`)

- [x]Implement `merge_quarantine(ingestion_errors_df, validation_errors_df) → combined_df`: Combine quarantine entries from different stages.
- [x]Implement `write_quarantine_log(combined_df, market, date, data_dir)`: Write via storage module.

### Tests for Phase 2

- [x]`test_storage.py`: Test atomic write (verify no partial files on simulated crash). Test path builders. Test round-trip write/read with schema enforcement.
- [x]`test_validate.py`: Test each validation rule (V1–V8) with crafted DataFrames. Test quarantine output schema. Test that valid rows are not affected by invalid rows.
- [x]`test_quarantine.py`: Test merge logic. Test write/read round-trip.
- [x]`conftest.py`: Create shared fixtures: sample OHLCV DataFrame, tmp `data_dir` via `tmp_path`.

### Milestone check: Can write a hand-crafted OHLCV DataFrame → validate → store to Parquet → read back via DuckDB.

---

## Phase 3: KRX Ingestion (First Market, End-to-End)

### Universe Management (`universe.py`)

- [x]Implement `fetch_universe_krx(date) → DataFrame`: Use `pykrx.stock.get_market_ticker_list(date, market="KOSPI")` + `market="KOSDAQ"`. For each ticker, get name via `get_market_ticker_name()`. Map to instrument metadata schema with `source_id` = KRX 6-digit code, `asset_type` = "stock", `exchange` = KOSPI/KOSDAQ.
- [x]Implement `detect_delistings(new_universe_df, stored_instruments_df, safety_threshold=0.20) → updated_instruments_df`:
  - Compare `source_id` sets.
  - If missing count > safety_threshold × active count: log error, return stored instruments unchanged.
  - Otherwise: mark missing instruments as `is_active=false, delisted_date=today`.
  - Handle re-listing: if previously delisted instrument reappears, set `is_active=true`, clear `delisted_date`, log warning.
  - Merge new instruments (`first_seen=today`).
  - Update `ticker`, `name`, `last_updated` for all instruments from new universe.

### KRX Fetcher (`sources/krx.py`)

- [x]Implement `fetch_ohlcv_krx(date) → DataFrame`: Use `pykrx.stock.get_market_ohlcv(date, market="ALL")`. Returns all tickers for one date. Map columns to canonical schema. Set `source_id` = index (KRX ticker code), `market` = "krx", `source` = "pykrx", `fetched_at` = utcnow(). Set `adj_*` columns to null initially (raw-only from bulk API).
- [x]Implement `fetch_adjusted_krx(date, tickers) → DataFrame`: For each ticker, call `pykrx.stock.get_market_ohlcv_by_date(date, date, ticker, adjusted=True)`. Add 0.5s delay between calls. Return DataFrame with `source_id`, `date`, `adj_open`, `adj_high`, `adj_low`, `adj_close`, `adj_volume`. Wrap per-ticker calls in try/except; collect failures.
- [x]Implement `merge_raw_adjusted(raw_df, adjusted_df) → DataFrame`: Left-join on `(source_id, date)`. Raw rows without adjusted data get null `adj_*` columns.
- [x]Implement KRX dividend/split fetch (best-effort): Use available `pykrx` APIs. If data is sparse or unavailable, return empty DataFrame and log warning. Do not block pipeline on this.

### Normalization (`normalize.py`)

- [x]Implement `normalize_ohlcv(df, source) → DataFrame`: Map source-specific column names to canonical names. Ensure `date` is `DATE` type (strip time). Ensure `source_id` is `VARCHAR`. Ensure price columns are `DOUBLE`. Ensure volume columns are `BIGINT`.
- [x]Implement `normalize_dividends(df, source) → DataFrame`: Map to canonical dividends schema.
- [x]Implement `normalize_splits(df, source) → DataFrame`: Map to canonical splits schema.

### Pipeline Orchestration (`pipeline.py`)

- [x]Implement `run_daily(market, date, config) → RunSummary`:
  1. Fetch universe → detect delistings → write instrument metadata
  2. Fetch raw OHLCV (bulk) → fetch adjusted OHLCV → merge → normalize
  3. Validate → split into valid + quarantine
  4. Write OHLCV Parquet
  5. Fetch dividends/splits (best-effort) → normalize → write Parquet
  6. Write universe snapshot
  7. Write quarantine log (merged ingestion + validation errors)
  8. Write run manifest JSON to `data/meta/runs/{YYYY-MM-DD}_{market}.json` (counts, status, timing, errors)
  9. Log run summary (universe size, fetched count, quarantined count, duration)
  10. Return summary dataclass with counts and status
- [x]Implement `run_backfill(market, start_date, end_date, config)`: Iterate over trading dates using `exchange_calendars`. Call `run_daily` per date. Log progress.
- [x]Wire `cli.py` `run` and `backfill` commands to `pipeline.py`.

### Tests for Phase 3

- [x]`tests/fixtures/krx_ohlcv_sample.py`: Sample DataFrames mimicking `pykrx` output for 5 tickers, 3 dates. Include one ticker with bad data (negative price) for quarantine testing.
- [x]`test_sources/test_krx.py`: Mock `pykrx` calls. Test `fetch_ohlcv_krx`, `fetch_adjusted_krx`. Test per-ticker error handling.
- [x]`test_normalize.py`: Test KRX raw data → canonical schema mapping.
- [x]`test_universe.py`: Test delisting detection with safety threshold. Test re-listing. Test first-run (no stored metadata).
- [x]`test_pipeline.py`: Integration test with mocked `pykrx`. Run pipeline for 1 date, 5 tickers. Verify: Parquet files at correct paths, schema matches, quarantine file exists for bad ticker, DuckDB query returns expected rows.
- [x]Test idempotency: Run pipeline twice on same date, verify output files identical.
- [x]Test holiday: Mock a non-trading day, verify early exit.

### Milestone check: `python -m getstock run --market krx` fetches real KRX data for today (or `--date`), writes Parquet, queryable via DuckDB.

---

## Phase 4: Tiingo / US Ingestion (Second Market)

### Tiingo Fetcher (`sources/tiingo.py`)

- [x]Implement `fetch_universe_tiingo(api_key, universe_filter, config) → DataFrame`: Download supported tickers ZIP, parse CSV. Filter to `assetType` in `["Stock", "ETF"]`, `priceCurrency == "USD"`, active (`endDate` null or future). Apply universe filter from config (`all`, `watchlist`, or CSV path). Map to instrument metadata schema with `source_id` = Tiingo ticker.
- [x]Implement `fetch_ohlcv_tiingo(ticker, start_date, end_date, api_key) → DataFrame`: Call `GET /tiingo/daily/<ticker>/prices`. Parse JSON response. Returns raw + adjusted fields. Single-ticker call.
- [x]Implement `fetch_ohlcv_batch_tiingo(tickers, date, api_key) → (DataFrame, list[QuarantineEntry])`: Loop over tickers, call `fetch_ohlcv_tiingo` per ticker. Implement adaptive rate limiting: track `X-RateLimit-Remaining` headers, sleep when approaching limit. On 429, wait for `Retry-After` (default 60s). On per-ticker failure (timeout, 4xx, 5xx), add to quarantine list and continue. Return merged DataFrame + list of failures.
- [x]Implement Tiingo dividend/split derivation (best-effort): Compare `close` vs `adjClose` ratios across consecutive days to detect dividend events. Or skip in v1 and log that dividends/splits are not independently tracked for US. Adjusted prices already account for them.

### US Universe & Delisting

- [x]Wire `fetch_universe_tiingo` into `universe.py`. Reuse `detect_delistings()` (same logic, different source). Tiingo uses `endDate` field for explicit delisting; also compare against stored metadata.

### US Normalization

- [x]Add Tiingo normalization to `normalize.py`: Map Tiingo JSON fields (`adjOpen`, `adjHigh`, `adjLow`, `adjClose`, `adjVolume`) to canonical `adj_*` columns. Map `date` (ISO string) to `DATE`.

### US Pipeline Integration

- [x]Wire Tiingo fetcher into `pipeline.py` `run_daily` for `market=us`. Same orchestration flow: universe → OHLCV → normalize → validate → store.
- [x]Add `--date` override for US backfill.

### Tests for Phase 4

- [x]`tests/fixtures/tiingo_ohlcv_sample.json`: Recorded Tiingo API response for 3 tickers, 1 date. Include one with missing `adjClose` for null handling.
- [x]`tests/fixtures/tiingo_universe_sample.csv`: Sample supported tickers CSV (10 rows).
- [x]`test_sources/test_tiingo.py`: Mock HTTP responses with `responses` library. Test OHLCV fetch, rate limiting (mock 429), per-ticker error handling. Test universe download + filter.
- [x]`test_pipeline.py`: Add US integration test. Same pattern as KRX: mocked API, 1 date, 5 tickers, verify Parquet output.

### Milestone check: `python -m getstock run --market us` fetches real Tiingo data for the configured universe, writes Parquet, queryable via DuckDB.

---

## Phase 5: DuckDB Query Layer

- [x]Implement `query.py`:
  - `get_ohlcv(market, start_date, end_date, ticker=None, source_id=None) → DataFrame`: Read from `data/ohlcv/{market}/**/*.parquet` with DuckDB. Filter by date range and optionally by ticker/source_id.
  - `get_universe(market, active_only=True) → DataFrame`: Read instrument metadata.
  - `get_quarantine_log(market, start_date=None, end_date=None) → DataFrame`: Read quarantine files.
- [x]Wire `cli.py` `query` command to `query.py`. Print results to stdout as tabular text.
- [x]`test_query.py`: Write sample Parquet files to tmp dir, verify DuckDB queries return correct results. Test glob patterns spanning multiple years.

### Milestone check: `python -m getstock query --market us --ticker AAPL --start 2025-06-01 --end 2026-03-15` returns data from Parquet.

---

## Phase 6: Backfill & Operations Hardening

### Backfill

- [x]Test `backfill` command end-to-end for KRX: backfill 1 week, verify file structure.
- [x]Test `backfill` command end-to-end for US: backfill 1 week for a small watchlist.
- [x]Add progress logging to backfill: `Processing date 15/252: 2025-09-15...`
- [x]Add `--dry-run` flag to `run` and `backfill`: log what would be fetched without writing.

### Operations

- [x]Add crontab example entries to README (KRX: 07:00 UTC weekdays, US: 21:30 UTC weekdays).
- [x]Document manual backfill procedure (how to run, what to expect, timing estimates).
- [x]Document quarantine inspection: how to query quarantine logs via DuckDB.
- [x]Document data querying: sample DuckDB SQL for common patterns (single ticker history, cross-sectional snapshot, join with metadata).

### Milestone check: Full 1-year backfill runs for KRX. US backfill runs for configured subset. Cron schedule works for 7 consecutive days.

---

## Phase 7: Documentation & Polish

- [x]Write `README.md`: Overview, setup instructions (venv, pip install, .env), usage examples, cron configuration, data directory layout, DuckDB query examples, architecture summary.
- [x]Add `.env.example` with all environment variables documented.
- [x]Review all log messages for clarity and consistency.
- [x]Review error messages for actionability (tell the user what to do, not just what went wrong).
- [x]Verify all public functions have concise docstrings.

---

## Deferred / Not in v1

- [ ] KRX Open API fallback fetcher: Implement `sources/krx_openapi.py` as a contingency if `pykrx` breaks. Would call `POST /svc/apis/sto/stk_bydd_trd` and `/sto/ksq_bydd_trd` with `AUTH_KEY` header. Provides raw OHLCV only (no adjusted prices). Requires API key registration at `openapi.krx.co.kr` and per-service subscription approval.
- [ ] KRX Open API as validation source: Cross-check `pykrx` raw OHLCV against KRX Open API data to detect `pykrx` scraping errors or silent breakage.
- [ ] Fallback data sources (Yahoo Finance, FRED, etc.)
- [ ] Self-calculated adjusted prices for KRX (requires verified corporate action history)
- [ ] Full ticker/name change history tracking (slowly changing dimension)
- [ ] Backfill beyond 1 year
- [ ] Persistent DuckDB database with materialized views
- [ ] Notification/alerting on pipeline failure (email, Slack, webhook)
- [ ] Data quality dashboard or monitoring UI
- [ ] Restatement versioning (tracking provider corrections over time)
- [ ] Additional markets (Japan, Europe, etc.)
- [ ] Fundamental data (earnings, financial statements)
- [ ] Automatic quarantine retry mechanism
- [ ] Async/parallel ingestion for performance optimization
- [ ] Independent dividend/split datasets for US (currently derived from adjusted prices or omitted)
- [ ] Automated periodic re-backfill to refresh historical adjusted prices
- [ ] Pre-built DuckDB views for common backtest queries
