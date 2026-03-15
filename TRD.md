# TRD.md

## System Overview

Getstock is a Python-based daily ETL pipeline that ingests end-of-day equity data from KRX and Tiingo, normalizes it into a canonical schema, and writes Parquet files queryable via DuckDB. The system runs as a CLI tool invoked by cron, one invocation per market per day.

```
┌─────────────┐    ┌─────────────┐
│  KRX Source  │    │   Tiingo    │
└──────┬──────┘    └──────┬──────┘
       │                  │
       ▼                  ▼
┌─────────────────────────────────┐
│         Ingestion Layer         │
│  (market-specific fetchers)     │
└──────────────┬──────────────────┘
               │ raw DataFrames
               ▼
┌─────────────────────────────────┐
│       Normalization Layer       │
│  (canonical schema mapping)     │
└──────────────┬──────────────────┘
               │ normalized DataFrames
               ▼
┌─────────────────────────────────┐
│        Validation Layer         │
│  (sanity checks, quarantine)    │
└──────────────┬──────────────────┘
               │ validated DataFrames
               ▼
┌─────────────────────────────────┐
│     Adjusted Series Layer       │
│  (raw passthrough + adjusted)   │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│         Storage Layer           │
│  (Parquet writer, partitioned)  │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│         DuckDB (query)          │
│  (reads Parquet files directly) │
└─────────────────────────────────┘
```

## Architecture Principles

1. **Simplicity over generality.** No plugin systems, no abstract factory patterns. Each market has one concrete fetcher module.
2. **Idempotent writes.** Every run can be re-executed safely. Overwrites are the norm.
3. **Fail per instrument, not per batch.** A single bad ticker must not abort the entire market's run.
4. **Raw data is sacred.** Raw source data is always preserved. Adjusted data is derived separately.
5. **Flat file storage.** Parquet files on local disk. No database server.
6. **DuckDB is read-only.** DuckDB is used only as a query engine over Parquet. It does not own the data.
7. **Configuration over code.** Market schedules, API keys, file paths—all in config/env, not hardcoded.

## Data Flow: Source to Serving

### Step-by-step per daily run

1. **Load config**: Read `.env` for API keys, `config.yaml` for market settings and paths.
2. **Determine run date**: Default to the most recent trading day for the target market. Override via CLI argument for backfill.
3. **Fetch universe**: Get current list of active instruments for the market.
4. **Ingest OHLCV**: Fetch daily OHLCV for each instrument (or batch) for the target date(s).
5. **Ingest corporate actions**: Fetch dividends and splits for the target date range.
6. **Ingest metadata**: Fetch delisting status and trading halt information.
7. **Normalize**: Map source-specific fields to canonical schema.
8. **Validate**: Apply sanity checks. Quarantine failing instruments.
9. **Generate adjusted series**: Produce adjusted OHLCV using source-provided adjusted values.
10. **Write Parquet**: Write raw and adjusted data to partitioned Parquet files.
11. **Update universe metadata**: Write updated instrument metadata (active/delisted status, current ticker/name).
12. **Log summary**: Log counts, warnings, quarantined instruments, and timing.

## Source-Specific Ingestion Notes

### KRX

- **Library**: Use `pykrx` (Python library for KRX data). If `pykrx` is insufficient, fall back to direct KRX file downloads.
- **Universe**: Fetch KOSPI + KOSDAQ listed common stocks. Filter out preferred shares, REITs, and special-purpose vehicles by stock type code.
- **OHLCV**: `pykrx` provides daily OHLCV per ticker and date range.
- **Adjusted prices**: `pykrx` provides adjusted prices; use these directly. Do not self-calculate.
- **Dividends/Splits**: `pykrx` provides some corporate action data. If granularity is insufficient, log a warning and store what is available.
- **Delisting**: Compare today's universe against previous day's. Instruments that disappear are marked as delisted with the detection date.
- **Trading halts**: `pykrx` may expose halt status via volume=0 + unchanged price. Heuristic-based in v1; flag as `halt_detection=heuristic` in metadata.
- **Rate limits**: `pykrx` scrapes KRX; add 0.5–1s delay between requests to avoid throttling.
- **Market close**: KRX closes at 15:30 KST. Cron runs at 16:00 KST.
- **Timezone**: All KRX dates are in `Asia/Seoul`. Store as date only (no time component) in canonical schema.

