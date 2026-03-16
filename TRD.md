# TRD.md

## System Overview

Getstock is a Python-based daily ETL pipeline that ingests end-of-day equity data from KRX (via `pykrx`) and Tiingo, normalizes it into a canonical schema, and writes Parquet files queryable via DuckDB. The system runs as a CLI tool invoked by cron, one invocation per market per day.

```
┌─────────────┐    ┌─────────────┐
│  KRX (pykrx)│    │   Tiingo    │
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
4. **Stable identifiers.** `source_id` (not `ticker`) is the primary key for joining across datasets. Tickers change; source IDs do not.
5. **Single OHLCV dataset.** Raw and adjusted prices live in the same file. No duplicate directory trees.
6. **Flat file storage.** Parquet files on local disk. No database server.
7. **DuckDB is read-only.** DuckDB is used only as a query engine over Parquet. It does not own the data.
8. **Configuration over code.** Market schedules, API keys, file paths—all in config/env, not hardcoded.

## Data Flow: Source to Serving

### Step-by-step per daily run

1. **Load config**: Read `.env` for API keys, `config.yaml` for market settings and paths.
2. **Determine run date**: Default to the most recent trading day for the target market (using `exchange_calendars`). Override via CLI argument for backfill.
3. **Fetch universe**: Get current list of active instruments for the market. Apply configurable universe filter (US only).
4. **Detect delistings**: Compare fetched universe against stored instrument metadata. Apply safety threshold (skip if >20% disappeared). Update metadata.
5. **Ingest OHLCV**: KRX: bulk per-date call. US: per-ticker with rate limiting. Both return raw + adjusted prices.
6. **Normalize**: Map source-specific fields to canonical schema. Assign `source_id`, map `ticker` to current.
7. **Validate**: Apply sanity checks. Split into valid and quarantine sets.
8. **Write OHLCV Parquet**: Write single file per market per date with raw + adjusted columns.
9. **Ingest corporate actions**: Fetch dividends and splits for the target date range.
10. **Write corporate action Parquet**: Dividends and splits to their respective paths.
11. **Write universe snapshot**: Record today's universe fetch for auditing.
12. **Write quarantine log**: Persist all quarantine entries (ingestion + validation failures).
13. **Log summary**: Log counts, warnings, quarantined instruments, and timing.

## Source-Specific Ingestion Notes

### KRX

- **Library**: `pykrx` — a maintained Python library that scrapes KRX data. Preferred over custom scraping.
- **Universe**: Use `pykrx.stock.get_market_ticker_list(date, market="ALL")` to get all listed tickers. Call for both KOSPI and KOSDAQ. Filter to common stocks by checking `get_market_ticker_name()` and stock type. `pykrx` stock codes are 6-digit strings (e.g., `"005930"` for Samsung Electronics). These serve as `source_id`.
- **OHLCV (bulk per-date)**: Use `pykrx.stock.get_market_ohlcv(date, market="ALL")` to fetch all tickers for a single date in one call. This returns open, high, low, close, volume for all listed instruments. This is the primary ingestion method — one HTTP request per date, not per ticker.
- **OHLCV (per-ticker, for backfill)**: Use `pykrx.stock.get_market_ohlcv_by_date(fromdate, todate, ticker)` when fetching a date range for a single ticker. For backfill, prefer iterating over dates with the bulk API instead.
- **Adjusted prices**: Use `pykrx.stock.get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True)` for adjusted prices. Note: the bulk per-date API does not support an `adjusted` parameter, so adjusted prices require per-ticker calls or a separate bulk function. **v1 approach**: For daily runs, fetch raw via bulk API. For adjusted prices, check if `pykrx` provides an adjusted bulk API; if not, use raw values and set `adj_*` columns equal to raw (since KRX does not have frequent dividends that would cause significant divergence within a single day's fetch). For backfill, use per-ticker adjusted calls. **Document clearly in code which path is used.**
- **Dividends/Splits**: `pykrx` has limited corporate action APIs. Use `pykrx.stock.get_market_cap_by_date()` and related functions to detect share count changes (proxy for splits). For dividends, data may be sparse. Store what is available; log warnings for missing data. This is a best-effort dataset in v1.
- **Delisting**: Compare today's universe (from `get_market_ticker_list`) against stored `instruments_krx.parquet`. Instruments absent from today's list that were previously active are delisting candidates, subject to the >20% safety threshold.
- **Trading halts**: Heuristic: volume=0 on a trading day for an active instrument. Not stored as a separate dataset; inferred from OHLCV data.
- **Rate limits**: The bulk per-date API is one request per call, so rate limits are not a concern for daily runs. For backfill (365 dates × 1 call each), add 1s delay between calls to be polite. For per-ticker calls (adjusted prices during backfill), add 0.5s delay.
- **Market close**: KRX closes at 15:30 KST. Cron runs at 16:00 KST.
- **Timezone**: All KRX dates are `Asia/Seoul` local dates. Stored as `DATE` type (no time component).
- **Market calendar**: Use `exchange_calendars` with exchange code `XKRX`.

### Tiingo (US)

- **API**: REST API, free tier. Base URL: `https://api.tiingo.com`.
- **Auth**: `Authorization: Token <api_key>` header. Key stored in `.env` as `TIINGO_API_KEY`.
- **Universe**: Download supported tickers file from `https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip`. This is a CSV with columns including `ticker`, `exchange`, `assetType`, `priceCurrency`, `startDate`, `endDate`. Filter to: `assetType` in `["Stock", "ETF"]`, `priceCurrency == "USD"`, `endDate` is null or in the future (active instruments). The `ticker` field from this file serves as `source_id` for Tiingo (Tiingo tickers are stable across renames — Tiingo maps old tickers to new ones internally). **Note**: If Tiingo's free tier limits daily requests, apply the configurable universe filter at this stage.
- **OHLCV**: Endpoint: `GET /tiingo/daily/<ticker>/prices?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD`. Returns JSON array with fields: `date`, `close`, `high`, `low`, `open`, `volume`, `adjClose`, `adjHigh`, `adjLow`, `adjOpen`, `adjVolume`. Each ticker requires a separate HTTP request. **There is no batch/multi-ticker endpoint for EOD prices on the free tier.**
- **Adjusted prices**: Tiingo's `adj*` fields are dividend-adjusted (and split-adjusted). Use `adjClose` as the default backtest series. Store all `adj*` fields alongside raw prices in the same OHLCV row.
- **Dividends**: Not directly available as a separate endpoint on the free tier. In v1, derive dividend events by detecting changes between `close` and `adjClose` ratios across consecutive days, or omit and rely on adjusted prices for backtesting. Log what approach is used.
- **Splits**: Same as dividends — derive from `adjVolume` vs `volume` ratio changes, or omit in v1. Not critical since adjusted prices already account for splits.
- **Delisting**: Instruments whose `endDate` in the supported tickers CSV is in the past are delisted. Compare against stored metadata. Apply >20% safety threshold.
- **Trading halts**: If Tiingo returns no data for a ticker on a date where the market was open, flag as potential halt in logs. Not stored as a separate dataset.
- **Rate limits**: Free tier limits vary; monitor `X-RateLimit-Remaining` and `X-RateLimit-Limit` response headers. Implement adaptive rate limiting: start at 5 req/sec, back off if rate limit headers indicate throttling. On HTTP 429, wait for `Retry-After` header duration (or 60s default) and retry. For ~500 instruments, expect ~2–5 minutes. For full US universe (~8,000), expect multiple hours.
- **Market close**: NYSE/NASDAQ close at 16:00 ET. Cron runs at 16:30 ET.
- **Timezone**: All US dates stored as `DATE` type (no time component). Market calendar: `exchange_calendars` with `XNYS`.
- **Universe filter**: Configurable in `config.yaml`. Options: `all` (every supported ticker), `watchlist` (explicit list in config), or a path to a CSV file of tickers. Default: `all`, but document that free-tier users should start with a subset.

