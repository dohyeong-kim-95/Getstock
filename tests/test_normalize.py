"""Tests for normalization."""

from datetime import date, datetime, timezone

import pandas as pd

from getstock.normalize import normalize_ohlcv
from getstock.schema import OHLCV_COLUMNS


def test_normalize_ohlcv_columns():
    now = datetime.now(timezone.utc)
    df = pd.DataFrame([{
        "source_id": "005930",
        "ticker": "005930",
        "date": "2026-03-15",
        "open": "70000",
        "high": "71000",
        "low": "69000",
        "close": "70500",
        "volume": "10000000",
        "adj_open": None,
        "adj_high": None,
        "adj_low": None,
        "adj_close": None,
        "adj_volume": None,
        "market": "krx",
        "source": "pykrx",
        "fetched_at": now,
    }])
    result = normalize_ohlcv(df, "pykrx")
    assert list(result.columns) == OHLCV_COLUMNS
    assert result.iloc[0]["open"] == 70000.0
    assert result.iloc[0]["date"] == date(2026, 3, 15)


def test_normalize_ohlcv_empty():
    df = pd.DataFrame(columns=OHLCV_COLUMNS)
    result = normalize_ohlcv(df, "pykrx")
    assert result.empty
    assert list(result.columns) == OHLCV_COLUMNS
