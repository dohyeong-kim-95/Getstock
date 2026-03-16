"""DuckDB query helpers for reading Parquet data."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


def get_ohlcv(
    market: str,
    data_dir: Path,
    start_date: date | None = None,
    end_date: date | None = None,
    ticker: str | None = None,
    source_id: str | None = None,
) -> pd.DataFrame:
    """Query OHLCV data from Parquet files via DuckDB."""
    pattern = str(data_dir / "ohlcv" / market / "**" / "*.parquet")
    conditions = []
    params: list = []

    if start_date:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        params.append(end_date)
    if ticker:
        conditions.append("ticker = ?")
        params.append(ticker)
    if source_id:
        conditions.append("source_id = ?")
        params.append(source_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM read_parquet('{pattern}', union_by_name=true) {where} ORDER BY source_id, date"

    try:
        con = duckdb.connect()
        df = con.execute(query, params).fetchdf()
        con.close()
        return df
    except Exception as e:
        logger.warning(f"Query failed: {e}")
        return pd.DataFrame()


def get_universe(
    market: str, data_dir: Path, active_only: bool = True
) -> pd.DataFrame:
    """Read instrument metadata."""
    path = data_dir / "meta" / f"instruments_{market}.parquet"
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_parquet(path)
    if active_only:
        df = df[df["is_active"] == True]
    return df


def get_quarantine_log(
    market: str, data_dir: Path,
    start_date: date | None = None, end_date: date | None = None,
) -> pd.DataFrame:
    """Read quarantine log files."""
    pattern = str(data_dir / "meta" / "quarantine" / f"*_{market}.parquet")

    conditions = []
    params: list = []
    if start_date:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        params.append(end_date)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM read_parquet('{pattern}', union_by_name=true) {where} ORDER BY date DESC"

    try:
        con = duckdb.connect()
        df = con.execute(query, params).fetchdf()
        con.close()
        return df
    except Exception as e:
        logger.warning(f"Quarantine query failed: {e}")
        return pd.DataFrame()
