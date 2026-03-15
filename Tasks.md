# Tasks.md

## Phase 1: Repository Setup & Configuration

### Repository Setup

- [ ] Initialize Python project structure:
  ```
  getstock/
  ├── __init__.py
  ├── __main__.py          # CLI entry point
  ├── cli.py               # CLI argument parsing
  ├── config.py            # Config loading
  ├── models.py            # Schema definitions (dataclasses/TypedDict)
  ├── sources/
  │   ├── __init__.py
  │   ├── krx.py           # KRX fetcher
  │   └── tiingo.py        # Tiingo fetcher
  ├── normalize.py         # Source → canonical schema mapping
  ├── validate.py          # Validation rules
  ├── adjust.py            # Adjusted series generation
  ├── storage.py           # Parquet read/write
  ├── quarantine.py        # Quarantine handling
  ├── universe.py          # Universe management & delisting detection
  └── logging_config.py    # Logging setup
  tests/
  ├── __init__.py
  ├── fixtures/
  ├── test_config.py
  ├── test_normalize.py
  ├── test_validate.py
  ├── test_storage.py
  ├── test_sources/
  │   ├── test_krx.py
  │   └── test_tiingo.py
  └── test_integration.py
  config.yaml
  .env.example
  .gitignore
  pyproject.toml
  README.md
  ```
- [ ] Create `pyproject.toml` with dependencies: `pandas`, `pyarrow`, `duckdb`, `pykrx`, `requests`, `python-dotenv`, `pyyaml`, `exchange-calendars`, `click`
- [ ] Create `.gitignore` (include `data/`, `.env`, `__pycache__/`, `*.egg-info/`, `.venv/`)
- [ ] Create `.env.example` with placeholder for `TIINGO_API_KEY`
- [ ] Set up `pytest` in `pyproject.toml`

### Config

- [ ] Implement `config.py`: Load `config.yaml` and `.env`. Validate required keys exist at startup. Fail fast with clear error if `TIINGO_API_KEY` is missing.
- [ ] Create `config.yaml` with market definitions (timezone, close time, run delay, asset types, source) and data directory paths.
- [ ] Implement `logging_config.py`: Configure Python `logging` with format `%(asctime)s | %(levelname)s | %(name)s | %(message)s`. Output to stdout + optional file.

---

## Phase 2: Core Ingestion

### Universe Management

- [ ] Implement `universe.py`: `fetch_universe(market) → DataFrame` that returns the current list of active instruments with columns matching the Instrument Metadata schema.
- [ ] KRX universe: Use `pykrx` to fetch KOSPI + KOSDAQ tickers. Filter to common stocks. Map to canonical instrument metadata schema.
- [ ] US universe: Download Tiingo supported tickers CSV. Filter to `assetType` in `[Stock, ETF]`. Map to canonical schema.
- [ ] Implement delisting detection: Compare fetched universe against stored `instruments_{market}.parquet`. Mark missing instruments as delisted with today's date.
- [ ] Implement metadata overwrite: Update ticker, name, `last_updated` on each run.

### KRX Ingestion (`sources/krx.py`)

- [ ] Implement `fetch_ohlcv_krx(tickers, start_date, end_date) → DataFrame`. Use `pykrx.stock.get_market_ohlcv_by_date()` or per-ticker API. Add 0.5s delay between requests.
- [ ] Implement `fetch_adjusted_krx(tickers, start_date, end_date) → DataFrame`. Use `pykrx` adjusted price functions.
- [ ] Implement `fetch_dividends_krx(tickers, start_date, end_date) → DataFrame`. Use available `pykrx` corporate action APIs.
- [ ] Implement `fetch_splits_krx(tickers, start_date, end_date) → DataFrame`. Use available `pykrx` APIs. Log warning if data is sparse.
- [ ] Handle per-instrument errors: wrap each ticker fetch in try/except, collect failures for quarantine.

### Tiingo Ingestion (`sources/tiingo.py`)