## Storage Design

### Base Directory Structure

```
data/
├── ohlcv/
│   ├── krx/
│   │   └── {YYYY}/
│   │       └── {YYYY-MM-DD}.parquet
│   └── us/
│       └── {YYYY}/
│           └── {YYYY-MM-DD}.parquet
├── dividends/
│   ├── krx/
│   │   └── {YYYY}/
│   │       └── {YYYY-MM-DD}.parquet
│   └── us/
│       └── {YYYY}/
│           └── {YYYY-MM-DD}.parquet
├── splits/
│   ├── krx/
│   │   └── {YYYY}/
│   │       └── {YYYY-MM-DD}.parquet
│   └── us/
│       └── {YYYY}/
│           └── {YYYY-MM-DD}.parquet
├── universe/
│   ├── krx/
│   │   └── {YYYY-MM-DD}.parquet
│   └── us/
│       └── {YYYY-MM-DD}.parquet
├── meta/
│   ├── instruments_krx.parquet
│   ├── instruments_us.parquet
│   └── quarantine/
│       └── {YYYY-MM-DD}_{market}.parquet
└── logs/
    └── {YYYY-MM-DD}_{market}.log
```

### Partitioning / File Layout

- **Partition by date**: One Parquet file per trading day per market per data type. Daily overwrites replace one file. File sizes are manageable (~2,500 rows for KRX, ~500–8,000 for US depending on filter).
- **Year subdirectory**: Groups files by year to avoid hundreds of files in one directory.
- **File naming**: `{YYYY-MM-DD}.parquet` — simple, sortable, unambiguous.
- **Row ordering within file**: Sort rows by `source_id` within each Parquet file. This enables efficient predicate pushdown when DuckDB filters on `source_id` or `ticker`.
- **Instrument metadata**: One file per market, overwritten on each run. Contains current state of all known instruments (active + delisted).
- **Universe snapshots**: One file per date per market. Records what the source reported as active that day, for auditing delisting detection.
- **Quarantine files**: One file per run date + market. Overwritten on re-run of the same date.

