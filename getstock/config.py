"""Configuration loading from config.yaml and .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class MarketConfig:
    timezone: str
    exchange_calendar: str
    close_time: str
    run_delay_minutes: int
    asset_types: list[str]
    source: str
    universe_filter: str = "all"
    watchlist: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    data_dir: Path
    markets: dict[str, MarketConfig]
    backfill_lookback_days: int
    price_change_warn_threshold: float
    delisting_safety_threshold: float
    log_level: str
    log_file_enabled: bool
    tiingo_api_key: str | None


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    load_dotenv()

    config_path = Path(config_path)
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    markets: dict[str, MarketConfig] = {}
    for name, m in raw["markets"].items():
        markets[name] = MarketConfig(
            timezone=m["timezone"],
            exchange_calendar=m["exchange_calendar"],
            close_time=m["close_time"],
            run_delay_minutes=m["run_delay_minutes"],
            asset_types=m["asset_types"],
            source=m["source"],
            universe_filter=m.get("universe_filter", "all"),
            watchlist=m.get("watchlist", []),
        )

    return AppConfig(
        data_dir=Path(raw["data_dir"]),
        markets=markets,
        backfill_lookback_days=raw["backfill"]["lookback_days"],
        price_change_warn_threshold=raw["validation"]["price_change_warn_threshold"],
        delisting_safety_threshold=raw["delisting"]["safety_threshold"],
        log_level=raw["logging"]["level"],
        log_file_enabled=raw["logging"]["file_enabled"],
        tiingo_api_key=os.environ.get("TIINGO_API_KEY"),
    )


def validate_config(config: AppConfig, market: str) -> None:
    if market not in config.markets:
        raise ValueError(f"Unknown market: {market}. Available: {list(config.markets.keys())}")
    if market == "us" and not config.tiingo_api_key:
        raise ValueError("TIINGO_API_KEY is required for US market. Set it in .env file.")
