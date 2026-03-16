# Getstock

Daily ETL module that ingests, normalizes, and stores equity market data for strategy backtesting. Covers Korean common stocks (KRX) and US stocks/ETFs (Tiingo), producing daily OHLCV with both raw and adjusted prices stored in Parquet files and queryable via DuckDB.

## Features

- **Two markets**: KRX (via `pykrx`) and US (via Tiingo REST API)
- **Daily OHLCV**: Raw and adjusted prices in a single file per market per date
- **Instrument tracking**: Stable `source_id` keys, delisting detection with safety threshold
- **Validation**: 8 rules (V1–V8) with instrument-level quarantine
- **Backfill**: 1-year historical ingestion with progress logging
- **DuckDB queries**: Read Parquet files directly with glob patterns
- **Idempotent**: Re-running any date overwrites cleanly via atomic writes

## Setup

### Prerequisites

- Python 3.10+
- Tiingo API key (free tier, required for US market only)

### Installation

```bash
git clone https://github.com/dohyeong-kim-95/Getstock.git
cd Getstock
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configuration

1. Copy the environment file and add your Tiingo API key:

```bash
cp .env.example .env
# Edit .env and set TIINGO_API_KEY=your_key_here
```

2. Review `config.yaml` for market settings, universe filter, and thresholds. Defaults work out of the box for KRX. For US, configure the universe filter to stay within free-tier rate limits:

```yaml
markets:
  us:
    universe_filter: watchlist
    watchlist: [AAPL, MSFT, GOOGL, AMZN, NVDA]
```

Options for `universe_filter`:
- `all` — every supported Tiingo ticker (~8,000+, may take hours on free tier)
- `watchlist` — explicit list in config (recommended for free tier)
- `/path/to/tickers.csv` — CSV file with ticker column

## Usage

### Daily Run

```bash
# Run for today's trading date (skips if not a trading day)
python -m getstock run --market krx
python -m getstock run --market us

# Run for a specific date
python -m getstock run --market krx --date 2026-03-13
```

### Backfill

```bash
# Backfill 1 year of KRX data
python -m getstock backfill --market krx --start 2025-03-16 --end 2026-03-16

# Backfill US data for a small date range
python -m getstock backfill --market us --start 2026-03-01 --end 2026-03-15

# Dry run — log what would be fetched without writing
python -m getstock backfill --market krx --start 2026-03-01 --end 2026-03-15 --dry-run
```

**Timing estimates**:
- KRX daily run: ~1–2 minutes (bulk API, one request per date + per-ticker adjusted prices)
- KRX 1-year backfill: ~30–60 minutes (365 dates × polite pacing)
- US daily run: ~2–5 minutes for 500 tickers (per-ticker API with rate limiting)
- US 1-year backfill for 500 tickers: several hours (rate-limited)

### Query

```bash
# Query stored OHLCV data
python -m getstock query --market us --ticker AAPL --start 2026-01-01 --end 2026-03-15
python -m getstock query --market krx --ticker 005930
```

## Cron Configuration

Schedule daily runs after each market close:

```bash
# crontab -e (server in UTC)

# KRX: 30 min after 15:30 KST close = 16:00 KST = 07:00 UTC
0 7 * * 1-5  cd /path/to/Getstock && python -m getstock run --market krx >> data/logs/cron_krx.log 2>&1

# US: 30 min after 16:00 ET close = 16:30 ET = 21:30 UTC (EST) / 20:30 UTC (EDT)
30 21 * * 1-5  cd /path/to/Getstock && python -m getstock run --market us >> data/logs/cron_us.log 2>&1
```

Exit codes: `0` = success (including "not a trading day"), non-zero = failure.

## Data Directory Layout

```
data/
├── ohlcv/
│   ├── krx/
│   │   └── 2026/
│   │       └── 2026-03-13.parquet
│   └── us/
│       └── 2026/
│           └── 2026-03-13.parquet
├── dividends/
│   ├── krx/...
│   └── us/...
├── splits/
│   ├── krx/...
│   └── us/...
├── universe/
│   ├── krx/
│   │   └── 2026-03-13.parquet
│   └── us/
│       └── 2026-03-13.parquet
├── meta/
│   ├── instruments_krx.parquet
│   ├── instruments_us.parquet
│   ├── quarantine/
│   │   └── 2026-03-13_krx.parquet
│   └── runs/
│       └── 2026-03-13_krx.json
└── logs/
    └── 2026-03-13_krx.log