### Why date-partitioned, not ticker-partitioned

- Daily overwrites affect one file → replace one small file (atomic via temp+rename).
- Cross-sectional queries (all tickers for a date range) are the common read pattern for rebalancing.
- Ticker-partitioned would require rewriting per-ticker files on every run.
- For single-ticker time series queries, DuckDB predicate pushdown on sorted `source_id` is efficient enough for v1 data volumes.

### Why single OHLCV file (not separate raw/adjusted)

- The previous design duplicated all raw columns in both `data/raw/` and `data/adjusted/` directory trees.
- Most queries need adjusted close alongside raw close. Separate trees require a join.
- A single file with `open, high, low, close, volume, adj_open, adj_high, adj_low, adj_close, adj_volume` satisfies both raw-data-preservation and backtest-ready requirements.
- If adjusted values are unavailable for an instrument, `adj_*` columns are set to null (not omitted from the file). This preserves the raw data for that instrument.

## DuckDB Usage Model

- **Role**: Read-only query engine. DuckDB reads Parquet files directly using `read_parquet()` with glob patterns.
- **No persistent database file in v1.** All queries go directly to Parquet.
- **Example queries**:

```sql
-- Get adjusted close for a single ticker (all dates, all years)
SELECT date, adj_close
FROM read_parquet('data/ohlcv/us/**/*.parquet')
WHERE ticker = 'AAPL'
ORDER BY date;

-- Get all adjusted close prices for a date range
SELECT source_id, ticker, date, adj_close
FROM read_parquet('data/ohlcv/us/**/*.parquet')
WHERE date BETWEEN '2025-06-01' AND '2026-03-15'
ORDER BY source_id, date;

-- Cross-sectional: all adjusted closes for a single date
SELECT source_id, ticker, adj_close
FROM read_parquet('data/ohlcv/us/2026/2026-03-14.parquet');

-- Active universe
SELECT * FROM read_parquet('data/meta/instruments_us.parquet')
WHERE is_active = true;

-- Quarantine log for a market
SELECT * FROM read_parquet('data/meta/quarantine/*_us.parquet')
ORDER BY date DESC;

-- Join OHLCV with instrument metadata
SELECT o.date, o.ticker, o.adj_close, i.name, i.exchange
FROM read_parquet('data/ohlcv/us/**/*.parquet') o
JOIN read_parquet('data/meta/instruments_us.parquet') i
  ON o.source_id = i.source_id
WHERE i.is_active = true AND o.date >= '2026-01-01'
ORDER BY o.ticker, o.date;
```

