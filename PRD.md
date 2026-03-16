# PRD.md

## Overview

Getstock is a daily end-of-day ETL module that ingests, normalizes, and stores equity market data for use in strategy backtesting. It covers Korean common stocks (KRX) and US stocks/ETFs (Tiingo), producing daily OHLCV with both raw and adjusted prices stored in Parquet files and queryable via DuckDB.

## Problem Statement

Backtesting trading strategies requires clean, consistent, daily OHLCV data with corporate action adjustments (dividends, splits) and delisting awareness. No single free data source covers both KRX and US markets in a unified schema. Manual data gathering is error-prone and non-reproducible.

This module solves the data foundation problem: reliable, automated, daily ingestion from two markets into a single queryable format.

## Goals

1. Provide a single local data store of daily OHLCV + corporate actions for KRX and US equities.
2. Automate daily incremental ingestion, running once per day per market after close.
3. Produce both raw and adjusted price series suitable for backtesting in a single queryable dataset.
4. Make the data queryable via DuckDB for research and strategy development.
5. Handle instrument-level failures gracefully without failing the full batch.

## Non-Goals

- Real-time or intraday data.
- Order book or tick data.
- Strategy execution or signal generation.
- Multi-user access or API serving.
- Cloud deployment or distributed processing.
- Full historical ticker/name change tracking (v1 overwrites to current).
- Self-calculated adjusted prices for Korean stocks (v1 uses provider-adjusted values).
- Fetching the entire US equity universe on free-tier Tiingo in a single daily run (see Constraints).

## Users / Consumers

| Consumer | Usage |
|---|---|
| Strategy backtesting engine | Reads adjusted daily close series from Parquet/DuckDB. Operates on daily close only. |
| Research notebooks | Ad-hoc DuckDB queries over raw and adjusted data. |
| Single maintainer (author) | Operates, monitors, and extends the pipeline. |

## Scope

### In-Scope (v1)

- **Markets**: KRX (Korean common stocks), US (stocks + ETFs).
- **Data types**: Daily OHLCV (raw + adjusted in single dataset), dividends (best-effort), splits (best-effort), delisting detection (inferred from universe snapshots), suspected trading halts (heuristic warnings only, not an authoritative dataset).
- **Sources**: KRX public data via `pykrx` for Korea (primary; official KRX Open API evaluated and deferred to fallback role), Tiingo REST API for US.
- **Backfill**: Full universe, most recent 1 year.
- **Incremental updates**: Once per day, 30 minutes after each market close.
- **Storage**: Parquet files, DuckDB as read-only query layer.
- **Adjusted series**: Tiingo-provided dividend-adjusted prices for US; `pykrx`-provided adjusted prices for KRX. Both stored alongside raw prices in the same OHLCV file.
- **Instrument identity**: Stable source-native identifiers (`source_id`) as primary key, with human-readable `ticker` updated to current on each run.
- **US universe filtering**: Configurable universe filter (default: all supported tickers; can be restricted to a watchlist or index constituents to stay within free-tier rate limits).

### Out-of-Scope (v1)

- Intraday or real-time data.
- Fundamental data, earnings, or financial statements.
- Options, futures, or derivatives.
- Alternative data sources or fallback providers.
- Ticker/name history tracking (overwrite to current).
- Serving API or web interface.
- Multi-user or concurrent access patterns.
- Rebalancing logic (owned by strategy engine).

## Functional Requirements

### FR-1: Universe Management

- Maintain a list of active instruments per market (KRX, US).
- Each instrument has a stable `source_id` (KRX 6-digit stock code; Tiingo `permaTicker`) that does not change across ticker renames.
- The `ticker` and `name` fields are overwritten to current values on each run. `source_id` is the stable join key across all datasets.
- Include common stocks for KRX; stocks and ETFs for US.
- Mark instruments as delisted when detected; exclude from default active universe.
- Preserve delisting metadata (date, reason if available) in instrument metadata.
- **Safety check**: If >20% of previously active instruments disappear in a single universe fetch, treat as a data-source anomaly. Log an error, skip delisting detection for that run, and proceed with the previous universe.

### FR-2: Daily OHLCV Ingestion

- Fetch daily OHLCV for all active instruments per market.
- KRX: Bulk fetch via `pykrx` per-date API (all tickers in one call per date).
- US: Fetch via Tiingo per-ticker daily endpoint with rate limiting.
- Store raw OHLCV and provider-adjusted prices in the same output file, one file per market per date.

### FR-3: Corporate Actions

- **Dividends**: Ingest dividend records per instrument per date.
- **Splits**: Ingest split records per instrument per date.
- US: Use Tiingo's adjusted close as the default backtest series (dividend-adjusted).
- KRX: Use `pykrx`-supplied adjusted prices; do not self-calculate in v1.
- Corporate action data quality may be incomplete in v1. Store what the source provides; log warnings for missing data.

