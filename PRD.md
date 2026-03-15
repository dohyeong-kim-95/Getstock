# PRD.md

## Overview

Getstock is a daily end-of-day ETL module that ingests, normalizes, and stores equity market data for use in strategy backtesting. It covers Korean common stocks (KRX) and US stocks/ETFs (Tiingo), producing both raw and adjusted OHLCV series stored in Parquet files and queryable via DuckDB.

## Problem Statement

Backtesting trading strategies requires clean, consistent, daily OHLCV data with corporate action adjustments (dividends, splits), delisting awareness, and trading halt status. No single free data source covers both KRX and US markets in a unified schema. Manual data gathering is error-prone and non-reproducible.

This module solves the data foundation problem: reliable, automated, daily ingestion from two markets into a single queryable format.

## Goals

1. Provide a single local data store of daily OHLCV + corporate actions for KRX and US equities.
2. Automate daily incremental ingestion, running once per day per market after close.
3. Produce both raw and adjusted price series suitable for backtesting.
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

## Users / Consumers

| Consumer | Usage |
|---|---|
| Strategy backtesting engine | Reads adjusted daily close series from Parquet/DuckDB. Operates on daily close only. |
| Research notebooks | Ad-hoc DuckDB queries over raw and adjusted data. |
| Single maintainer (author) | Operates, monitors, and extends the pipeline. |

## Scope

### In-Scope (v1)

- **Markets**: KRX (Korean common stocks), US (stocks + ETFs).
- **Data types**: Daily OHLCV, dividends, splits, delisting status, trading halt status.
- **Sources**: KRX public data for Korea, Tiingo API for US.
- **Backfill**: Full universe, most recent 1 year.
- **Incremental updates**: Once per day, 30 minutes after each market close.
- **Storage**: Parquet files (raw + adjusted), DuckDB as query layer.
- **Adjusted series**: Dividend-adjusted close for US (from Tiingo); provider-adjusted values for KRX.
- **Raw data retention**: Keep raw source data alongside adjusted series.

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
- Include common stocks for KRX; stocks and ETFs for US.
- Mark instruments as delisted when detected; exclude from default active universe.
- Preserve delisting metadata (date, reason if available) in instrument metadata.
- Overwrite ticker and name to current values on each run.

### FR-2: Daily OHLCV Ingestion

- Fetch daily OHLCV for all active instruments per market.
- KRX: Source from KRX public data.
- US: Source from Tiingo API (end-of-day endpoint).
- Store raw OHLCV exactly as received from source.

### FR-3: Corporate Actions

- **Dividends**: Ingest dividend records per instrument per date.
- **Splits**: Ingest split records per instrument per date.
- US: Use Tiingo's adjusted close as the default backtest series (dividend-adjusted).
- KRX: Use provider-supplied adjusted prices; do not self-calculate in v1.

### FR-4: Delisting and Trading Halt

- Detect delisted instruments and flag them in metadata.
- Detect trading halts and record halt status per instrument per date.
- Delisted instruments remain in historical data but are excluded from the active serving universe.

### FR-5: Initial Backfill

- On first run (or explicit trigger), backfill 1 year of history for the full universe.
- Backfill must be idempotent: re-running overwrites with latest provider data.

### FR-6: Incremental Daily Update

- Run once per day per market, 30 minutes after market close.
- KRX batch and US batch run independently.
- Fetch only the latest trading day's data for active instruments.
- Overwrite if data for that date already exists (idempotent).

### FR-7: Adjusted Series Generation

- Produce adjusted OHLCV series for backtesting.
- US: Default to Tiingo's `adjClose` (dividend-adjusted). Store alongside raw.
- KRX: Use provider-adjusted values as-is.

### FR-8: Storage

- Write Parquet files organized by market and data type.
- Keep raw and adjusted data in separate file paths.
- Support DuckDB reads directly from Parquet files.

### FR-9: Validation

- Validate row counts, date ranges, and price sanity (e.g., close > 0, high >= low).
- Missing data raises warnings, does not fail the batch.
- Validation failures are isolated at instrument level.
- Failed instruments are quarantined (logged, flagged) but do not block the rest.