- **Glob pattern `**/*.parquet`** spans all year subdirectories. This is the standard query pattern.
- **Future**: May add a persistent DuckDB database with views if query performance degrades. Not needed for v1 data volumes (~365 files per market).

## Canonical Schema Design

### OHLCV

One file per market per date. Contains both raw and adjusted prices.

| Column | Type | Description |
|---|---|---|
| `source_id` | `VARCHAR` | Stable source-native identifier. KRX: 6-digit stock code (e.g., `"005930"`). US: Tiingo ticker (stable across renames). Primary key component. |
| `ticker` | `VARCHAR` | Current human-readable ticker symbol. Updated to latest on each run. |
| `date` | `DATE` | Trading date (local market date, no time component). |
| `open` | `DOUBLE` | Raw open price in local currency. |
| `high` | `DOUBLE` | Raw high price. |
| `low` | `DOUBLE` | Raw low price. |
| `close` | `DOUBLE` | Raw close price. |
| `volume` | `BIGINT` | Raw trading volume in shares. |
| `adj_open` | `DOUBLE` | Adjusted open. Null if source does not provide. |
| `adj_high` | `DOUBLE` | Adjusted high. Null if source does not provide. |
| `adj_low` | `DOUBLE` | Adjusted low. Null if source does not provide. |
| `adj_close` | `DOUBLE` | Adjusted close. Default backtest series. Null if unavailable. |
| `adj_volume` | `BIGINT` | Adjusted volume. Null if source does not provide. |
| `market` | `VARCHAR` | Market identifier (`krx` or `us`). Enables cross-market queries on combined datasets. |
| `source` | `VARCHAR` | Data source identifier (`pykrx`, `tiingo`). |
| `fetched_at` | `TIMESTAMP` | UTC timestamp when data was fetched. |

**Unique constraint**: `(source_id, date)` per file. Enforced during validation (V7).

**Sort order**: Rows sorted by `source_id` within each file.

### Dividends

| Column | Type | Description |
|---|---|---|
| `source_id` | `VARCHAR` | Stable source-native identifier. |
| `ticker` | `VARCHAR` | Current ticker symbol. |
| `ex_date` | `DATE` | Ex-dividend date. |
| `amount` | `DOUBLE` | Dividend amount per share in local currency. |
| `currency` | `VARCHAR` | Currency code (`KRW`, `USD`). |
| `market` | `VARCHAR` | Market identifier. |
| `source` | `VARCHAR` | Data source identifier. |
| `fetched_at` | `TIMESTAMP` | UTC timestamp. |

### Splits

| Column | Type | Description |
|---|---|---|
| `source_id` | `VARCHAR` | Stable source-native identifier. |
| `ticker` | `VARCHAR` | Current ticker symbol. |
| `date` | `DATE` | Split effective date. |
| `ratio_from` | `DOUBLE` | Original shares (e.g., 1 in a 1:4 split). |
| `ratio_to` | `DOUBLE` | New shares (e.g., 4 in a 1:4 split). |
| `market` | `VARCHAR` | Market identifier. |
| `source` | `VARCHAR` | Data source identifier. |
| `fetched_at` | `TIMESTAMP` | UTC timestamp. |

### Instrument Metadata

One file per market, overwritten on each run.

| Column | Type | Description |
|---|---|---|
| `source_id` | `VARCHAR` | Stable source-native identifier. Primary key. |
| `ticker` | `VARCHAR` | Current ticker symbol (overwritten to latest each run). |
| `name` | `VARCHAR` | Current instrument name (overwritten to latest each run). |
| `market` | `VARCHAR` | Market identifier (`krx`, `us`). |
| `asset_type` | `VARCHAR` | `stock` or `etf`. |
| `exchange` | `VARCHAR` | Exchange code (e.g., `KOSPI`, `KOSDAQ`, `NYSE`, `NASDAQ`). |
| `currency` | `VARCHAR` | Trading currency (`KRW`, `USD`). |
| `is_active` | `BOOLEAN` | `true` if currently listed and trading. |
| `delisted_date` | `DATE` | Date delisting was detected. Null if active. |
| `first_seen` | `DATE` | Date instrument first appeared in universe. |
| `last_updated` | `DATE` | Date metadata was last refreshed. |