- [ ] Implement `fetch_ohlcv_tiingo(tickers, start_date, end_date, api_key) → DataFrame`. Use Tiingo daily prices endpoint. Returns raw + adjusted fields.
- [ ] Implement rate limiting: Track request count, sleep when approaching 500/hour. Respect `Retry-After` headers on 429 responses.
- [ ] Implement retry logic: 3 retries with exponential backoff (2s, 4s, 8s) on connection errors.
- [ ] Implement `fetch_dividends_tiingo(tickers, start_date, end_date, api_key) → DataFrame`. Use Tiingo fundamentals/metadata endpoint if available on free tier.
- [ ] Implement `fetch_splits_tiingo(tickers, start_date, end_date, api_key) → DataFrame`. Same as dividends; if not directly available, log warning.
- [ ] Handle per-instrument errors: wrap each ticker fetch in try/except, collect failures for quarantine.

---

## Phase 3: Normalization & Adjusted Series

### Normalization (`normalize.py`)

- [ ] Implement `normalize_ohlcv(df, source) → DataFrame`: Map source-specific columns to canonical OHLCV schema. Add `source` and `fetched_at` columns.
- [ ] Implement `normalize_dividends(df, source) → DataFrame`: Map to canonical dividends schema.
- [ ] Implement `normalize_splits(df, source) → DataFrame`: Map to canonical splits schema.
- [ ] Ensure all date columns are `date` type (not datetime). Strip time components.
- [ ] Ensure ticker column uses consistent format per market.

### Adjusted Series (`adjust.py`)

- [ ] Implement `generate_adjusted_ohlcv(raw_df, source) → DataFrame`:
  - US: Copy Tiingo `adj*` fields into canonical `adj_open`, `adj_high`, `adj_low`, `adj_close`, `adj_volume`.
  - KRX: Copy `pykrx` adjusted values into canonical adjusted columns.
- [ ] If adjusted values are missing for an instrument, exclude from adjusted output and log warning.

---

## Phase 4: Validation & Quarantine

### Validation (`validate.py`)

- [ ] Implement validation function `validate_ohlcv(df) → (valid_df, quarantine_df)`:
  - V1: Positive prices (`open > 0`, `high > 0`, `low > 0`, `close > 0`)
  - V2: `high >= low`
  - V3: `high >= open` and `high >= close`
  - V4: `low <= open` and `low <= close`
  - V5: `volume >= 0`
  - V6: Date in expected range (warning only)
  - V7: No duplicate `(ticker, date)` — keep last, warn
  - V8: Price change > 50% from previous close — warning only, keep data
- [ ] Return tuple of `(clean DataFrame, quarantine DataFrame with error details)`.
- [ ] Each quarantined row includes: `ticker`, `date`, `stage=validation`, `error_type`, `error_detail`.

### Quarantine (`quarantine.py`)

- [ ] Implement `write_quarantine(quarantine_df, market, run_date, data_dir)`: Write to `data/meta/quarantine/{YYYY-MM-DD}_{market}.parquet`.
- [ ] Implement `read_quarantine(market, run_date, data_dir) → DataFrame`: Read quarantine for a specific run.
- [ ] Merge quarantine entries from ingestion errors and validation errors before writing.

---

## Phase 5: Storage

### Parquet Storage (`storage.py`)

- [ ] Implement `write_parquet(df, path)`: Write DataFrame to Parquet with `pyarrow`. Create parent directories if needed.
- [ ] Implement `read_parquet(path) → DataFrame`: Read a single Parquet file.
- [ ] Implement `write_daily_ohlcv(df, market, data_type, run_date, data_dir)`: Write to correct path (`data/{raw|adjusted}/{market}/ohlcv/{YYYY}/{YYYY-MM-DD}.parquet`).
- [ ] Implement `write_daily_dividends(df, market, run_date, data_dir)`.
- [ ] Implement `write_daily_splits(df, market, run_date, data_dir)`.
- [ ] Implement `write_universe_snapshot(df, market, run_date, data_dir)`.
- [ ] Implement `write_instrument_metadata(df, market, data_dir)`: Overwrite `data/meta/instruments_{market}.parquet`.
- [ ] Ensure all writes are atomic: write to temp file, then rename (prevents corrupt files on crash).

---

## Phase 6: DuckDB Integration