```

## DuckDB Query Examples

No database setup required — DuckDB reads Parquet files directly.

```sql
-- Adjusted close for a single ticker (all dates)
SELECT date, adj_close
FROM read_parquet('data/ohlcv/us/**/*.parquet')
WHERE ticker = 'AAPL'
ORDER BY date;

-- Cross-sectional: all tickers for a date range
SELECT source_id, ticker, date, adj_close
FROM read_parquet('data/ohlcv/us/**/*.parquet')
WHERE date BETWEEN '2026-01-01' AND '2026-03-15'
ORDER BY source_id, date;

-- All adjusted closes for a single date
SELECT source_id, ticker, adj_close
FROM read_parquet('data/ohlcv/us/2026/2026-03-13.parquet');

-- Active instruments
SELECT * FROM read_parquet('data/meta/instruments_us.parquet')
WHERE is_active = true;

-- Join OHLCV with instrument metadata
SELECT o.date, o.ticker, o.adj_close, i.name, i.exchange
FROM read_parquet('data/ohlcv/us/**/*.parquet') o
JOIN read_parquet('data/meta/instruments_us.parquet') i
  ON o.source_id = i.source_id
WHERE i.is_active = true AND o.date >= '2026-01-01'
ORDER BY o.ticker, o.date;
```

## Quarantine Inspection

When instruments fail validation, they are quarantined (excluded from output) and logged:

```sql
-- View all quarantine entries for US
SELECT * FROM read_parquet('data/meta/quarantine/*_us.parquet')
ORDER BY date DESC;

-- Check quarantine for a specific date
SELECT source_id, ticker, error_type, error_detail
FROM read_parquet('data/meta/quarantine/2026-03-13_us.parquet');

-- Count quarantined instruments per date
SELECT date, count(*) as quarantined
FROM read_parquet('data/meta/quarantine/*_krx.parquet')
GROUP BY date ORDER BY date DESC;
```

## Run Manifests

Each run writes a JSON summary to `data/meta/runs/{date}_{market}.json`:

```json
{
  "market": "krx",
  "date": "2026-03-13",
  "status": "success",
  "started_at": "2026-03-13T07:00:12Z",
  "finished_at": "2026-03-13T07:02:45Z",
  "duration_seconds": 153,
  "universe_size": 2487,
  "fetched_count": 2485,
  "quarantined_count": 2,
  "files_written": ["instruments", "universe", "ohlcv", "quarantine", "run_manifest"]
}
```

## Architecture

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
               │
               ▼
┌─────────────────────────────────┐
│       Normalization Layer       │
│  (canonical schema mapping)     │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│        Validation Layer         │
│  (V1–V8, quarantine bad rows)   │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│         Storage Layer           │
│  (atomic Parquet writes)        │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│         DuckDB (query)          │
│  (reads Parquet directly)       │
└─────────────────────────────────┘
```

Key design decisions:
- **`source_id`** (not `ticker`) is the stable primary key — tickers change, source IDs don't
- **Date-partitioned Parquet** — one file per market per date, atomic overwrites
- **Single OHLCV file** — raw + adjusted columns together, no duplicate directory trees
- **Instrument-level quarantine** — one bad ticker doesn't block the entire batch

## Adjusted Price Staleness

Adjusted prices are point-in-time snapshots. After a new dividend or split, historical `adj_*` values in previously written files become stale. v1 has no automatic historical refresh. Workaround:

```bash
# Periodic re-backfill (e.g., monthly)
python -m getstock backfill --market us --start 2025-03-16 --end 2026-03-16
```

## Running Tests

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## Project Structure

```
getstock/
├── __main__.py          # CLI entry point
├── cli.py               # Click CLI commands (run, backfill, query)
├── config.py            # Config + env loading
├── schema.py            # Canonical schema constants
├── sources/
│   ├── krx.py           # KRX fetcher via pykrx
│   └── tiingo.py        # Tiingo fetcher via REST API
├── normalize.py         # Source → canonical schema mapping
├── validate.py          # Validation rules (V1–V8)
├── universe.py          # Universe management & delisting detection
├── quarantine.py        # Quarantine handling
├── storage.py           # Atomic Parquet read/write
├── pipeline.py          # Orchestration
├── query.py             # DuckDB query helpers
└── logging_config.py    # Logging setup
```
