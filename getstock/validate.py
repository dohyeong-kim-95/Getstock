"""Validation rules for OHLCV data (V1-V8)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import pandas as pd

from getstock.schema import QUARANTINE_COLUMNS

logger = logging.getLogger(__name__)


def validate_ohlcv(
    df: pd.DataFrame, target_date: date, market: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply validation rules. Returns (valid_df, quarantine_df)."""
    if df.empty:
        return df, pd.DataFrame(columns=QUARANTINE_COLUMNS)

    df = df.copy()
    quarantine_rows = []

    # V1: Positive prices
    bad_prices = (df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0) | (df["close"] <= 0)
    for idx in df[bad_prices].index:
        row = df.loc[idx]
        quarantine_rows.append(_q_entry(row, market, "validation_failed", "V1: Non-positive price"))

    # V2: high >= low
    bad_hl = df["high"] < df["low"]
    for idx in df[bad_hl].index:
        row = df.loc[idx]
        quarantine_rows.append(_q_entry(row, market, "validation_failed", "V2: high < low"))

    # V3: high >= open and high >= close
    bad_h = (df["high"] < df["open"]) | (df["high"] < df["close"])
    for idx in df[bad_h].index:
        row = df.loc[idx]
        quarantine_rows.append(_q_entry(row, market, "validation_failed", "V3: high < open or close"))

    # V4: low <= open and low <= close
    bad_l = (df["low"] > df["open"]) | (df["low"] > df["close"])
    for idx in df[bad_l].index:
        row = df.loc[idx]
        quarantine_rows.append(_q_entry(row, market, "validation_failed", "V4: low > open or close"))

    # V5: Non-negative volume
    bad_vol = df["volume"] < 0
    for idx in df[bad_vol].index:
        row = df.loc[idx]
        quarantine_rows.append(_q_entry(row, market, "validation_failed", "V5: Negative volume"))

    # Combine all quarantine masks
    quarantine_mask = bad_prices | bad_hl | bad_h | bad_l | bad_vol

    # V6: Date matches target (warning only)
    if "date" in df.columns:
        wrong_date = df["date"] != target_date
        if wrong_date.any():
            count = wrong_date.sum()
            logger.warning(f"V6: {count} rows have date != target {target_date}")

    # V7: Unique (source_id, date) - keep last, warn
    dupes = df.duplicated(subset=["source_id", "date"], keep="last")
    if dupes.any():
        count = dupes.sum()
        logger.warning(f"V7: {count} duplicate (source_id, date) rows found. Keeping last.")
        df = df[~dupes]
        # Recompute quarantine_mask after dropping dupes
        quarantine_mask = quarantine_mask.reindex(df.index, fill_value=False)

    # V8: Price spike > 50% (warning only, no quarantine)
    # Skipped for single-date runs (no previous close available)

    # Validate adjusted prices if present
    adj_close_present = df["adj_close"].notna()
    if adj_close_present.any():
        adj_bad = adj_close_present & (df["adj_close"] <= 0)
        for idx in df[adj_bad].index:
            row = df.loc[idx]
            quarantine_rows.append(_q_entry(row, market, "validation_failed", "Adj: adj_close <= 0"))
        quarantine_mask = quarantine_mask | adj_bad

        adj_hl = adj_close_present & df["adj_high"].notna() & df["adj_low"].notna() & (df["adj_high"] < df["adj_low"])
        for idx in df[adj_hl].index:
            row = df.loc[idx]
            quarantine_rows.append(_q_entry(row, market, "validation_failed", "Adj: adj_high < adj_low"))
        quarantine_mask = quarantine_mask | adj_hl

    valid_df = df[~quarantine_mask].copy()
    quarantine_df = pd.DataFrame(quarantine_rows, columns=QUARANTINE_COLUMNS) if quarantine_rows else pd.DataFrame(columns=QUARANTINE_COLUMNS)

    if not quarantine_df.empty:
        # Deduplicate quarantine entries per source_id
        quarantine_df = quarantine_df.drop_duplicates(subset=["source_id", "date"], keep="first")

    n_quarantined = len(df) - len(valid_df)
    if n_quarantined:
        logger.warning(f"Quarantined {n_quarantined} instrument-dates")

    return valid_df, quarantine_df


def _q_entry(row: pd.Series, market: str, error_type: str, detail: str) -> dict:
    return {
        "source_id": row.get("source_id", ""),
        "ticker": row.get("ticker", ""),
        "market": market,
        "date": row.get("date"),
        "stage": "validation",
        "error_type": error_type,
        "error_detail": detail,
        "created_at": datetime.now(timezone.utc),
    }