### Tiingo (US)

- **API**: REST API with free tier. End-of-day endpoint: `https://api.tiingo.com/tiingo/daily/<ticker>/prices`.
- **Auth**: API key in `Authorization` header. Stored in `.env` as `TIINGO_API_KEY`.
- **Universe**: Tiingo provides a supported tickers CSV (`https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip`). Filter to `assetType` in `[Stock, ETF]` and `exchange` in US exchanges.
- **OHLCV**: End-of-day endpoint returns OHLCV + `adjOpen`, `adjHigh`, `adjLow`, `adjClose`, `adjVolume`.
- **Adjusted prices**: Use Tiingo's `adjClose` as the default backtest close. Store all `adj*` fields.
- **Dividends/Splits**: Available via Tiingo's metadata or fundamentals endpoints. If not available on free tier, derive from raw vs adjusted price ratios. Document the approach used.
- **Delisting**: Instruments that disappear from the supported tickers list are marked as delisted.
- **Trading halts**: If Tiingo returns no data for a date where the market was open, flag as potential halt. Heuristic-based.
- **Rate limits**: Free tier allows ~500 unique symbols/hour for daily data. Use the batch endpoint where available. Implement rate limiting with exponential backoff.
- **Market close**: NYSE/NASDAQ close at 16:00 ET. Cron runs at 16:30 ET.
- **Timezone**: All US dates stored as date only. Market calendar uses `exchange_calendars` library (NYSE calendar).

## Storage Design

### Base Directory Structure

```
data/
├── raw/
│   ├── krx/
│   │   ├── ohlcv/
│   │   │   └── {YYYY}/
│   │   │       └── {YYYY-MM-DD}.parquet
│   │   ├── dividends/
│   │   │   └── {YYYY}/
│   │   │       └── {YYYY-MM-DD}.parquet
│   │   ├── splits/
│   │   │   └── {YYYY}/
│   │   │       └── {YYYY-MM-DD}.parquet
│   │   └── universe/
│   │       └── {YYYY-MM-DD}.parquet
│   └── us/
│       ├── ohlcv/
│       │   └── {YYYY}/
│       │       └── {YYYY-MM-DD}.parquet
│       ├── dividends/
│       │   └── {YYYY}/
│       │       └── {YYYY-MM-DD}.parquet
│       ├── splits/
│       │   └── {YYYY}/
│       │       └── {YYYY-MM-DD}.parquet
│       └── universe/
│           └── {YYYY-MM-DD}.parquet
├── adjusted/
│   ├── krx/
│   │   └── ohlcv/
│   │       └── {YYYY}/
│   │           └── {YYYY-MM-DD}.parquet
│   └── us/
│       └── ohlcv/
│           └── {YYYY}/
│               └── {YYYY-MM-DD}.parquet
├── meta/
│   ├── instruments_krx.parquet
│   ├── instruments_us.parquet
│   └── quarantine/
│       └── {YYYY-MM-DD}_{market}.parquet
└── logs/
    └── {YYYY-MM-DD}_{market}.log
```

### Partitioning / File Layout

- **Partition by date**: One Parquet file per trading day per market per data type. This makes daily overwrites trivial (replace one file) and keeps file sizes manageable.
- **Year subdirectory**: Groups files by year to avoid a single directory with hundreds of files.
- **File naming**: `{YYYY-MM-DD}.parquet` — simple, sortable, unambiguous.
- **Instrument metadata**: One file per market, overwritten on each run. Contains current state of all known instruments.
- **Quarantine files**: One file per failed run date + market. Contains instrument-level failure details.

### Why date-partitioned, not ticker-partitioned