### Quarantine Log

| Column | Type | Description |
|---|---|---|
| `source_id` | `VARCHAR` | Stable source-native identifier. |
| `ticker` | `VARCHAR` | Instrument ticker (at time of failure). |
| `market` | `VARCHAR` | Market identifier. |
| `date` | `DATE` | Trading date that failed. |
| `stage` | `VARCHAR` | Pipeline stage (`ingestion`, `validation`). |
| `error_type` | `VARCHAR` | Error category (`missing_data`, `validation_failed`, `api_error`, `timeout`). |
| `error_detail` | `VARCHAR` | Error message or details. |
| `created_at` | `TIMESTAMP` | UTC timestamp. |

## Required Datasets

| Dataset | Location | Granularity | Updated |
|---|---|---|---|
| OHLCV (KRX) | `data/ohlcv/krx/{YYYY}/{YYYY-MM-DD}.parquet` | Per trading day | Daily |
| OHLCV (US) | `data/ohlcv/us/{YYYY}/{YYYY-MM-DD}.parquet` | Per trading day | Daily |
| Dividends (KRX) | `data/dividends/krx/{YYYY}/{YYYY-MM-DD}.parquet` | Per trading day | Daily (best-effort) |
| Dividends (US) | `data/dividends/us/{YYYY}/{YYYY-MM-DD}.parquet` | Per trading day | Daily (best-effort) |
| Splits (KRX) | `data/splits/krx/{YYYY}/{YYYY-MM-DD}.parquet` | Per trading day | Daily (best-effort) |
| Splits (US) | `data/splits/us/{YYYY}/{YYYY-MM-DD}.parquet` | Per trading day | Daily (best-effort) |
| Universe snapshot (KRX) | `data/universe/krx/{YYYY-MM-DD}.parquet` | Per calendar day | Daily |
| Universe snapshot (US) | `data/universe/us/{YYYY-MM-DD}.parquet` | Per calendar day | Daily |
| Instrument metadata (KRX) | `data/meta/instruments_krx.parquet` | Singleton | Overwritten daily |
| Instrument metadata (US) | `data/meta/instruments_us.parquet` | Singleton | Overwritten daily |
| Quarantine log | `data/meta/quarantine/{YYYY-MM-DD}_{market}.parquet` | Per run | Overwritten per date+market on re-run |

## Raw vs Adjusted Policy

| Market | Raw Columns | Adjusted Columns | Default Backtest Series | Source |
|---|---|---|---|---|
| US | `open, high, low, close, volume` | `adj_open, adj_high, adj_low, adj_close, adj_volume` | `adj_close` (dividend + split adjusted) | Tiingo `adj*` fields |
| KRX | `open, high, low, close, volume` | `adj_open, adj_high, adj_low, adj_close, adj_volume` | `adj_close` from provider | `pykrx` adjusted prices |

- Raw and adjusted columns coexist in the same OHLCV file. No separate directory trees.
- If a source does not provide adjusted values for an instrument, `adj_*` columns are set to null. The raw columns are still written. The instrument is not excluded.
- Adjusted series are never self-calculated in v1.
- **Staleness**: Adjusted prices are point-in-time as of the date they were fetched. Tiingo retroactively updates `adj*` values after each dividend. Only re-fetching (via backfill) refreshes historical adjusted prices. This is a known v1 limitation. Recommend periodic re-backfill (e.g., monthly) for users who need consistent historical adjusted series.

## Delisting / Halt Handling Policy

### Delisting