### FR-4: Delisting Detection and Trading Halt Warnings

- **Delisting**: Inferred by comparing consecutive universe snapshots — not sourced from a dedicated delisting event feed. If a previously active instrument disappears from the universe fetch (subject to the >20% safety threshold in FR-1), mark it as delisted. This is inference-based detection; the exact delisting date may lag by one trading day.
- **Trading halts**: Best-effort heuristic only. If an active instrument has volume=0 or is absent from OHLCV data on a trading day, log a warning. v1 does not produce an authoritative halt dataset — halt signals are informational log warnings, not stored data.
- Delisted instruments remain in historical data but are excluded from the active serving universe.
- Historical OHLCV for delisted instruments is preserved and queryable when explicitly requested.

### FR-5: Initial Backfill

- On first run (or explicit trigger), backfill 1 year of history for the full universe.
- Backfill must be idempotent: re-running overwrites with latest provider data.
- Backfill fetches data per-date (not per-ticker) where possible to minimize API calls.

### FR-6: Incremental Daily Update

- Run once per day per market, 30 minutes after market close.
- KRX batch and US batch run independently.
- Fetch only the latest trading day's data for active instruments.
- Overwrite if data for that date already exists (idempotent).

### FR-7: Adjusted Series Generation

- Produce adjusted OHLCV for backtesting.
- US: Default to Tiingo's `adjClose` (dividend-adjusted). Store all `adj*` fields alongside raw prices.
- KRX: Use provider-adjusted values as-is alongside raw prices.
- **Staleness warning**: Adjusted prices are point-in-time snapshots as of the date they were fetched. Daily runs only write the current date's file — historical files are never retroactively updated. After a new dividend or split, all historical `adj_*` values in previously written files become stale. v1 has no automatic historical refresh. The workaround is manual periodic re-backfill (e.g., `python -m getstock backfill --market us --start ... --end ...`). Users relying on adjusted series for backtesting should be aware of this limitation.

### FR-8: Storage

- Write Parquet files organized by data type and market.
- OHLCV files contain both raw and adjusted columns in a single file (no separate raw/adjusted trees).
- Dividends and splits stored in their own file paths.
- Support DuckDB reads directly from Parquet files via glob patterns.

### FR-9: Validation

- Validate row counts, date ranges, and price sanity (e.g., close > 0, high >= low).
- Missing data raises warnings, does not fail the batch.
- Validation failures are isolated at instrument level.
- Failed instruments are quarantined (logged, flagged) but do not block the rest.
- Quarantined instrument-dates are excluded from the output Parquet file for that date.

### FR-10: Data Overwrite Policy

- If provider data changes (corrections, restatements), overwrite with latest on re-run.
- No versioning of historical corrections in v1.
- Re-running a date (manually or via backfill) re-fetches and overwrites. This is the mechanism for correcting stale data.

## Non-Functional Requirements

- **NFR-1**: Daily incremental run must complete within 60 minutes for KRX. US run time depends on universe size and rate limits; 60 minutes for ~500 instruments, proportionally longer for larger universes.
- **NFR-2**: All configuration and API keys stored in `.env`, not in code.
- **NFR-3**: Logging to stdout/file with structured messages (timestamp, market, stage, status). Each run writes a lightweight JSON run manifest (`data/meta/runs/{date}_{market}.json`) with counts, status, timing, and errors for debugging.
- **NFR-4**: All dependencies must be free/open-source. APIs must have a free tier.
- **NFR-5**: Single-process execution; no distributed coordination needed.
- **NFR-6**: Cron-compatible: each run is a single CLI invocation with exit code 0 on success.

## Success Criteria

1. Full 1-year backfill completes for KRX without manual intervention. US backfill completes for the configured universe subset.
2. Daily incremental update runs unattended via cron for 7 consecutive days without failure.
3. DuckDB can query adjusted daily close for any instrument in the universe in < 1 second.
4. Instrument-level failures are quarantined without aborting the batch.
5. Parquet files are readable by any Parquet-compatible tool. Schema is self-documenting.
6. Re-running the same date produces identical output (idempotent).

## Constraints

- Single maintainer: no operations team, no on-call.
- Free APIs only: `pykrx` (scrapes KRX), Tiingo free tier.
- Local or single-server execution.
- Python ecosystem (aligns with DuckDB, Parquet, and data tooling).
- **Tiingo free-tier rate limits**: The free tier limits API request throughput. For the full US equity universe (~8,000+ instruments), per-ticker fetching may require many hours. v1 defaults to a configurable universe filter. Users can start with a manageable subset (e.g., S&P 500, ~500 instruments) and expand as needed or upgrade to a paid tier.
- **`pykrx` pacing**: `pykrx` scrapes KRX and has no formal API key or rate limit, but polite request pacing is still required to avoid being blocked. The bulk per-date API (`get_market_ohlcv`) fetches all tickers in one call, making daily runs fast (~1 request). For backfill (many dates) or per-ticker adjusted price calls, add delays (1s between bulk calls, 0.5s between per-ticker calls) to avoid overloading the upstream KRX site.

