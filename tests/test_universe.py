"""Tests for universe management and delisting detection."""

from datetime import date

import pandas as pd
import pytest

from getstock.schema import INSTRUMENTS_COLUMNS
from getstock.universe import detect_delistings


def _make_instruments(ids, active=True, today=date(2026, 3, 15)):
    rows = []
    for sid in ids:
        rows.append({
            "source_id": sid,
            "ticker": sid,
            "name": f"Company {sid}",
            "market": "krx",
            "asset_type": "stock",
            "exchange": "KOSPI",
            "currency": "KRW",
            "is_active": active,
            "delisted_date": None,
            "first_seen": today,
            "last_updated": today,
        })
    return pd.DataFrame(rows, columns=INSTRUMENTS_COLUMNS)


def test_first_run_all_new():
    new = _make_instruments(["A", "B", "C"])
    result = detect_delistings(new, None, today=date(2026, 3, 15))
    assert len(result) == 3
    assert all(result["is_active"] == True)


def test_normal_delisting():
    stored = _make_instruments(["A", "B", "C"])
    new = _make_instruments(["A", "B"])  # C disappeared
    result = detect_delistings(new, stored, safety_threshold=0.5, today=date(2026, 3, 16))
    c_row = result[result["source_id"] == "C"].iloc[0]
    assert c_row["is_active"] == False
    assert c_row["delisted_date"] == date(2026, 3, 16)


def test_safety_threshold_exceeded():
    stored = _make_instruments(["A", "B", "C", "D", "E"])
    new = _make_instruments(["A"])  # 80% disappeared > 20% threshold
    result = detect_delistings(new, stored, safety_threshold=0.20, today=date(2026, 3, 16))
    # All should remain active (safety threshold triggered)
    assert all(result["is_active"] == True)


def test_relisting():
    stored = _make_instruments(["A", "B"])
    stored.loc[stored["source_id"] == "B", "is_active"] = False
    stored.loc[stored["source_id"] == "B", "delisted_date"] = date(2026, 3, 10)
    new = _make_instruments(["A", "B"])  # B reappears
    result = detect_delistings(new, stored, today=date(2026, 3, 16))
    b_row = result[result["source_id"] == "B"].iloc[0]
    assert b_row["is_active"] == True
    assert pd.isna(b_row["delisted_date"]) or b_row["delisted_date"] is None


def test_new_instrument_added():
    stored = _make_instruments(["A", "B"])
    new = _make_instruments(["A", "B", "C"])
    result = detect_delistings(new, stored, today=date(2026, 3, 16))
    assert len(result) == 3
    c_row = result[result["source_id"] == "C"].iloc[0]
    assert c_row["first_seen"] == date(2026, 3, 16)