- **Detection**: Compare current universe fetch against stored instrument metadata. Instruments absent from the current universe that were previously active are candidates for delisting.
- **Safety threshold**: If >20% of previously active instruments are absent, assume a data source anomaly. Log error, skip delisting detection, proceed with previous universe. This prevents mass false-positive delistings from source outages or fetch failures.
- **Marking**: Set `is_active = false` and `delisted_date = today` in instrument metadata.
- **Data retention**: All historical OHLCV data for delisted instruments remains in Parquet files. Delisted instruments are still queryable by filtering on `source_id`.
- **Serving**: Default queries should filter on `is_active = true` (via instrument metadata join or where clause). Backtesting engine may explicitly include delisted instruments for survivorship-bias-free analysis.
- **Re-listing**: If an instrument reappears after being marked delisted, set `is_active = true` and clear `delisted_date`. Log a warning. This handles temporary listing suspensions.

### Trading Halts

- **Detection**: Heuristic-based. If a market was open (per `exchange_calendars`) but an active instrument has volume=0 or is absent from the OHLCV data for that date, it may be halted.
- **Storage**: Not a separate dataset in v1. The signal is implicit in the OHLCV data (missing row or volume=0).
- **Logging**: Log instruments with suspected halts at WARNING level for auditing.
- **Future**: Add an explicit `is_halted` boolean column to OHLCV if sources provide reliable halt data.

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
| V7: No duplicate source_id+date | Unique constraint on `(source_id, date)` | Keep last, warn |
| V8: Price spike detection | `abs(close / prev_close - 1) > 0.50` | Warning only (legitimate for limit-up/down, IPOs, etc.) |

- **Quarantine severity**: Remove the instrument-date row from the output Parquet file. Write the row + error details to the quarantine log.
- **Warning severity**: Log the issue but keep the data in the output.
- **V8 note**: Korean markets have daily price limits (±30%). US has no hard limits. A >50% change is unusual but possible (e.g., post-halt, merger, reverse split). Warning-only is correct.
- **Adjusted price validation**: If `adj_close` is present and non-null, apply V1–V4 to adjusted prices as well. Quarantine if adjusted prices fail basic sanity.

## Error Handling

| Error Type | Behavior |
|---|---|
| API connection failure (total) | Retry 3 times with exponential backoff (2s, 4s, 8s). If all retries fail for the universe/bulk fetch, abort the market run and exit non-zero. |
| API rate limit (429) | Wait for `Retry-After` header duration (or 60s default), then retry. Max 3 retries per request. |
| Single instrument fetch failure (US per-ticker) | Log error, add to quarantine for that date, continue with remaining instruments. |
| Empty universe fetch | If universe returns 0 instruments, abort. If >80% present (below safety threshold), proceed normally. |
| Validation failure (instrument-level) | Quarantine the instrument-date, continue batch. |
| Parquet write failure | Critical. Abort the market run. Exit non-zero. Do not partially written state (atomic write via temp file). |
| Config/env missing | Fail fast at startup. Print missing keys and exit. |

### Restart / Partial Failure Behavior

- If a run crashes midway, some Parquet files for that date may have been written (atomically, so no corrupt files) while others were not.
- **Recovery**: Re-run the same date. The pipeline re-fetches everything and overwrites all files for that date. This is the designed recovery mechanism.
- **Cost**: Wasted API calls for the re-fetch. Acceptable for daily runs.
- **Quarantine on restart**: A re-run overwrites the quarantine file for that date+market, so quarantine state is consistent with the latest run.

## Quarantine Policy

- Quarantined instrument-dates are written to `data/meta/quarantine/{YYYY-MM-DD}_{market}.parquet`.
- Quarantined data is excluded from the output OHLCV Parquet file.
- Quarantine is informational: it records what failed and why, for later investigation.
- No automatic retry of quarantined instruments. Re-running the date will re-attempt and re-evaluate.
- Quarantine files are overwritten per date+market on re-run (consistent with idempotent overwrite policy).
- Quarantine files across different dates accumulate (not overwritten). A cleanup utility may be added later.

## Idempotency and Overwrite Policy

