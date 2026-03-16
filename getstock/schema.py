"""Canonical schema constants for all datasets."""

import pyarrow as pa

# --- OHLCV ---
OHLCV_COLUMNS = [
    "source_id",
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "adj_volume",
    "market",
    "source",
    "fetched_at",
]

OHLCV_SCHEMA = pa.schema([
    ("source_id", pa.string()),
    ("ticker", pa.string()),
    ("date", pa.date32()),
    ("open", pa.float64()),
    ("high", pa.float64()),
    ("low", pa.float64()),
    ("close", pa.float64()),
    ("volume", pa.int64()),
    ("adj_open", pa.float64()),
    ("adj_high", pa.float64()),
    ("adj_low", pa.float64()),
    ("adj_close", pa.float64()),
    ("adj_volume", pa.int64()),
    ("market", pa.string()),
    ("source", pa.string()),
    ("fetched_at", pa.timestamp("us", tz="UTC")),
])

# --- Dividends ---
DIVIDENDS_COLUMNS = [
    "source_id",
    "ticker",
    "ex_date",
    "amount",
    "currency",
    "market",
    "source",
    "fetched_at",
]

DIVIDENDS_SCHEMA = pa.schema([
    ("source_id", pa.string()),
    ("ticker", pa.string()),
    ("ex_date", pa.date32()),
    ("amount", pa.float64()),
    ("currency", pa.string()),
    ("market", pa.string()),
    ("source", pa.string()),
    ("fetched_at", pa.timestamp("us", tz="UTC")),
])

# --- Splits ---
SPLITS_COLUMNS = [
    "source_id",
    "ticker",
    "date",
    "ratio_from",
    "ratio_to",
    "market",
    "source",
    "fetched_at",
]

SPLITS_SCHEMA = pa.schema([
    ("source_id", pa.string()),
    ("ticker", pa.string()),
    ("date", pa.date32()),
    ("ratio_from", pa.float64()),
    ("ratio_to", pa.float64()),
    ("market", pa.string()),
    ("source", pa.string()),
    ("fetched_at", pa.timestamp("us", tz="UTC")),
])

# --- Instrument Metadata ---
INSTRUMENTS_COLUMNS = [
    "source_id",
    "ticker",
    "name",
    "market",
    "asset_type",
    "exchange",
    "currency",
    "is_active",
    "delisted_date",
    "first_seen",
    "last_updated",
]

INSTRUMENTS_SCHEMA = pa.schema([
    ("source_id", pa.string()),
    ("ticker", pa.string()),
    ("name", pa.string()),
    ("market", pa.string()),
    ("asset_type", pa.string()),
    ("exchange", pa.string()),
    ("currency", pa.string()),
    ("is_active", pa.bool_()),
    ("delisted_date", pa.date32()),
    ("first_seen", pa.date32()),
    ("last_updated", pa.date32()),
])

# --- Quarantine Log ---
QUARANTINE_COLUMNS = [
    "source_id",
    "ticker",
    "market",
    "date",
    "stage",
    "error_type",
    "error_detail",
    "created_at",
]

QUARANTINE_SCHEMA = pa.schema([
    ("source_id", pa.string()),
    ("ticker", pa.string()),
    ("market", pa.string()),
    ("date", pa.date32()),
    ("stage", pa.string()),
    ("error_type", pa.string()),
    ("error_detail", pa.string()),
    ("created_at", pa.timestamp("us", tz="UTC")),
])
