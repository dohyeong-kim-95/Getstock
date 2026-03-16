"""Tests for KRX fetcher (mocked pykrx)."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from getstock.sources.krx import fetch_ohlcv_krx, merge_raw_adjusted


@patch("pykrx.stock.get_market_ohlcv")
def test_fetch_ohlcv_krx_basic(mock_get_ohlcv):
    # Mock pykrx response
    mock_df = pd.DataFrame({
        "시가": [70000, 150000],
        "고가": [71000, 152000],
        "저가": [69000, 148000],
        "종가": [70500, 151000],
        "거래량": [10000000, 5000000],
    }, index=["005930", "000660"])
    mock_get_ohlcv.return_value = mock_df

    result = fetch_ohlcv_krx(date(2026, 3, 15))
    assert len(result) == 2
    assert "source_id" in result.columns
    assert result.iloc[0]["market"] == "krx"


def test_merge_raw_adjusted():
    raw = pd.DataFrame({
        "source_id": ["A", "B"],
        "ticker": ["A", "B"],
        "date": [date(2026, 3, 15)] * 2,
        "open": [100, 200],
        "high": [110, 210],
        "low": [90, 190],
        "close": [105, 205],
        "volume": [1000, 2000],
        "adj_open": [None, None],
        "adj_high": [None, None],
        "adj_low": [None, None],
        "adj_close": [None, None],
        "adj_volume": [None, None],
        "market": ["krx", "krx"],
        "source": ["pykrx", "pykrx"],
        "fetched_at": [datetime.now(timezone.utc)] * 2,
    })
    adj = pd.DataFrame({
        "source_id": ["A"],
        "date": [date(2026, 3, 15)],
        "adj_open": [99.0],
        "adj_high": [109.0],
        "adj_low": [89.0],
        "adj_close": [104.0],
        "adj_volume": [1000],
    })
    result = merge_raw_adjusted(raw, adj)
    assert result.loc[result["source_id"] == "A", "adj_close"].iloc[0] == 104.0
    assert pd.isna(result.loc[result["source_id"] == "B", "adj_close"].iloc[0])