- **OHLCV files**: One file per date per market. Re-running a date overwrites the file completely via atomic write (temp file + rename).
- **Dividends/Splits files**: Same as OHLCV — one file per date per market, overwritten on re-run.
- **Instrument metadata**: Overwritten in full on every run. Represents current state only.
- **Universe snapshots**: One file per date per market. Overwritten on re-run.
- **Quarantine**: Overwritten per date + market on re-run.
- **No append mode anywhere**: All writes are full-file overwrites. No duplicate row risk. Idempotent by construction.
- **Backfill**: Running backfill on already-populated dates overwrites existing files. Always trusts the latest provider data.
- **Reproducibility limitation**: Because overwrites replace files and providers may retroactively change data (especially adjusted prices), exact reproduction of a previous backtest requires a copy/snapshot of the data directory at that point in time. v1 does not provide built-in snapshotting.

## Scheduling Model

```
# crontab entries (server in UTC)

# KRX: 30 min after 15:30 KST close = 16:00 KST = 07:00 UTC
0 7 * * 1-5  cd /path/to/getstock && python -m getstock run --market krx >> data/logs/cron_krx.log 2>&1

# US: 30 min after 16:00 ET close = 16:30 ET = 21:30 UTC (EST) / 20:30 UTC (EDT)
# Use 21:30 UTC (safe for EST; 1 hour after close during EDT)
30 21 * * 1-5  cd /path/to/getstock && python -m getstock run --market us >> data/logs/cron_us.log 2>&1
```

- Each cron entry is a single CLI invocation.
- Exit code 0 = success (including "not a trading day, nothing to do"). Non-zero = failure.
- The CLI determines the correct trading date based on `exchange_calendars`. If today is not a trading day, exit 0 with a log message.
- Backfill is a separate CLI command: `python -m getstock backfill --market krx --start 2025-03-16 --end 2026-03-16`.
- **EDT/EST note**: The US cron time is set for EST (21:30 UTC). During EDT, the run happens ~1 hour after close instead of 30 minutes. This is acceptable; the data is available by then. A more precise approach would use a timezone-aware scheduler, but cron with a fixed UTC time is simpler and sufficient.

## Configuration / Secrets Handling

### `.env` file

```
TIINGO_API_KEY=your_api_key_here
```

- Loaded via `python-dotenv` at startup.
- `.env` is in `.gitignore`.
- Only `TIINGO_API_KEY` is required. KRX data via `pykrx` does not require an API key.
- If `TIINGO_API_KEY` is missing and `--market us` is requested, fail fast with a clear error.
- If `TIINGO_API_KEY` is missing and `--market krx` is requested, proceed (KRX does not need it).

### `config.yaml`

```yaml
data_dir: ./data

markets:
  krx:
    timezone: Asia/Seoul
    exchange_calendar: XKRX
    close_time: "15:30"
    run_delay_minutes: 30
    asset_types: [stock]
    source: pykrx
  us:
    timezone: US/Eastern
    exchange_calendar: XNYS
    close_time: "16:00"
    run_delay_minutes: 30
    asset_types: [stock, etf]
    source: tiingo
    universe_filter: all  # Options: "all", "watchlist", or path to CSV file
    # watchlist: [AAPL, MSFT, GOOGL]  # Used when universe_filter: watchlist

backfill:
  lookback_days: 365

validation:
  price_change_warn_threshold: 0.50

delisting:
  safety_threshold: 0.20  # Skip delisting if >20% of universe disappears

logging:
  level: INFO
  file_enabled: true
```

- Config is loaded once at startup.
- Paths in config are relative to project root.

## Logging / Observability

- **Library**: Python `logging` module. No external dependencies.
- **Format**: `%(asctime)s | %(levelname)s | %(name)s | %(message)s`
- **Outputs**: stdout (always) + file (if configured). File per run: `data/logs/{YYYY-MM-DD}_{market}.log`.
- **Log levels**:
  - `INFO`: Run start/end, instrument counts, file writes, trading day determination.
  - `WARNING`: Missing data, quarantined instruments, heuristic halt detection, skipped delisting (safety threshold), adjusted price nulls.
  - `ERROR`: API failures after retries, critical write failures, empty universe fetch.
- **Run summary**: At end of each run, log a structured summary:
  ```
  RUN SUMMARY | market=us | date=2026-03-15 | universe=500 | fetched=495 | quarantined=3 | skipped=2 | duration=4m32s
  ```
- **No external monitoring in v1.** Rely on cron output and log files. Future: add notification on non-zero exit.

## Testing Strategy

### Unit Tests

