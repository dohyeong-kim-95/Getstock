"""Tests for validation rules V1-V8."""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from getstock.schema import OHLCV_COLUMNS
from getstock.validate import validate_ohlcv


def _make_row(overrides=None):
    row = {
        "source_id": "005930",
        "ticker": "005930",
        "date": date(2026, 3, 15),
        "open": 70000.0,
        "high": 71000.0,
        "low": 69000.0,
        "close": 70500.0,
        "volume": 10000000,
        "adj_open": None,
        "adj_high": None,
        "adj_low": None,
        "adj_close": None,
        "adj_volume": None,
        "market": "krx",
        "source": "pykrx",
        "fetched_at": datetime.now(timezone.utc),
    }
    if overrides:
        row.update(overrides)
    return row


def test_valid_row_passes():
    df = pd.DataFrame([_make_row()])
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 1
    assert len(q) == 0


def test_v1_negative_price_quarantined():
    df = pd.DataFrame([_make_row({"open": -100})])
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 0
    assert len(q) == 1
    assert "V1" in q.iloc[0]["error_detail"]


def test_v2_high_less_than_low():
    df = pd.DataFrame([_make_row({"high": 68000, "low": 69000})])
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 0
    assert len(q) == 1


def test_v3_high_less_than_open():
    df = pd.DataFrame([_make_row({"high": 69000, "open": 70000})])
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 0


def test_v4_low_greater_than_close():
    df = pd.DataFrame([_make_row({"low": 71000, "close": 70500})])
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 0


def test_v5_negative_volume():
    df = pd.DataFrame([_make_row({"volume": -1})])
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 0


def test_v7_duplicates_keep_last():
    r1 = _make_row({"close": 70000})
    r2 = _make_row({"close": 71000})
    df = pd.DataFrame([r1, r2])
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 1
    assert valid.iloc[0]["close"] == 71000


def test_valid_rows_not_affected_by_bad_row():
    good = _make_row({"source_id": "000660"})
    bad = _make_row({"source_id": "999999", "open": -100})
    df = pd.DataFrame([good, bad])
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 1
    assert valid.iloc[0]["source_id"] == "000660"
    assert len(q) == 1


def test_adj_close_negative_quarantined():
    df = pd.DataFrame([_make_row({"adj_close": -50.0, "adj_high": 100.0, "adj_low": 90.0})])
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 0


def test_empty_dataframe():
    df = pd.DataFrame(columns=OHLCV_COLUMNS)
    valid, q = validate_ohlcv(df, date(2026, 3, 15), "krx")
    assert len(valid) == 0
    assert len(q) == 0