- Daily overwrites affect one date at a time → replace one small file.
- Backtest queries typically scan date ranges across all instruments → date-partitioned files align with read pattern.
- Ticker-partitioned would require rewriting per-ticker files on every run.

## DuckDB Usage Model

- **Role**: Read-only query engine. DuckDB reads Parquet files directly using `read_parquet()` with glob patterns.
- **No persistent database file in v1.** All queries go directly to Parquet.
- **Example queries**:

```sql
-- Get adjusted close for a single ticker
SELECT date, adj_close
FROM read_parquet('data/adjusted/us/ohlcv/2025/*.parquet')
WHERE ticker = 'AAPL'
ORDER BY date;

-- Get all adjusted close prices for a date range
SELECT ticker, date, adj_close
FROM read_parquet('data/adjusted/us/ohlcv/2025/*.parquet')
WHERE date BETWEEN '2025-01-01' AND '2025-06-30'
ORDER BY ticker, date;

-- Universe snapshot
SELECT * FROM read_parquet('data/meta/instruments_us.parquet')
WHERE is_active = true;
```

- **Future**: May add a persistent DuckDB database with views or materialized tables if query performance on raw Parquet becomes insufficient. Not needed for v1 data volumes (~1 year, two markets).

## Canonical Schema Design

### OHLCV (raw)

| Column | Type | Description |
|---|---|---|
| `ticker` | `VARCHAR` | Current ticker symbol. Overwritten to latest on each run. |
| `date` | `DATE` | Trading date (local market date, no time). |
| `open` | `DOUBLE` | Raw open price. |
| `high` | `DOUBLE` | Raw high price. |
| `low` | `DOUBLE` | Raw low price. |
| `close` | `DOUBLE` | Raw close price. |
| `volume` | `BIGINT` | Trading volume in shares. |
| `source` | `VARCHAR` | Data source identifier (`krx`, `tiingo`). |
| `fetched_at` | `TIMESTAMP` | UTC timestamp when data was fetched. |

### OHLCV (adjusted)

Same as raw, plus:

| Column | Type | Description |
|---|---|---|
| `adj_open` | `DOUBLE` | Adjusted open price. |
| `adj_high` | `DOUBLE` | Adjusted high price. |
| `adj_low` | `DOUBLE` | Adjusted low price. |
| `adj_close` | `DOUBLE` | Adjusted close price. Default backtest series. |
| `adj_volume` | `BIGINT` | Adjusted volume (if available, else same as raw). |

### Dividends

| Column | Type | Description |
|---|---|---|
| `ticker` | `VARCHAR` | Current ticker symbol. |
| `ex_date` | `DATE` | Ex-dividend date. |
| `amount` | `DOUBLE` | Dividend amount per share (local currency). |
| `currency` | `VARCHAR` | Currency code (`KRW`, `USD`). |
| `source` | `VARCHAR` | Data source identifier. |
| `fetched_at` | `TIMESTAMP` | UTC timestamp when data was fetched. |

### Splits

| Column | Type | Description |
|---|---|---|
| `ticker` | `VARCHAR` | Current ticker symbol. |
| `date` | `DATE` | Split effective date. |
| `ratio_from` | `DOUBLE` | Original shares (e.g., 1 in a 1:4 split). |
| `ratio_to` | `DOUBLE` | New shares (e.g., 4 in a 1:4 split). |
| `source` | `VARCHAR` | Data source identifier. |
| `fetched_at` | `TIMESTAMP` | UTC timestamp when data was fetched. |

### Instrument Metadata

| Column | Type | Description |
|---|---|---|
| `ticker` | `VARCHAR` | Current ticker symbol. |
| `name` | `VARCHAR` | Current instrument name. |
| `market` | `VARCHAR` | Market identifier (`krx`, `us`). |
| `asset_type` | `VARCHAR` | `stock` or `etf`. |
| `exchange` | `VARCHAR` | Exchange code (e.g., `KOSPI`, `KOSDAQ`, `NYSE`, `NASDAQ`). |
| `is_active` | `BOOLEAN` | `true` if currently listed and trading. |
| `delisted_date` | `DATE` | Date delisting was detected (null if active). |
| `first_seen` | `DATE` | Date instrument first appeared in universe. |
| `last_updated` | `DATE` | Date metadata was last refreshed. |