- **Schema validation**: Verify normalized DataFrames match canonical schema (column names, types).
- **Validation rules**: Test each rule (V1–V8) with crafted DataFrames containing known good and bad rows.
- **Normalization**: Test source-to-canonical field mapping for each market with fixture data.
- **Quarantine logic**: Verify failed instruments are correctly quarantined and excluded from output.
- **Delisting detection**: Test safety threshold logic. Test normal delisting. Test re-listing.
- **Universe filtering**: Test `all`, `watchlist`, and CSV filter modes.

### Integration Tests

- **Mock API tests**: Use recorded API responses (fixtures) to test full pipeline without network.
- **Parquet round-trip**: Write and read back Parquet files; verify schema, data integrity, and sort order.
- **DuckDB query tests**: Verify expected queries return correct results against test Parquet files.
- **Idempotency tests**: Run pipeline twice on same date; verify output files are byte-identical.
- **Quarantine persistence**: Inject a bad ticker, verify it appears in quarantine file and is absent from OHLCV file.

### Manual / Smoke Tests

- **Single-ticker test**: Run pipeline for one ticker, one date, inspect output.
- **Backfill test**: Backfill 1 week for a small subset; verify file structure and data.
- **Holiday handling**: Run on a known market holiday; verify early exit with code 0.

### Test Tooling

- `pytest` as test runner.
- `responses` library for HTTP mocking (Tiingo).
- `unittest.mock` for `pykrx` mocking.
- Test fixtures stored in `tests/fixtures/`.

## Explicit Trade-offs and Rationale

| Trade-off | Chosen approach | Alternative considered | Why |
|---|---|---|---|
| Single OHLCV file (raw+adj) vs separate trees | Single file | Separate `raw/` and `adjusted/` directories | Avoids data duplication. Most queries need both. Simpler DuckDB queries. Null `adj_*` columns handle missing adjusted data cleanly. |
| `source_id` as PK vs `ticker` as PK | `source_id` | `ticker` only | Tickers change (renames) and get recycled (delisting + relisting of new company). `source_id` is stable. `ticker` is kept for readability. |
| Date-partitioned vs ticker-partitioned Parquet | Date-partitioned | Ticker-partitioned | Daily overwrites affect one file. Cross-sectional queries align with rebalancing. Ticker-partitioned requires rewriting per-ticker files on every run. |
| Overwrite vs append | Overwrite per date | Append with dedup | Simpler write path. No duplicate row risk. Idempotent by construction. |
| Provider-adjusted vs self-calculated (KRX) | Provider-adjusted | Self-calculate from splits/dividends | Self-calculation requires verified corporate action history. Provider values are good enough for v1. |
| `pykrx` bulk per-date vs per-ticker | Bulk per-date for daily runs | Per-ticker for each instrument | One HTTP request per date vs thousands. Dramatically faster for daily runs. Per-ticker used only for backfill adjusted prices if needed. |
| Configurable US universe filter | Filter supported, default `all` | Always fetch full universe | Free-tier rate limits make full-universe daily runs take hours. Filter lets users start small. |
| DuckDB direct-on-Parquet vs persistent DB | Direct on Parquet | Persistent DuckDB file | One year of data is small. Avoids sync between Parquet source-of-truth and DB. |
| Cron vs dedicated scheduler | Cron | APScheduler, Celery | Zero additional dependencies. Single-server, single-maintainer. |
| Single process, sequential | Single process | asyncio / multiprocessing | Simplicity. Rate limits make parallelism less useful. Daily runs are not latency-sensitive. |
| Instrument-level quarantine vs batch abort | Instrument-level quarantine | Fail entire batch | Maximizes data availability. One bad ticker should not block thousands of others. |
| Overwrite ticker/name vs history tracking | Overwrite to current | Slowly changing dimension table | Ticker history is complex (mergers, symbol changes). Overwrite is sufficient for v1. |
| Adjusted price staleness accepted | Point-in-time adjusted prices, periodic re-backfill | Retroactive update of all historical files on each run | Retroactive update would require re-fetching all historical dates daily. Impractical on free tier. Staleness is acceptable; re-backfill is the workaround. |
