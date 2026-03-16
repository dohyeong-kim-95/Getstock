"""Universe management and delisting detection."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from getstock.schema import INSTRUMENTS_COLUMNS

logger = logging.getLogger(__name__)


def fetch_universe_krx(target_date: date) -> pd.DataFrame:
    """Fetch KRX universe via pykrx bulk API (single HTTP call per market)."""
    from pykrx.website.krx.market.wrap import get_market_ticker_and_name

    date_str = target_date.strftime("%Y%m%d")
    tickers = []

    for market_name in ["KOSPI", "KOSDAQ"]:
        # Bulk call: returns Series with ticker as index, name as value.
        # One HTTP request per market, not per ticker.
        names_series = get_market_ticker_and_name(date_str, market_name)
        for ticker_code, name in names_series.items():
            tickers.append({
                "source_id": ticker_code,
                "ticker": ticker_code,
                "name": name,
                "market": "krx",
                "asset_type": "stock",
                "exchange": market_name,
                "currency": "KRW",
                "is_active": True,
                "delisted_date": None,
                "first_seen": target_date,
                "last_updated": target_date,
            })

    df = pd.DataFrame(tickers, columns=INSTRUMENTS_COLUMNS)
    logger.info(f"KRX universe: {len(df)} instruments")
    return df


def detect_delistings(
    new_universe_df: pd.DataFrame,
    stored_instruments_df: pd.DataFrame | None,
    safety_threshold: float = 0.20,
    today: date | None = None,
) -> pd.DataFrame:
    """Compare new universe against stored instruments and detect delistings."""
    if today is None:
        today = date.today()

    if stored_instruments_df is None or stored_instruments_df.empty:
        # First run: all instruments are new
        new_universe_df = new_universe_df.copy()
        new_universe_df["first_seen"] = today
        new_universe_df["last_updated"] = today
        return new_universe_df

    stored = stored_instruments_df.copy()
    new_ids = set(new_universe_df["source_id"].astype(str))
    active_stored = stored[stored["is_active"] == True]
    active_ids = set(active_stored["source_id"].astype(str))

    missing_ids = active_ids - new_ids
    missing_ratio = len(missing_ids) / len(active_ids) if active_ids else 0

    if missing_ratio > safety_threshold:
        logger.error(
            f"Safety threshold exceeded: {len(missing_ids)}/{len(active_ids)} "
            f"({missing_ratio:.1%}) instruments disappeared. Skipping delisting detection."
        )
        # Still update ticker/name for existing instruments
        stored["last_updated"] = today
        return stored

    # Mark missing instruments as delisted
    if missing_ids:
        logger.info(f"Detected {len(missing_ids)} delistings")
        mask = stored["source_id"].isin(missing_ids)
        stored.loc[mask, "is_active"] = False
        stored.loc[mask, "delisted_date"] = today

    # Handle re-listing: previously delisted instruments that reappear
    delisted = stored[stored["is_active"] == False]
    delisted_ids = set(delisted["source_id"].astype(str))
    relisted_ids = delisted_ids & new_ids
    if relisted_ids:
        logger.warning(f"Re-listing detected for {len(relisted_ids)} instruments")
        mask = stored["source_id"].isin(relisted_ids)
        stored.loc[mask, "is_active"] = True
        stored.loc[mask, "delisted_date"] = None

    # Add new instruments
    existing_ids = set(stored["source_id"].astype(str))
    new_only = new_universe_df[~new_universe_df["source_id"].isin(existing_ids)].copy()
    if not new_only.empty:
        new_only["first_seen"] = today
        new_only["last_updated"] = today
        logger.info(f"New instruments: {len(new_only)}")
        stored = pd.concat([stored, new_only], ignore_index=True)

    # Update ticker/name/last_updated for all active instruments from new universe
    new_lookup = new_universe_df.set_index("source_id")[["ticker", "name", "exchange"]].to_dict("index")
    for idx in stored.index:
        sid = stored.at[idx, "source_id"]
        if sid in new_lookup:
            stored.at[idx, "ticker"] = new_lookup[sid]["ticker"]
            stored.at[idx, "name"] = new_lookup[sid]["name"]
            stored.at[idx, "exchange"] = new_lookup[sid]["exchange"]
            stored.at[idx, "last_updated"] = today

    return stored[INSTRUMENTS_COLUMNS]