### Quarantine Log

| Column | Type | Description |
|---|---|---|
| `ticker` | `VARCHAR` | Instrument ticker. |
| `market` | `VARCHAR` | Market identifier. |
| `date` | `DATE` | Run date. |
| `stage` | `VARCHAR` | Pipeline stage where failure occurred (`ingestion`, `validation`, `storage`). |
| `error_type` | `VARCHAR` | Error category (`missing_data`, `validation_failed`, `api_error`). |
| `error_detail` | `VARCHAR` | Error message or details. |
| `created_at` | `TIMESTAMP` | UTC timestamp. |

## Required Tables / Datasets

| Dataset | Location | Updated |
|---|---|---|
| Raw OHLCV (KRX) | `data/raw/krx/ohlcv/` | Daily |
| Raw OHLCV (US) | `data/raw/us/ohlcv/` | Daily |
| Adjusted OHLCV (KRX) | `data/adjusted/krx/ohlcv/` | Daily |
| Adjusted OHLCV (US) | `data/adjusted/us/ohlcv/` | Daily |
| Dividends (KRX) | `data/raw/krx/dividends/` | Daily |
| Dividends (US) | `data/raw/us/dividends/` | Daily |
| Splits (KRX) | `data/raw/krx/splits/` | Daily |
| Splits (US) | `data/raw/us/splits/` | Daily |
| Universe snapshot (KRX) | `data/raw/krx/universe/` | Daily |
| Universe snapshot (US) | `data/raw/us/universe/` | Daily |
| Instrument metadata (KRX) | `data/meta/instruments_krx.parquet` | Daily (overwrite) |
| Instrument metadata (US) | `data/meta/instruments_us.parquet` | Daily (overwrite) |
| Quarantine log | `data/meta/quarantine/` | Per failed run |

## Raw vs Adjusted Policy

| Market | Raw Data | Adjusted Data | Default Backtest Series |
|---|---|---|---|
| US | Stored as-is from Tiingo | Tiingo `adj*` fields | `adj_close` (dividend-adjusted) |
| KRX | Stored as-is from `pykrx` | Provider-adjusted values from `pykrx` | `adj_close` from provider |

- Raw and adjusted are stored in separate directory trees.
- If a source does not provide adjusted values for an instrument, the adjusted file omits that instrument and a warning is logged.
- Adjusted series are never self-calculated in v1.

## Delisting / Halt Handling Policy

### Delisting

- **Detection**: Compare current universe fetch against stored instrument metadata. Instruments absent from the current universe that were previously active are candidates for delisting.
- **Marking**: Set `is_active = false` and `delisted_date = today` in instrument metadata.
- **Data retention**: All historical data for delisted instruments remains in raw and adjusted Parquet files.
- **Serving**: Default queries filter on `is_active = true`. Backtesting engine may explicitly include delisted instruments for survivorship-bias-free analysis.
- **No re-listing logic in v1**: If an instrument reappears after being marked delisted, set `is_active = true` and clear `delisted_date`. Log a warning.

### Trading Halts

- **Detection**: Heuristic-based. If a market was open but an instrument has no data, or volume = 0 with unchanged price, flag as potential halt.
- **Storage**: Halt status is not a separate dataset in v1. Instead, absence of data for an active instrument on a trading day implies a potential halt.
- **Future**: Add explicit halt status field to OHLCV if sources provide it.

## Validation Rules

Applied per instrument per date, after normalization:

