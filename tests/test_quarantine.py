"""Tests for quarantine handling."""

from datetime import date, datetime, timezone

import pandas as pd

from getstock.quarantine import merge_quarantine
from getstock.schema import QUARANTINE_COLUMNS


def test_merge_both_empty():
    empty = pd.DataFrame(columns=QUARANTINE_COLUMNS)
    result = merge_quarantine([], empty)
    assert result.empty
    assert list(result.columns) == QUARANTINE_COLUMNS


def test_merge_ingestion_errors_as_list():
    errors = [{
        "source_id": "X",
        "ticker": "X",
        "market": "krx",
        "date": date(2026, 3, 15),
        "stage": "ingestion",
        "error_type": "api_error",
        "error_detail": "timeout",
        "created_at": datetime.now(timezone.utc),
    }]
    empty = pd.DataFrame(columns=QUARANTINE_COLUMNS)
    result = merge_quarantine(errors, empty)
    assert len(result) == 1
    assert result.iloc[0]["stage"] == "ingestion"


def test_merge_validation_errors():
    empty_list = []
    val_errors = pd.DataFrame([{
        "source_id": "Y",
        "ticker": "Y",
        "market": "krx",
        "date": date(2026, 3, 15),
        "stage": "validation",
        "error_type": "validation_failed",
        "error_detail": "V1: Non-positive price",
        "created_at": datetime.now(timezone.utc),
    }], columns=QUARANTINE_COLUMNS)
    result = merge_quarantine(empty_list, val_errors)
    assert len(result) == 1


def test_merge_both():
    ing = [{
        "source_id": "A",
        "ticker": "A",
        "market": "krx",
        "date": date(2026, 3, 15),
        "stage": "ingestion",
        "error_type": "api_error",
        "error_detail": "timeout",
        "created_at": datetime.now(timezone.utc),
    }]
    val = pd.DataFrame([{
        "source_id": "B",
        "ticker": "B",
        "market": "krx",
        "date": date(2026, 3, 15),
        "stage": "validation",
        "error_type": "validation_failed",
        "error_detail": "V2",
        "created_at": datetime.now(timezone.utc),
    }], columns=QUARANTINE_COLUMNS)
    result = merge_quarantine(ing, val)
    assert len(result) == 2
