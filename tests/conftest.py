"""Shared test fixtures."""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from getstock.schema import OHLCV_COLUMNS


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Temporary data directory."""
    return tmp_path / "data"


@pytest.fixture
def sample_ohlcv_df():
    """Sample OHLCV DataFrame with 5 tickers, 1 date."""
    now = datetime.now(timezone.utc)
    d = date(2026, 3, 15)
    rows = [
        {"source_id": "005930", "ticker": "005930", "date": d, "open": 70000, "high": 71000, "low": 69000, "close": 70500, "volume": 10000000, "adj_open": 70000.0, "adj_high": 71000.0, "adj_low": 69000.0, "adj_close": 70500.0, "adj_volume": 10000000, "market": "krx", "source": "pykrx", "fetched_at": now},
        {"source_id": "000660", "ticker": "000660", "date": d, "open": 150000, "high": 152000, "low": 148000, "close": 151000, "volume": 5000000, "adj_open": 150000.0, "adj_high": 152000.0, "adj_low": 148000.0, "adj_close": 151000.0, "adj_volume": 5000000, "market": "krx", "source": "pykrx", "fetched_at": now},
        {"source_id": "035420", "ticker": "035420", "date": d, "open": 300000, "high": 305000, "low": 298000, "close": 302000, "volume": 2000000, "adj_open": 300000.0, "adj_high": 305000.0, "adj_low": 298000.0, "adj_close": 302000.0, "adj_volume": 2000000, "market": "krx", "source": "pykrx", "fetched_at": now},
        {"source_id": "051910", "ticker": "051910", "date": d, "open": 500000, "high": 510000, "low": 495000, "close": 505000, "volume": 1000000, "adj_open": None, "adj_high": None, "adj_low": None, "adj_close": None, "adj_volume": None, "market": "krx", "source": "pykrx", "fetched_at": now},
        # Bad data: negative price for quarantine testing
        {"source_id": "999999", "ticker": "999999", "date": d, "open": -100, "high": 200, "low": 50, "close": 150, "volume": 1000, "adj_open": None, "adj_high": None, "adj_low": None, "adj_close": None, "adj_volume": None, "market": "krx", "source": "pykrx", "fetched_at": now},
    ]
    return pd.DataFrame(rows, columns=OHLCV_COLUMNS)


@pytest.fixture
def sample_date():
    return date(2026, 3, 15)