| Rule | Check | Severity |
|---|---|---|
| V1: Positive prices | `open > 0`, `high > 0`, `low > 0`, `close > 0` | Quarantine instrument-date |
| V2: High >= Low | `high >= low` | Quarantine instrument-date |
| V3: High >= Open, Close | `high >= open`, `high >= close` | Quarantine instrument-date |
| V4: Low <= Open, Close | `low <= open`, `low <= close` | Quarantine instrument-date |
| V5: Non-negative volume | `volume >= 0` | Quarantine instrument-date |
| V6: Date in expected range | Date matches the target fetch date | Warning, log |
| V7: No duplicate ticker-date | Unique constraint on `(ticker, date)` | Keep last, warn |
| V8: Price within 50% of previous close | `abs(close / prev_close - 1) < 0.50` | Warning only (legitimate for halts, IPOs, etc.) |

- Validation failures at severity "quarantine" remove the instrument-date from the output and write to the quarantine log.
- Validation failures at severity "warning" log the issue but keep the data.

## Error Handling

| Error Type | Behavior |
|---|---|
| API connection failure | Retry 3 times with exponential backoff (2s, 4s, 8s). If all retries fail, abort the market run and exit with non-zero code. |
| API rate limit (429) | Wait for `Retry-After` header duration, then retry. Max 3 retries. |
| Single instrument fetch failure | Log error, quarantine the instrument for that date, continue with remaining instruments. |
| Validation failure (instrument-level) | Quarantine the instrument-date, continue batch. |
| Parquet write failure | Critical. Abort the market run. Exit non-zero. |
| Config/env missing | Fail fast at startup. Print missing keys and exit. |

## Quarantine Policy

- Quarantined instrument-dates are written to `data/meta/quarantine/{YYYY-MM-DD}_{market}.parquet`.
- Quarantined data is excluded from both raw and adjusted output files.
- Quarantine is informational: it records what failed and why, for later investigation.
- No automatic retry of quarantined instruments. Manual re-run of the date will re-attempt.
- Quarantine files accumulate (not overwritten across dates). A cleanup utility may be added later.

## Idempotency and Overwrite Policy

- **OHLCV files**: One file per date. Re-running a date overwrites the file completely. This is the idempotency mechanism.
- **Instrument metadata**: Overwritten in full on every run. Represents current state only.
- **Universe snapshots**: One file per date. Overwritten on re-run.
- **Quarantine**: Overwritten per date + market on re-run.
- **No append mode**: All writes are full-file overwrites. This avoids duplicate row issues and simplifies the write path.
- **Backfill**: Running backfill on already-populated dates overwrites existing files. This is intentional—always trust the latest provider data.

## Scheduling Model

```
# crontab entries (server timezone matters; use system UTC and convert)

# KRX: runs at 16:00 KST = 07:00 UTC (standard time)
0 7 * * 1-5  cd /path/to/getstock && python -m getstock run --market krx >> data/logs/cron_krx.log 2>&1

# US: runs at 16:30 ET = 21:30 UTC (standard time) / 20:30 UTC (daylight time)
30 21 * * 1-5  cd /path/to/getstock && python -m getstock run --market us >> data/logs/cron_us.log 2>&1
```

- Each cron entry is a single CLI invocation.
- Exit code 0 = success. Non-zero = failure (logged in cron output).
- The CLI determines the correct trading date based on the market calendar. If today is not a trading day (weekend, holiday), the run exits early with code 0 and a log message.
- Backfill is a separate CLI command: `python -m getstock backfill --market krx --start 2025-03-15 --end 2026-03-15`.

## Configuration / Secrets Handling

### `.env` file

```
TIINGO_API_KEY=your_api_key_here
```

- Loaded via `python-dotenv` at startup.
- `.env` is in `.gitignore`.

### `config.yaml`

```yaml
data_dir: ./data

markets:
  krx:
    timezone: Asia/Seoul
    close_time: "15:30"
    run_delay_minutes: 30
    asset_types: [stock]
    source: krx
  us:
    timezone: US/Eastern
    close_time: "16:00"
    run_delay_minutes: 30
    asset_types: [stock, etf]
    source: tiingo

backfill:
  lookback_days: 365

validation:
  price_change_warn_threshold: 0.50

logging:
  level: INFO
  file_enabled: true
```

