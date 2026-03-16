"""Normalize source-specific data to canonical schema."""

from __future__ import annotations

import logging

import pandas as pd

from getstock.schema import (
    DIVIDENDS_COLUMNS,
    OHLCV_COLUMNS,
    SPLITS_COLUMNS,
)

logger = logging.getLogger(__name__)


def normalize_ohlcv(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Map source-specific columns to canonical OHLCV schema."""
    if df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    df = df.copy()

    # Ensure correct types
    df["source_id"] = df["source_id"].astype(str)
    df["ticker"] = df["ticker"].astype(str)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")

    for col in ["adj_open", "adj_high", "adj_low", "adj_close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "adj_volume" in df.columns:
        df["adj_volume"] = pd.to_numeric(df["adj_volume"], errors="coerce").astype("Int64")

    df["market"] = df.get("market", source)
    df["source"] = source

    # Ensure all columns present
    for col in OHLCV_COLUMNS:
        if col not in df.columns:
            df[col] = None

    return df[OHLCV_COLUMNS]


def normalize_dividends(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Map to canonical dividends schema."""
    if df.empty:
        return pd.DataFrame(columns=DIVIDENDS_COLUMNS)
    df = df.copy()
    df["source"] = source
    for col in DIVIDENDS_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[DIVIDENDS_COLUMNS]


def normalize_splits(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Map to canonical splits schema."""
    if df.empty:
        return pd.DataFrame(columns=SPLITS_COLUMNS)
    df = df.copy()
    df["source"] = source
    for col in SPLITS_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[SPLITS_COLUMNS]
