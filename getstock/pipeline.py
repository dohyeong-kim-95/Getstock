"""Pipeline orchestration: ties ingestion → normalize → validate → store."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import exchange_calendars as xcals
import pandas as pd

from getstock.config import AppConfig
from getstock.normalize import normalize_ohlcv
from getstock.quarantine import merge_quarantine
from getstock.storage import (
    read_parquet,
    instruments_path,
    write_instruments,
    write_ohlcv,
    write_quarantine,
    write_run_manifest,
    write_universe_snapshot,
)
from getstock.validate import validate_ohlcv

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    market: str
    date: date
    status: str = "success"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    duration_seconds: float = 0
    universe_size: int = 0
    fetched_count: int = 0
    quarantined_count: int = 0
    skipped_count: int = 0
    files_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "date": self.date.isoformat(),
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.duration_seconds,
            "universe_size": self.universe_size,
            "fetched_count": self.fetched_count,
            "quarantined_count": self.quarantined_count,
            "skipped_count": self.skipped_count,
            "files_written": self.files_written,
            "errors": self.errors,
        }


def run_daily(
    market: str, target_date: date, config: AppConfig,
    fetch_adjusted: bool = False,
) -> RunSummary:
    """Run the full daily pipeline for a market.

    Args:
        fetch_adjusted: If True (backfill mode), fetch per-ticker adjusted
            prices for KRX. If False (daily mode), set adj_* = raw values.
            Has no effect on US market (Tiingo always provides adjusted).
    """
    summary = RunSummary(market=market, date=target_date)
    start = time.time()

    try:
        if market == "krx":
            _run_krx(target_date, config, summary, fetch_adjusted=fetch_adjusted)
        elif market == "us":
            _run_us(target_date, config, summary)
        else:
            raise ValueError(f"Unknown market: {market}")
    except Exception as e:
        logger.error(f"Pipeline failed for {market} on {target_date}: {e}", exc_info=True)
        summary.status = "failed"
        summary.errors.append(str(e))

    summary.finished_at = datetime.now(timezone.utc)
    summary.duration_seconds = round(time.time() - start, 1)

    # Write run manifest
    write_run_manifest(summary.to_dict(), market, target_date, config.data_dir)
    summary.files_written.append("run_manifest")

    # Log summary
    logger.info(
        f"RUN SUMMARY | market={market} | date={target_date} | "
        f"universe={summary.universe_size} | fetched={summary.fetched_count} | "
        f"quarantined={summary.quarantined_count} | skipped={summary.skipped_count} | "
        f"duration={summary.duration_seconds}s | status={summary.status}"
    )

    return summary


def _run_krx(
    target_date: date, config: AppConfig, summary: RunSummary,
    fetch_adjusted: bool = False,
) -> None:
    from getstock.sources.krx import (
        fetch_adjusted_krx,
        fetch_ohlcv_krx,
        fill_adjusted_from_raw,
        merge_raw_adjusted,
    )
    from getstock.universe import detect_delistings, fetch_universe_krx

    data_dir = config.data_dir

    # 1. Universe
    new_universe = fetch_universe_krx(target_date)
    summary.universe_size = len(new_universe)

    stored_path = instruments_path(data_dir, "krx")
    stored = read_parquet(stored_path) if stored_path.exists() else None

    instruments = detect_delistings(
        new_universe, stored,
        safety_threshold=config.delisting_safety_threshold,
        today=target_date,
    )
    write_instruments(instruments, "krx", data_dir)
    summary.files_written.append("instruments")

    write_universe_snapshot(new_universe, "krx", target_date, data_dir)
    summary.files_written.append("universe")

    # 2. OHLCV
    raw_df = fetch_ohlcv_krx(target_date)
    summary.fetched_count = len(raw_df)

    ingestion_errors: list[dict] = []
    if fetch_adjusted:
        # Backfill mode: per-ticker adjusted price fetch (slow, ~0.5s per ticker)
        active_tickers = instruments[instruments["is_active"] == True]["source_id"].tolist()
        adj_df, ingestion_errors = fetch_adjusted_krx(target_date, active_tickers)
        merged = merge_raw_adjusted(raw_df, adj_df)
    else:
        # Daily mode: set adj_* = raw values (no per-ticker HTTP calls).
        # KRX bulk API does not support adjusted prices. For daily runs,
        # raw and adjusted diverge only on ex-dividend/split dates, which
        # are infrequent. Periodic re-backfill refreshes adjusted values.
        merged = fill_adjusted_from_raw(raw_df)

    # 3. Normalize
    normalized = normalize_ohlcv(merged, "pykrx")

    # 4. Validate
    valid_df, quarantine_df = validate_ohlcv(normalized, target_date, "krx")
    summary.quarantined_count = len(quarantine_df)

    # 5. Write OHLCV
    write_ohlcv(valid_df, "krx", target_date, data_dir)
    summary.files_written.append("ohlcv")

    # 6. Quarantine
    combined_q = merge_quarantine(ingestion_errors, quarantine_df)
    if not combined_q.empty:
        write_quarantine(combined_q, "krx", target_date, data_dir)
        summary.files_written.append("quarantine")


def _run_us(target_date: date, config: AppConfig, summary: RunSummary) -> None:
    from getstock.sources.tiingo import (
        fetch_ohlcv_batch_tiingo,
        fetch_universe_tiingo,
    )
    from getstock.universe import detect_delistings

    data_dir = config.data_dir
    market_config = config.markets["us"]

    # 1. Universe
    new_universe = fetch_universe_tiingo(
        api_key=config.tiingo_api_key,
        universe_filter=market_config.universe_filter,
        watchlist=market_config.watchlist,
    )
    summary.universe_size = len(new_universe)

    stored_path = instruments_path(data_dir, "us")
    stored = read_parquet(stored_path) if stored_path.exists() else None

    instruments = detect_delistings(
        new_universe, stored,
        safety_threshold=config.delisting_safety_threshold,
        today=target_date,
    )
    write_instruments(instruments, "us", data_dir)
    summary.files_written.append("instruments")

    write_universe_snapshot(new_universe, "us", target_date, data_dir)
    summary.files_written.append("universe")

    # 2. OHLCV
    active_tickers = instruments[instruments["is_active"] == True]["source_id"].tolist()
    ohlcv_df, ingestion_errors = fetch_ohlcv_batch_tiingo(
        active_tickers, target_date, config.tiingo_api_key
    )
    summary.fetched_count = len(ohlcv_df)

    # 3. Normalize
    normalized = normalize_ohlcv(ohlcv_df, "tiingo")

    # 4. Validate
    valid_df, quarantine_df = validate_ohlcv(normalized, target_date, "us")
    summary.quarantined_count = len(quarantine_df)

    # 5. Write OHLCV
    write_ohlcv(valid_df, "us", target_date, data_dir)
    summary.files_written.append("ohlcv")

    # 6. Quarantine
    combined_q = merge_quarantine(ingestion_errors, quarantine_df)
    if not combined_q.empty:
        write_quarantine(combined_q, "us", target_date, data_dir)
        summary.files_written.append("quarantine")


def run_backfill(
    market: str, start_date: date, end_date: date, config: AppConfig, dry_run: bool = False
) -> None:
    """Run pipeline for each trading day in the date range."""
    market_config = config.markets[market]
    cal = xcals.get_calendar(market_config.exchange_calendar)

    sessions = cal.sessions_in_range(
        pd.Timestamp(start_date), pd.Timestamp(end_date)
    )
    total = len(sessions)
    logger.info(f"Backfill: {total} trading days from {start_date} to {end_date}")

    for i, session in enumerate(sessions, 1):
        d = session.date()
        logger.info(f"Processing date {i}/{total}: {d}")

        if dry_run:
            logger.info(f"[DRY RUN] Would fetch {market} data for {d}")
            continue

        try:
            run_daily(market, d, config, fetch_adjusted=True)
        except Exception as e:
            logger.error(f"Failed for {d}: {e}", exc_info=True)
            continue
