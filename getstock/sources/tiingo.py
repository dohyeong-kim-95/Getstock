"""Tiingo data fetcher via REST API."""

from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import date, datetime, timezone

import pandas as pd
import requests

from getstock.schema import DIVIDENDS_COLUMNS, OHLCV_COLUMNS, SPLITS_COLUMNS

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.tiingo.com"
_UNIVERSE_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
_DEFAULT_RATE_LIMIT_DELAY = 0.2  # seconds between requests (5 req/sec)
_RETRY_AFTER_DEFAULT = 60


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }


def fetch_universe_tiingo(
    api_key: str, universe_filter: str = "all", watchlist: list[str] | None = None
) -> pd.DataFrame:
    """Download and filter Tiingo supported tickers."""
    logger.info("Downloading Tiingo supported tickers")

    resp = requests.get(_UNIVERSE_URL, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        csv_name = z.namelist()[0]
        with z.open(csv_name) as f:
            df = pd.read_csv(f)

    # Filter to stocks and ETFs, USD, active
    df = df[df["assetType"].isin(["Stock", "ETF"])]
    df = df[df["priceCurrency"] == "USD"]
    df = df[df["endDate"].isna() | (pd.to_datetime(df["endDate"]) >= datetime.now())]

    # Apply universe filter
    if universe_filter == "watchlist" and watchlist:
        df = df[df["ticker"].isin(watchlist)]
    elif universe_filter not in ("all", "watchlist") and universe_filter:
        # Treat as CSV path
        filter_df = pd.read_csv(universe_filter)
        filter_tickers = filter_df.iloc[:, 0].tolist()
        df = df[df["ticker"].isin(filter_tickers)]

    now = date.today()
    result = pd.DataFrame({
        "source_id": df["ticker"].astype(str),
        "ticker": df["ticker"].astype(str),
        "name": df.get("name", ""),
        "market": "us",
        "asset_type": df["assetType"].str.lower(),
        "exchange": df.get("exchange", ""),
        "currency": "USD",
        "is_active": True,
        "delisted_date": pd.NaT,
        "first_seen": now,
        "last_updated": now,
    })
    logger.info(f"Tiingo universe: {len(result)} instruments after filtering")
    return result


def fetch_ohlcv_tiingo(
    ticker: str, start_date: date, end_date: date, api_key: str
) -> pd.DataFrame:
    """Fetch OHLCV for a single ticker from Tiingo."""
    url = f"{_BASE_URL}/tiingo/daily/{ticker}/prices"
    params = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
    }

    resp = requests.get(url, headers=_headers(api_key), params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    now = datetime.now(timezone.utc)
    rows = []
    for item in data:
        rows.append({
            "source_id": ticker,
            "ticker": ticker,
            "date": pd.Timestamp(item["date"]).date(),
            "open": item["open"],
            "high": item["high"],
            "low": item["low"],
            "close": item["close"],
            "volume": item["volume"],
            "adj_open": item.get("adjOpen"),
            "adj_high": item.get("adjHigh"),
            "adj_low": item.get("adjLow"),
            "adj_close": item.get("adjClose"),
            "adj_volume": item.get("adjVolume"),
            "market": "us",
            "source": "tiingo",
            "fetched_at": now,
        })

    return pd.DataFrame(rows)[OHLCV_COLUMNS]


def fetch_ohlcv_batch_tiingo(
    tickers: list[str], target_date: date, api_key: str
) -> tuple[pd.DataFrame, list[dict]]:
    """Fetch OHLCV for multiple tickers with rate limiting. Returns (df, errors)."""
    all_dfs = []
    errors = []

    for i, ticker in enumerate(tickers):
        try:
            df = fetch_ohlcv_tiingo(ticker, target_date, target_date, api_key)
            if not df.empty:
                all_dfs.append(df)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                retry_after = int(
                    e.response.headers.get("Retry-After", _RETRY_AFTER_DEFAULT)
                )
                logger.warning(f"Rate limited. Waiting {retry_after}s")
                time.sleep(retry_after)
                # Retry once
                try:
                    df = fetch_ohlcv_tiingo(ticker, target_date, target_date, api_key)
                    if not df.empty:
                        all_dfs.append(df)
                    continue
                except Exception as e2:
                    logger.warning(f"Retry failed for {ticker}: {e2}")
                    errors.append(_make_error(ticker, target_date, e2))
                    continue

            logger.warning(f"HTTP error for {ticker}: {e}")
            errors.append(_make_error(ticker, target_date, e))
        except Exception as e:
            logger.warning(f"Failed to fetch {ticker}: {e}")
            errors.append(_make_error(ticker, target_date, e))

        if i < len(tickers) - 1:
            time.sleep(_DEFAULT_RATE_LIMIT_DELAY)

        if (i + 1) % 100 == 0:
            logger.info(f"Fetched {i + 1}/{len(tickers)} tickers")

    result = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame(columns=OHLCV_COLUMNS)
    return result, errors


def _make_error(ticker: str, target_date: date, exc: Exception) -> dict:
    return {
        "source_id": ticker,
        "ticker": ticker,
        "market": "us",
        "date": target_date,
        "stage": "ingestion",
        "error_type": "api_error",
        "error_detail": str(exc),
        "created_at": datetime.now(timezone.utc),
    }


def fetch_dividends_tiingo(target_date: date) -> pd.DataFrame:
    """Dividends not independently tracked in v1. Returns empty DataFrame."""
    logger.info("Tiingo dividends derived from adjusted prices in v1. Returning empty.")
    return pd.DataFrame(columns=DIVIDENDS_COLUMNS)


def fetch_splits_tiingo(target_date: date) -> pd.DataFrame:
    """Splits not independently tracked in v1. Returns empty DataFrame."""
    logger.info("Tiingo splits derived from adjusted prices in v1. Returning empty.")
    return pd.DataFrame(columns=SPLITS_COLUMNS)
