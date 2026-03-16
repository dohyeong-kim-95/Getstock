"""KRX data fetcher via pykrx."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

import pandas as pd

from getstock.schema import OHLCV_COLUMNS

logger = logging.getLogger(__name__)

_BULK_DELAY = 1.0  # seconds between bulk per-date calls
_TICKER_DELAY = 0.5  # seconds between per-ticker calls


def fetch_ohlcv_krx(target_date: date) -> pd.DataFrame:
    """Fetch raw OHLCV for all KRX tickers on a single date via bulk API."""
    from pykrx import stock

    date_str = target_date.strftime("%Y%m%d")
    logger.info(f"Fetching KRX bulk OHLCV for {target_date.isoformat()}")

    df = stock.get_market_ohlcv(date_str, market="ALL")
    if df.empty:
        logger.warning(f"No KRX OHLCV data returned for {target_date.isoformat()}")
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    now = datetime.now(timezone.utc)
    df = df.reset_index()
    df = df.rename(columns={
        "티커": "source_id",
        "시가": "open",
        "고가": "high",
        "저가": "low",
        "종가": "close",
        "거래량": "volume",
    })

    # pykrx index column name may vary; handle both cases
    if "source_id" not in df.columns and df.columns[0] != "source_id":
        df = df.rename(columns={df.columns[0]: "source_id"})

    df["source_id"] = df["source_id"].astype(str)
    df["ticker"] = df["source_id"]
    df["date"] = target_date
    df["adj_open"] = None
    df["adj_high"] = None
    df["adj_low"] = None
    df["adj_close"] = None
    df["adj_volume"] = None
    df["market"] = "krx"
    df["source"] = "pykrx"
    df["fetched_at"] = now

    return df[OHLCV_COLUMNS]


def fetch_adjusted_krx(
    target_date: date, tickers: list[str]
) -> tuple[pd.DataFrame, list[dict]]:
    """Fetch adjusted prices per ticker. Returns (adjusted_df, errors)."""
    from pykrx import stock

    date_str = target_date.strftime("%Y%m%d")
    rows = []
    errors = []

    for i, ticker in enumerate(tickers):
        try:
            adj = stock.get_market_ohlcv_by_date(
                date_str, date_str, ticker, adjusted=True
            )
            if not adj.empty:
                row = adj.iloc[0]
                rows.append({
                    "source_id": ticker,
                    "date": target_date,
                    "adj_open": row.get("시가"),
                    "adj_high": row.get("고가"),
                    "adj_low": row.get("저가"),
                    "adj_close": row.get("종가"),
                    "adj_volume": row.get("거래량"),
                })
        except Exception as e:
            logger.warning(f"Failed to fetch adjusted prices for {ticker}: {e}")
            errors.append({
                "source_id": ticker,
                "ticker": ticker,
                "market": "krx",
                "date": target_date,
                "stage": "ingestion",
                "error_type": "api_error",
                "error_detail": str(e),
                "created_at": datetime.now(timezone.utc),
            })

        if i < len(tickers) - 1:
            time.sleep(_TICKER_DELAY)

    adj_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["source_id", "date", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"]
    )
    return adj_df, errors


def merge_raw_adjusted(raw_df: pd.DataFrame, adj_df: pd.DataFrame) -> pd.DataFrame:
    """Left-join raw OHLCV with adjusted prices on (source_id, date)."""
    if adj_df.empty:
        return raw_df

    adj_cols = ["source_id", "date", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"]
    adj_df = adj_df[adj_cols]

    merged = raw_df.drop(columns=["adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"])
    merged = merged.merge(adj_df, on=["source_id", "date"], how="left")
    return merged[OHLCV_COLUMNS]


def fetch_dividends_krx(target_date: date) -> pd.DataFrame:
    """Best-effort dividend fetch for KRX. Returns empty DataFrame if unavailable."""
    logger.info(f"KRX dividend data is best-effort in v1. Returning empty for {target_date}")
    from getstock.schema import DIVIDENDS_COLUMNS
    return pd.DataFrame(columns=DIVIDENDS_COLUMNS)


def fetch_splits_krx(target_date: date) -> pd.DataFrame:
    """Best-effort split fetch for KRX. Returns empty DataFrame if unavailable."""
    logger.info(f"KRX split data is best-effort in v1. Returning empty for {target_date}")
    from getstock.schema import SPLITS_COLUMNS
    return pd.DataFrame(columns=SPLITS_COLUMNS)