### DuckDB Query Layer

- [ ] Create `getstock/query.py` with helper functions:
  - `get_adjusted_close(market, ticker, start_date, end_date) → DataFrame`
  - `get_universe(market, active_only=True) → DataFrame`
  - `get_quarantine_log(market, start_date, end_date) → DataFrame`
- [ ] Use `duckdb.query()` with `read_parquet()` and glob patterns.
- [ ] Add a simple CLI subcommand: `python -m getstock query --market us --ticker AAPL --start 2025-06-01 --end 2026-03-15` that prints results to stdout.

---

## Phase 7: CLI & Pipeline Orchestration

### CLI (`cli.py` + `__main__.py`)

- [ ] Implement CLI using `click`:
  - `python -m getstock run --market {krx|us}` — daily incremental run
  - `python -m getstock backfill --market {krx|us} --start YYYY-MM-DD --end YYYY-MM-DD` — historical backfill
  - `python -m getstock query --market {krx|us} [--ticker TICKER] [--start DATE] [--end DATE]` — ad-hoc query
- [ ] `run` command: Determine today's trading date using `exchange_calendars`. If not a trading day, exit 0 with log message.
- [ ] `run` command orchestration:
  1. Load config
  2. Fetch universe → detect delistings → write metadata
  3. Fetch OHLCV (raw) → normalize → validate → quarantine failures → write raw Parquet
  4. Generate adjusted series → write adjusted Parquet
  5. Fetch dividends → normalize → write Parquet
  6. Fetch splits → normalize → write Parquet
  7. Write universe snapshot
  8. Write quarantine log
  9. Log run summary
- [ ] `backfill` command: Iterate over trading dates in range. Call same pipeline per date. Add progress logging.
- [ ] Exit code 0 on success, 1 on failure. Instrument-level quarantine is not a failure.

---

## Phase 8: Tests

### Unit Tests

- [ ] `test_config.py`: Test config loading, missing keys, default values.
- [ ] `test_normalize.py`: Test KRX and Tiingo raw data → canonical schema mapping with sample data.
- [ ] `test_validate.py`: Test each validation rule (V1–V8) with crafted DataFrames. Verify quarantine output.
- [ ] `test_storage.py`: Test Parquet write/read round-trip. Verify file paths and directory creation.
- [ ] `test_sources/test_krx.py`: Test KRX fetcher with mocked `pykrx` calls.
- [ ] `test_sources/test_tiingo.py`: Test Tiingo fetcher with mocked HTTP responses (use `responses` or `pytest-mock`).

### Integration Tests

- [ ] `test_integration.py`: Run full pipeline with mocked API responses for 1 date, 5 tickers. Verify:
  - Raw and adjusted Parquet files exist at correct paths
  - Schema matches canonical definitions
  - DuckDB queries return expected results
  - Quarantine file contains expected failures (inject one bad ticker in fixtures)
- [ ] Test idempotency: Run pipeline twice, verify output files are identical.
- [ ] Test holiday handling: Mock a non-trading day, verify early exit.

### Test Fixtures

- [ ] Create `tests/fixtures/krx_ohlcv_sample.json` with sample KRX response data.
- [ ] Create `tests/fixtures/tiingo_ohlcv_sample.json` with sample Tiingo response data.
- [ ] Create `tests/fixtures/tiingo_universe_sample.csv` with sample supported tickers data.

---

## Phase 9: Documentation & Operations

### Docs

- [ ] Write `README.md`: Setup instructions, usage examples, cron configuration, architecture overview.
- [ ] Add inline docstrings to all public functions.

### Operations

- [ ] Create example crontab entries in `README.md` for KRX (07:00 UTC weekdays) and US (21:30 UTC weekdays).
- [ ] Document manual backfill procedure.
- [ ] Document how to inspect quarantine logs.
- [ ] Document how to query data via DuckDB (sample SQL in README or a `queries/` directory).
- [ ] Add `.env.example` with all required environment variables documented.

---

## Deferred / Not in v1

- [ ] Fallback data sources (e.g., Yahoo Finance, FRED for macro data)
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
- [ ] Pre-built DuckDB views for common backtest queries