- Config is loaded once at startup.
- Paths in config are relative to project root.

## Logging / Observability

- **Library**: Python `logging` module. No external dependencies.
- **Format**: `%(asctime)s | %(levelname)s | %(name)s | %(message)s`
- **Outputs**: stdout (always) + file (if configured). File goes to `data/logs/`.
- **Log levels**:
  - `INFO`: Run start/end, instrument counts, file writes.
  - `WARNING`: Missing data, quarantined instruments, heuristic-based detections.
  - `ERROR`: API failures, critical write failures.
- **Run summary**: At end of each run, log a structured summary:
  ```
  RUN SUMMARY | market=us | date=2026-03-15 | instruments=4500 | fetched=4485 | quarantined=15 | duration=42m
  ```
- **No external monitoring in v1.** Rely on cron output and log files. Future: add email/webhook on non-zero exit.

## Testing Strategy

### Unit Tests

- **Schema validation**: Verify normalized DataFrames match canonical schema.
- **Validation rules**: Test each validation rule with known good and bad data.
- **Normalization**: Test source-to-canonical field mapping for each market.
- **Quarantine logic**: Verify failed instruments are correctly quarantined and excluded.

### Integration Tests

- **Mock API tests**: Use recorded API responses (fixtures) to test full pipeline without network.
- **Parquet round-trip**: Write and read back Parquet files; verify schema and data integrity.
- **DuckDB query tests**: Verify expected queries return correct results against test Parquet files.
- **Idempotency tests**: Run pipeline twice on same date; verify output is identical.

### Manual / Smoke Tests

- **Single-ticker test**: Run pipeline for one ticker, one date, inspect output.
- **Backfill test**: Backfill 1 week for a small subset; verify file structure and data.
- **Holiday handling**: Run on a known market holiday; verify early exit.

### Test Tooling

- `pytest` for test runner.
- `pytest-mock` or `responses` for HTTP mocking.
- Test fixtures stored in `tests/fixtures/`.

## Explicit Trade-offs and Rationale

| Trade-off | Chosen approach | Alternative considered | Why |
|---|---|---|---|
| Date-partitioned vs ticker-partitioned Parquet | Date-partitioned | Ticker-partitioned | Daily overwrites affect one file. Cross-sectional queries (all tickers for a date) are the common read pattern for rebalancing. |
| Overwrite vs append | Overwrite per date | Append with dedup | Simpler write path. No duplicate row risk. Idempotent by construction. |
| Provider-adjusted vs self-calculated (KRX) | Provider-adjusted | Self-calculate from splits/dividends | Self-calculation requires verified corporate action history. Provider values are good enough for v1. |
| `pykrx` vs direct KRX scraping | `pykrx` | Custom scraper | `pykrx` is maintained, covers the needed data, and handles KRX's interface. Custom scraping is fragile. |
| DuckDB direct-on-Parquet vs persistent DB | Direct on Parquet | Persistent DuckDB file | One year of data is small enough. No need for materialized indexes. Avoids sync issues between Parquet source-of-truth and DB copy. |
| Cron vs dedicated scheduler (APScheduler, etc.) | Cron | APScheduler, Celery | Zero additional dependencies. Single-server, single-maintainer. Cron is battle-tested. |
| Single process vs async/parallel | Single process, sequential | asyncio / multiprocessing | Simplicity. Daily runs are not latency-sensitive. Rate limits make parallelism less useful. |
| No persistent state DB | Flat files + Parquet metadata | SQLite for run state | One less dependency. Run state is implicit in file existence. Quarantine log covers failure tracking. |
| Instrument-level quarantine vs batch abort | Instrument-level quarantine | Fail entire batch | Maximizes data availability. One bad ticker should not block 4,000+ others. |
| Overwrite ticker/name vs history tracking | Overwrite to current | Slowly changing dimension table | Ticker history is complex (mergers, symbol changes). Overwrite is sufficient for v1 backtesting needs. |
