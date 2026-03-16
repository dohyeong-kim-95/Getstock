"""Quarantine handling for failed instrument-dates."""

from __future__ import annotations

import pandas as pd

from getstock.schema import QUARANTINE_COLUMNS


def merge_quarantine(
    ingestion_errors: pd.DataFrame | list[dict],
    validation_errors: pd.DataFrame,
) -> pd.DataFrame:
    """Combine quarantine entries from ingestion and validation stages."""
    dfs = []

    if isinstance(ingestion_errors, list):
        if ingestion_errors:
            dfs.append(pd.DataFrame(ingestion_errors, columns=QUARANTINE_COLUMNS))
    elif isinstance(ingestion_errors, pd.DataFrame) and not ingestion_errors.empty:
        dfs.append(ingestion_errors)

    if not validation_errors.empty:
        dfs.append(validation_errors)

    if not dfs:
        return pd.DataFrame(columns=QUARANTINE_COLUMNS)

    combined = pd.concat(dfs, ignore_index=True)
    return combined[QUARANTINE_COLUMNS]
