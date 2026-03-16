"""Integration tests for pipeline orchestration."""

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from getstock.config import AppConfig, MarketConfig
from getstock.schema import INSTRUMENTS_COLUMNS, OHLCV_COLUMNS
from getstock.storage import ohlcv_path, read_parquet


@pytest.fixture
def mock_config(tmp_path):
    return AppConfig(
        data_dir=tmp_path / "data",
        markets={
            "krx": MarketConfig(
                timezone="Asia/Seoul",
                exchange_calendar="XKRX",
                close_time="15:30",
                run_delay_minutes=30,
                asset_types=["stock"],
                source="pykrx",
            ),
        },
        backfill_lookback_days=365,
        price_change_warn_threshold=0.50,
        delisting_safety_threshold=0.20,
        log_level="INFO",
        log_file_enabled=False,
        tiingo_api_key=None,
    )


def _mock_universe(target_date):
    return pd.DataFrame([
        {"source_id": "005930", "ticker": "005930", "name": "Samsung", "market": "krx", "asset_type": "stock", "exchange": "KOSPI", "currency": "KRW", "is_active": True, "delisted_date": None, "first_seen": target_date, "last_updated": target_date},
        {"source_id": "000660", "ticker": "000660", "name": "SK Hynix", "market": "krx", "asset_type": "stock", "exchange": "KOSPI", "currency": "KRW", "is_active": True, "delisted_date": None, "first_seen": target_date, "last_updated": target_date},
    ], columns=INSTRUMENTS_COLUMNS)


def _mock_ohlcv(target_date):
    now = datetime.now(timezone.utc)
    return pd.DataFrame([
        {"source_id": "005930", "ticker": "005930", "date": target_date, "open": 70000, "high": 71000, "low": 69000, "close": 70500, "volume": 10000000, "adj_open": None, "adj_high": None, "adj_low": None, "adj_close": None, "adj_volume": None, "market": "krx", "source": "pykrx", "fetched_at": now},
        {"source_id": "000660", "ticker": "000660", "date": target_date, "open": 150000, "high": 152000, "low": 148000, "close": 151000, "volume": 5000000, "adj_open": None, "adj_high": None, "adj_low": None, "adj_close": None, "adj_volume": None, "market": "krx", "source": "pykrx", "fetched_at": now},
    ], columns=OHLCV_COLUMNS)


@patch("getstock.sources.krx.fetch_adjusted_krx")
@patch("getstock.sources.krx.fetch_ohlcv_krx")
@patch("getstock.universe.fetch_universe_krx")
def test_run_daily_krx(mock_universe, mock_ohlcv, mock_adj, mock_config):
    target = date(2026, 3, 13)  # a Friday
    mock_universe.return_value = _mock_universe(target)
    mock_ohlcv.return_value = _mock_ohlcv(target)
    mock_adj.return_value = (pd.DataFrame(columns=["source_id", "date", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"]), [])

    from getstock.pipeline import run_daily

    summary = run_daily("krx", target, mock_config)
    assert summary.status == "success"
    assert summary.fetched_count == 2

    # Verify Parquet file written
    path = ohlcv_path(mock_config.data_dir, "krx", target)
    assert path.exists()
    df = read_parquet(path)
    assert len(df) == 2


@patch("getstock.sources.krx.fetch_adjusted_krx")
@patch("getstock.sources.krx.fetch_ohlcv_krx")
@patch("getstock.universe.fetch_universe_krx")
def test_run_daily_idempotent(mock_universe, mock_ohlcv, mock_adj, mock_config):
    target = date(2026, 3, 13)
    mock_universe.return_value = _mock_universe(target)
    mock_ohlcv.return_value = _mock_ohlcv(target)
    mock_adj.return_value = (pd.DataFrame(columns=["source_id", "date", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"]), [])

    from getstock.pipeline import run_daily

    run_daily("krx", target, mock_config)
    run_daily("krx", target, mock_config)

    path = ohlcv_path(mock_config.data_dir, "krx", target)
    df = read_parquet(path)
    assert len(df) == 2  # Same result, not doubled
