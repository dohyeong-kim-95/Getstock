"""Parquet storage with atomic writes and path builders."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from getstock.schema import (
    INSTRUMENTS_SCHEMA,
    OHLCV_SCHEMA,
    QUARANTINE_SCHEMA,
)


# --- Path builders ---

def ohlcv_path(data_dir: Path, market: str, d: date) -> Path:
    return data_dir / "ohlcv" / market / str(d.year) / f"{d.isoformat()}.parquet"


def dividends_path(data_dir: Path, market: str, d: date) -> Path:
    return data_dir / "dividends" / market / str(d.year) / f"{d.isoformat()}.parquet"


def splits_path(data_dir: Path, market: str, d: date) -> Path:
    return data_dir / "splits" / market / str(d.year) / f"{d.isoformat()}.parquet"


def universe_path(data_dir: Path, market: str, d: date) -> Path:
    return data_dir / "universe" / market / f"{d.isoformat()}.parquet"


def instruments_path(data_dir: Path, market: str) -> Path:
    return data_dir / "meta" / f"instruments_{market}.parquet"


def quarantine_path(data_dir: Path, market: str, d: date) -> Path:
    return data_dir / "meta" / "quarantine" / f"{d.isoformat()}_{market}.parquet"


def run_manifest_path(data_dir: Path, market: str, d: date) -> Path:
    return data_dir / "meta" / "runs" / f"{d.isoformat()}_{market}.json"


# --- Read/Write ---

def write_parquet(df: pd.DataFrame, path: Path, schema: pa.Schema | None = None) -> None:
    """Atomic write: write to temp file then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".parquet.tmp")

    if schema is not None:
        table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    else:
        table = pa.Table.from_pandas(df, preserve_index=False)

    pq.write_table(table, tmp_path)
    os.replace(tmp_path, path)


def read_parquet(path: Path) -> pd.DataFrame:
    """Read a single Parquet file."""
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def write_ohlcv(df: pd.DataFrame, market: str, d: date, data_dir: Path) -> Path:
    """Sort by source_id and write OHLCV Parquet."""
    if not df.empty:
        df = df.sort_values("source_id").reset_index(drop=True)
    path = ohlcv_path(data_dir, market, d)
    write_parquet(df, path, schema=OHLCV_SCHEMA)
    return path


def write_instruments(df: pd.DataFrame, market: str, data_dir: Path) -> Path:
    """Overwrite instrument metadata."""
    path = instruments_path(data_dir, market)
    write_parquet(df, path, schema=INSTRUMENTS_SCHEMA)
    return path


def write_quarantine(df: pd.DataFrame, market: str, d: date, data_dir: Path) -> Path:
    """Write quarantine log."""
    path = quarantine_path(data_dir, market, d)
    write_parquet(df, path, schema=QUARANTINE_SCHEMA)
    return path


def write_universe_snapshot(df: pd.DataFrame, market: str, d: date, data_dir: Path) -> Path:
    """Write universe snapshot for the date."""
    path = universe_path(data_dir, market, d)
    write_parquet(df, path, schema=INSTRUMENTS_SCHEMA)
    return path


def write_run_manifest(summary: dict, market: str, d: date, data_dir: Path) -> Path:
    """Write JSON run manifest."""
    path = run_manifest_path(data_dir, market, d)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    os.replace(tmp_path, path)
    return path
