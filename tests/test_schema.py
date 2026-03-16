"""Tests for schema constants."""

from getstock.schema import (
    DIVIDENDS_COLUMNS,
    INSTRUMENTS_COLUMNS,
    OHLCV_COLUMNS,
    OHLCV_SCHEMA,
    QUARANTINE_COLUMNS,
    SPLITS_COLUMNS,
)


def test_ohlcv_columns_count():
    assert len(OHLCV_COLUMNS) == 16


def test_ohlcv_schema_matches_columns():
    schema_names = [field.name for field in OHLCV_SCHEMA]
    assert schema_names == OHLCV_COLUMNS


def test_instruments_has_source_id():
    assert "source_id" in INSTRUMENTS_COLUMNS
    assert "is_active" in INSTRUMENTS_COLUMNS


def test_quarantine_has_required_fields():
    assert "stage" in QUARANTINE_COLUMNS
    assert "error_type" in QUARANTINE_COLUMNS
    assert "error_detail" in QUARANTINE_COLUMNS


def test_dividends_columns():
    assert "ex_date" in DIVIDENDS_COLUMNS
    assert "amount" in DIVIDENDS_COLUMNS


def test_splits_columns():
    assert "ratio_from" in SPLITS_COLUMNS
    assert "ratio_to" in SPLITS_COLUMNS
