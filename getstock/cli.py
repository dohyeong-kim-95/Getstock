"""CLI definitions using Click."""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime

import click
import exchange_calendars as xcals

from getstock.config import load_config, validate_config
from getstock.logging_config import setup_logging

logger = logging.getLogger(__name__)


def _resolve_trading_date(market_config, target_date: date | None) -> date | None:
    """Return target_date if it's a trading day, else None."""
    cal = xcals.get_calendar(market_config.exchange_calendar)
    if target_date is None:
        target_date = date.today()
    ts = datetime(target_date.year, target_date.month, target_date.day)
    if not cal.is_session(ts):
        return None
    return target_date


@click.group()
def cli() -> None:
    """Getstock: Daily ETL for equity market data."""


@cli.command()
@click.option("--market", required=True, type=click.Choice(["krx", "us"]), help="Target market")
@click.option("--date", "run_date", default=None, type=click.DateTime(formats=["%Y-%m-%d"]), help="Trading date (default: today)")
@click.option("--config-path", default="config.yaml", help="Path to config file")
def run(market: str, run_date: datetime | None, config_path: str) -> None:
    """Run daily ingestion for a market."""
    config = load_config(config_path)
    validate_config(config, market)

    target = run_date.date() if run_date else None
    market_config = config.markets[market]

    setup_logging(
        level=config.log_level,
        file_enabled=config.log_file_enabled,
        data_dir=config.data_dir,
        market=market,
        run_date=target or date.today(),
    )

    trading_date = _resolve_trading_date(market_config, target)
    if trading_date is None:
        display = (target or date.today()).isoformat()
        logger.info(f"{display} is not a trading day for {market}. Nothing to do.")
        sys.exit(0)

    logger.info(f"Starting daily run for {market} on {trading_date.isoformat()}")

    from getstock.pipeline import run_daily

    summary = run_daily(market, trading_date, config)
    if summary.status == "success":
        logger.info(f"Daily run completed successfully for {market} on {trading_date.isoformat()}")
        sys.exit(0)
    else:
        logger.error(f"Daily run failed for {market} on {trading_date.isoformat()}")
        sys.exit(1)


@cli.command()
@click.option("--market", required=True, type=click.Choice(["krx", "us"]), help="Target market")
@click.option("--start", required=True, type=click.DateTime(formats=["%Y-%m-%d"]), help="Start date")
@click.option("--end", required=True, type=click.DateTime(formats=["%Y-%m-%d"]), help="End date")
@click.option("--config-path", default="config.yaml", help="Path to config file")
@click.option("--dry-run", is_flag=True, help="Log what would be fetched without writing")
def backfill(market: str, start: datetime, end: datetime, config_path: str, dry_run: bool) -> None:
    """Backfill historical data for a market."""
    config = load_config(config_path)
    validate_config(config, market)

    setup_logging(
        level=config.log_level,
        file_enabled=config.log_file_enabled,
        data_dir=config.data_dir,
        market=market,
        run_date=date.today(),
    )

    logger.info(f"Starting backfill for {market} from {start.date()} to {end.date()}")

    from getstock.pipeline import run_backfill

    run_backfill(market, start.date(), end.date(), config, dry_run=dry_run)


@cli.command()
@click.option("--market", required=True, type=click.Choice(["krx", "us"]), help="Target market")
@click.option("--ticker", default=None, help="Filter by ticker")
@click.option("--start", default=None, type=click.DateTime(formats=["%Y-%m-%d"]), help="Start date")
@click.option("--end", default=None, type=click.DateTime(formats=["%Y-%m-%d"]), help="End date")
@click.option("--config-path", default="config.yaml", help="Path to config file")
def query(market: str, ticker: str | None, start: datetime | None, end: datetime | None, config_path: str) -> None:
    """Query stored data via DuckDB."""
    config = load_config(config_path)

    setup_logging(level=config.log_level)

    from getstock.query import get_ohlcv

    df = get_ohlcv(
        market=market,
        start_date=start.date() if start else None,
        end_date=end.date() if end else None,
        ticker=ticker,
        data_dir=config.data_dir,
    )
    if df.empty:
        logger.info("No data found for the given query.")
    else:
        click.echo(df.to_string(index=False))
