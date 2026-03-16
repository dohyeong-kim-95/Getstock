"""Logging configuration."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path


def setup_logging(
    level: str = "INFO",
    file_enabled: bool = False,
    data_dir: Path | None = None,
    market: str | None = None,
    run_date: date | None = None,
) -> None:
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if file_enabled and data_dir and market and run_date:
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{run_date.isoformat()}_{market}.log"
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_format,
        handlers=handlers,
        force=True,
    )
