"""Tests for config loading."""

import os
from pathlib import Path

import pytest
import yaml

from getstock.config import load_config, validate_config


@pytest.fixture
def config_file(tmp_path):
    config = {
        "data_dir": str(tmp_path / "data"),
        "markets": {
            "krx": {
                "timezone": "Asia/Seoul",
                "exchange_calendar": "XKRX",
                "close_time": "15:30",
                "run_delay_minutes": 30,
                "asset_types": ["stock"],
                "source": "pykrx",
            },
            "us": {
                "timezone": "US/Eastern",
                "exchange_calendar": "XNYS",
                "close_time": "16:00",
                "run_delay_minutes": 30,
                "asset_types": ["stock", "etf"],
                "source": "tiingo",
                "universe_filter": "all",
            },
        },
        "backfill": {"lookback_days": 365},
        "validation": {"price_change_warn_threshold": 0.50},
        "delisting": {"safety_threshold": 0.20},
        "logging": {"level": "INFO", "file_enabled": False},
    }
    path = tmp_path / "config.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


def test_load_config(config_file):
    cfg = load_config(config_file)
    assert "krx" in cfg.markets
    assert "us" in cfg.markets
    assert cfg.markets["krx"].exchange_calendar == "XKRX"
    assert cfg.backfill_lookback_days == 365
    assert cfg.delisting_safety_threshold == 0.20


def test_validate_config_unknown_market(config_file):
    cfg = load_config(config_file)
    with pytest.raises(ValueError, match="Unknown market"):
        validate_config(cfg, "jpx")


def test_validate_config_us_no_api_key(config_file, monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    cfg = load_config(config_file)
    cfg.tiingo_api_key = None
    with pytest.raises(ValueError, match="TIINGO_API_KEY"):
        validate_config(cfg, "us")


def test_validate_config_krx_no_api_key(config_file, monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    cfg = load_config(config_file)
    cfg.tiingo_api_key = None
    # Should not raise for KRX
    validate_config(cfg, "krx")