## Risks / Open Questions

| # | Risk / Question | Mitigation / Default |
|---|---|---|
| R1 | Tiingo free tier cannot fetch full US universe (~8,000 tickers) within 60 minutes. | Default to a filtered universe (configurable watchlist or index membership). Document how to expand. Periodic bulk backfill can run overnight. |
| R2 | `pykrx` API stability: it scrapes KRX, which may change HTML/endpoints without notice. | Pin `pykrx` version. Monitor for breakage. Upstream library is actively maintained. Fallback contingency: the official KRX Open API (`openapi.krx.co.kr`, 31 endpoints, data from 2010+) can provide raw OHLCV if `pykrx` breaks, though it lacks adjusted prices and corporate actions. |
| R3 | `pykrx` adjusted prices may not be available for all KRX instruments or all dates. | Log warning, store raw-only for those instruments. Adjusted columns set to null. |
| R4 | Delisting detection: universe fetch anomaly (source outage) could false-positive delist everything. | Safety threshold: skip delisting if >20% of universe disappears in one run. |
| R5 | Adjusted price staleness: daily runs only update the current date's file. Historical adjusted prices become stale after each new dividend. | Document limitation. Recommend periodic re-backfill (e.g., monthly). |
| R6 | Trading halt data may not be reliably available from all sources. | Best-effort heuristic (volume=0 or missing data). Mark detection method in logs. |
| R7 | Schema evolution as new fields or markets are added. | Parquet is schema-aware. Add columns as needed; old files remain readable with null for new columns. |
| R8 | Ticker reuse: A ticker symbol may be assigned to a different company after delisting. | `source_id` (not `ticker`) is the stable primary key. Ticker collisions across different entities are avoided via `source_id`. |

## v1 Decisions Already Made

| Decision | Rationale |
|---|---|
| **Korea source: `pykrx` (primary), KRX Open API (fallback only)** | The official KRX Open API (`openapi.krx.co.kr`) was evaluated and rejected as the v1 primary source. It lacks adjusted prices, dividends, and splits endpoints; requires per-service approval (up to 1 business day); has a 10,000 requests/day limit; and prohibits commercial use. `pykrx` provides bulk per-date OHLCV, adjusted prices via per-ticker calls, and requires no API key or approval. KRX Open API is retained as a future fallback if `pykrx` breaks. |
| Single OHLCV file with raw + adjusted columns | Avoids duplicating data across two directory trees. Most queries need both raw and adjusted. Simplifies DuckDB queries. |
| `source_id` as stable primary key | Tickers change and get recycled. KRX stock codes and Tiingo `permaTicker` are stable identifiers. `ticker` is kept for readability but is not the join key. |
| US default backtest series = Tiingo dividend-adjusted close | Most common adjustment for equity backtesting. |
| KRX adjusted prices = provider-supplied values | Self-calculation requires verified corporate action history; defer to v2. |
| Overwrite ticker/name to current | Full ticker history tracking is complex; not needed for v1 backtesting. |
| Delisted instruments excluded from active universe | Delisting is inferred from universe snapshot comparison, not a dedicated event feed. Detection may lag by one trading day. Prevents lookahead bias in strategy selection. Historical data preserved for survivorship analysis. |
| Overwrite on provider data change | Simplest policy; no versioning overhead. |
| 1-year backfill only | Limits initial data volume; sufficient for strategy development. |
| Instrument-level quarantine on failure | Maximizes data availability per batch. |
| Parquet + DuckDB | Zero-infrastructure analytical stack; fast, local, free. |
| Cron-based scheduling | Simplest scheduler for single-server, single-maintainer operation. |
| Configurable US universe filter | Free-tier rate limits make full-universe daily runs infeasible. Start small, expand later. |

## Future Extensions

- Extend backfill to full available history.
- Add fallback data sources (e.g., Yahoo Finance, FRED for macro).
- Evaluate KRX Open API as a fallback or validation source for Korea data (raw OHLCV cross-check against `pykrx`).
- Ticker/name change history tracking.
- Self-calculated adjusted prices for KRX.
- Fundamental data (earnings, financials).
- Additional markets (Japan, Europe).
- Data quality dashboards.
- Webhook or notification on pipeline failure.
- Restatement versioning (keep history of provider corrections).
- Automated periodic re-backfill to refresh adjusted prices.
