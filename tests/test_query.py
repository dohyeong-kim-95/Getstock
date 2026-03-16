"""Tests for DuckDB query helpers."""

from datetime import date

import pytest

from getstock.query import get_ohlcv, get_universe
from getstock.storage import write_instruments, write_ohlcv


def test_get_ohlcv(tmp_data_dir, sample_ohlcv_df):
    d = date(2026, 3, 15)
    # Remove the bad row for this test
    good_df = sample_ohlcv_df[sample_ohlcv_df["source_id"] != "999999"].copy()
    write_ohlcv(good_df, "krx", d, tmp_data_dir)

    result = get_ohlcv("krx", tmp_data_dir, start_date=d, end_date=d)
    assert len(result) == 4


def test_get_ohlcv_filter_ticker(tmp_data_dir, sample_ohlcv_df):
    d = date(2026, 3, 15)
    good_df = sample_ohlcv_df[sample_ohlcv_df["source_id"] != "999999"].copy()
    write_ohlcv(good_df, "krx", d, tmp_data_dir)

    result = get_ohlcv("krx", tmp_data_dir, ticker="005930")
    assert len(result) == 1
    assert result.iloc[0]["ticker"] == "005930"


def test_get_ohlcv_no_data(tmp_data_dir):
    result = get_ohlcv("krx", tmp_data_dir)
    assert result.empty
