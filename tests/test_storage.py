"""Tests for Parquet storage."""

from datetime import date

import pandas as pd
import pytest

from getstock.storage import (
    dividends_path,
    instruments_path,
    ohlcv_path,
    quarantine_path,
    read_parquet,
    run_manifest_path,
    splits_path,
    universe_path,
    write_ohlcv,
    write_parquet,
    write_run_manifest,
)


def test_path_builders(tmp_data_dir):
    d = date(2026, 3, 15)
    assert str(ohlcv_path(tmp_data_dir, "krx", d)).endswith("ohlcv/krx/2026/2026-03-15.parquet")
    assert str(dividends_path(tmp_data_dir, "us", d)).endswith("dividends/us/2026/2026-03-15.parquet")
    assert str(splits_path(tmp_data_dir, "krx", d)).endswith("splits/krx/2026/2026-03-15.parquet")
    assert str(universe_path(tmp_data_dir, "krx", d)).endswith("universe/krx/2026-03-15.parquet")
    assert str(instruments_path(tmp_data_dir, "krx")).endswith("meta/instruments_krx.parquet")
    assert str(quarantine_path(tmp_data_dir, "us", d)).endswith("meta/quarantine/2026-03-15_us.parquet")
    assert str(run_manifest_path(tmp_data_dir, "krx", d)).endswith("meta/runs/2026-03-15_krx.json")


def test_write_read_roundtrip(tmp_data_dir, sample_ohlcv_df):
    path = ohlcv_path(tmp_data_dir, "krx", date(2026, 3, 15))
    from getstock.schema import OHLCV_SCHEMA
    write_parquet(sample_ohlcv_df, path, schema=OHLCV_SCHEMA)
    assert path.exists()

    df = read_parquet(path)
    assert len(df) == len(sample_ohlcv_df)
    assert list(df.columns) == list(sample_ohlcv_df.columns)


def test_write_ohlcv_sorted(tmp_data_dir, sample_ohlcv_df):
    d = date(2026, 3, 15)
    write_ohlcv(sample_ohlcv_df, "krx", d, tmp_data_dir)
    path = ohlcv_path(tmp_data_dir, "krx", d)
    df = read_parquet(path)
    assert list(df["source_id"]) == sorted(df["source_id"])


def test_atomic_write_no_tmp_residue(tmp_data_dir, sample_ohlcv_df):
    path = ohlcv_path(tmp_data_dir, "krx", date(2026, 3, 15))
    from getstock.schema import OHLCV_SCHEMA
    write_parquet(sample_ohlcv_df, path, schema=OHLCV_SCHEMA)
    tmp_path = path.with_suffix(".parquet.tmp")
    assert not tmp_path.exists()
    assert path.exists()


def test_write_run_manifest(tmp_data_dir):
    d = date(2026, 3, 15)
    summary = {"market": "krx", "date": "2026-03-15", "status": "success", "universe_size": 100}
    path = write_run_manifest(summary, "krx", d, tmp_data_dir)
    assert path.exists()
    import json
    with open(path) as f:
        loaded = json.load(f)
    assert loaded["market"] == "krx"
    assert loaded["status"] == "success"


def test_read_nonexistent_returns_empty(tmp_data_dir):
    df = read_parquet(tmp_data_dir / "nonexistent.parquet")
    assert df.empty
