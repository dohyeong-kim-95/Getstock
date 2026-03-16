"""Tests for Tiingo fetcher (mocked HTTP)."""

from datetime import date

import pytest
import responses

from getstock.sources.tiingo import fetch_ohlcv_tiingo


@responses.activate
def test_fetch_ohlcv_tiingo_basic():
    responses.add(
        responses.GET,
        "https://api.tiingo.com/tiingo/daily/AAPL/prices",
        json=[{
            "date": "2026-03-15T00:00:00+00:00",
            "open": 175.0,
            "high": 178.0,
            "low": 174.0,
            "close": 177.0,
            "volume": 50000000,
            "adjOpen": 175.0,
            "adjHigh": 178.0,
            "adjLow": 174.0,
            "adjClose": 177.0,
            "adjVolume": 50000000,
        }],
        status=200,
    )

    result = fetch_ohlcv_tiingo("AAPL", date(2026, 3, 15), date(2026, 3, 15), "test_key")
    assert len(result) == 1
    assert result.iloc[0]["ticker"] == "AAPL"
    assert result.iloc[0]["adj_close"] == 177.0
    assert result.iloc[0]["market"] == "us"


@responses.activate
def test_fetch_ohlcv_tiingo_empty():
    responses.add(
        responses.GET,
        "https://api.tiingo.com/tiingo/daily/FAKE/prices",
        json=[],
        status=200,
    )

    result = fetch_ohlcv_tiingo("FAKE", date(2026, 3, 15), date(2026, 3, 15), "test_key")
    assert result.empty


@responses.activate
def test_fetch_ohlcv_tiingo_http_error():
    responses.add(
        responses.GET,
        "https://api.tiingo.com/tiingo/daily/BAD/prices",
        json={"detail": "Not found"},
        status=404,
    )

    import requests
    with pytest.raises(requests.exceptions.HTTPError):
        fetch_ohlcv_tiingo("BAD", date(2026, 3, 15), date(2026, 3, 15), "test_key")