### FR-10: Data Overwrite Policy

- If provider data changes (corrections, restatements), overwrite with latest.
- No versioning of historical corrections in v1.

## Non-Functional Requirements

- **NFR-1**: Pipeline must complete within 60 minutes per market per daily run.
- **NFR-2**: All configuration and API keys stored in `.env`, not in code.
- **NFR-3**: Logging to stdout/file with structured messages (timestamp, market, stage, status).
- **NFR-4**: All dependencies must be free/open-source. APIs must have a free tier sufficient for the universe size.
- **NFR-5**: Single-process execution; no distributed coordination needed.
- **NFR-6**: Cron-compatible: each run is a single CLI invocation with exit code 0 on success.

## Success Criteria

1. Full 1-year backfill completes for both KRX and US without manual intervention.
2. Daily incremental update runs unattended via cron for 7 consecutive days without failure.
3. DuckDB can query adjusted daily close for any instrument in the universe in < 1 second.
4. Instrument-level failures are quarantined without aborting the batch.
5. Raw and adjusted Parquet files are readable by any Parquet-compatible tool.

## Constraints

- Single maintainer: no operations team, no on-call.
- Free APIs only: KRX public data, Tiingo free tier.
- Local or single-server execution.
- Python ecosystem (assumed; aligns with DuckDB, Parquet, and data tooling).
- Tiingo free tier rate limits apply (~500 requests/hour for end-of-day; batch endpoints preferred).

## Risks / Open Questions

| # | Risk / Question | Mitigation / Default |
|---|---|---|
| R1 | Tiingo free tier may not cover full US universe (rate limits, symbol count). | Use batch endpoints where available. Paginate. Monitor rate limit headers. If universe exceeds free tier, prioritize by market cap or user-defined watchlist. |
| R2 | KRX public data access method is not fully defined (scraping vs. API vs. file download). | Research KRX data access during implementation. Default to `pykrx` library or official KRX file downloads. |
| R3 | Adjusted price calculations for KRX may be inaccurate if provider-adjusted values are missing. | In v1, skip adjusted series for instruments where provider does not supply them; log warning. |
| R4 | Delisting detection reliability varies by source. | Best-effort detection. Log when instruments disappear from active listings. |
| R5 | Rebalancing frequency is not fixed; data granularity must support arbitrary rebalancing. | Daily data is sufficient for any rebalancing period >= 1 day. No action needed. |
| R6 | Trading halt data may not be reliably available from all sources. | Best-effort. If source does not provide halt status, mark as unknown. |
| R7 | Schema evolution as new fields or markets are added. | Use Parquet (schema-aware). Add columns as needed; old files remain readable. |

## v1 Decisions Already Made

| Decision | Rationale |
|---|---|
| Store raw + adjusted data separately | Enables debugging and future recalculation. |
| US default backtest series = Tiingo dividend-adjusted close | Most common adjustment for equity backtesting. |
| KRX adjusted prices = provider-supplied values | Self-calculation requires verified corporate action history; defer to v2. |
| Overwrite ticker/name to current | Full ticker history tracking is complex; not needed for v1 backtesting. |
| Delisted instruments excluded from active universe | Prevents lookahead bias in strategy selection. Metadata preserved for survivorship analysis. |
| Overwrite on provider data change | Simplest policy; no versioning overhead. |
| 1-year backfill only | Limits initial data volume; sufficient for strategy development. |
| Instrument-level quarantine on failure | Maximizes data availability per batch. |
| Parquet + DuckDB | Zero-infrastructure analytical stack; fast, local, free. |
| Cron-based scheduling | Simplest scheduler for single-server, single-maintainer operation. |

## Future Extensions

- Extend backfill to full available history.
- Add fallback data sources (e.g., Yahoo Finance, FRED for macro).
- Ticker/name change history tracking.
- Self-calculated adjusted prices for KRX.
- Fundamental data (earnings, financials).
- Additional markets (Japan, Europe).
- Data quality dashboards.
- Webhook or notification on pipeline failure.
- Restatement versioning (keep history of provider corrections).
