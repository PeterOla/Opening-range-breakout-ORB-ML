"""
Historical data access using DuckDB and local Parquet files.

Functions:
- query_symbol_range(symbol, start_ts, end_ts, interval='1min') -> pandas.DataFrame
- list_available_symbols() -> list[str]
- get_daily_partition_path(symbol, ts) -> str
"""
from __future__ import annotations
import os
from datetime import datetime, date
from typing import Optional, List
import glob
import duckdb
import pandas as pd
from core.config import settings


DB_PATH = settings.DUCKDB_PATH
PARQUET_BASE = settings.PARQUET_BASE_PATH


def _connect():
    if DB_PATH:
        parent = os.path.dirname(DB_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
    con = duckdb.connect(DB_PATH)
    return con


def _day_partition_path(symbol: str, ts: datetime | date, interval: str = '1min') -> str:
    """Return the local parquet path for the partition for the given day and symbol."""
    year = f"{ts.year:04d}"
    month = f"{ts.month:02d}"
    day = f"{ts.day:02d}"
    return os.path.join(PARQUET_BASE, interval, f"symbol={symbol}", f"year={year}", f"month={month}", f"day={day}")


def query_symbol_range(symbol: str, start_ts: datetime, end_ts: datetime, interval: str = "1min") -> pd.DataFrame:
    """Query parquet files for a symbol in a time range and return a pandas DataFrame.

    This function looks for parquet files under `data/processed/<interval>/symbol=<symbol>/year=.../month=.../day=...`.
    If multiple day partitions are requested, it scans the matching files.
    """
    con = _connect()
    # Build wildcard path for the date range (inclusive)
    start_date = start_ts.date()
    end_date = end_ts.date()

    parts = []
    dt = start_date
    while dt <= end_date:
        parts.append(os.path.join(PARQUET_BASE, interval, f"symbol={symbol}", f"year={dt.year:04d}", f"month={dt.month:02d}", f"day={dt.day:02d}", "*.parquet"))
        dt = dt + pd.to_timedelta(1, unit="D")

    # Guard: if no partitioned parts exist, we may still have flat per-symbol parquet files
    # (e.g. DataPipeline writes: data/processed/5min/<SYMBOL>.parquet).
    files = []
    for p in parts:
        files.extend([os.path.abspath(fp) for fp in glob.glob(p)])

    if not files:
        # Flat-file fallback
        flat_path = os.path.join(PARQUET_BASE, interval, f"{symbol}.parquet")
        if not os.path.exists(flat_path):
            # Some pipelines may uppercase symbols on disk
            flat_path = os.path.join(PARQUET_BASE, interval, f"{symbol.upper()}.parquet")
        if not os.path.exists(flat_path):
            return pd.DataFrame()

        try:
            df = pd.read_parquet(flat_path)
        except Exception:
            return pd.DataFrame()

        # Normalise time column name.
        if "timestamp" not in df.columns and "datetime" in df.columns:
            df = df.rename(columns={"datetime": "timestamp"})
        if "timestamp" not in df.columns:
            return pd.DataFrame()

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])

        start = pd.Timestamp(start_ts)
        end = pd.Timestamp(end_ts)
        ts_tz = None
        try:
            ts_tz = df["timestamp"].dt.tz
        except Exception:
            ts_tz = None

        if ts_tz is not None:
            if start.tzinfo is None:
                start = start.tz_localize(ts_tz)
            else:
                start = start.tz_convert(ts_tz)
            if end.tzinfo is None:
                end = end.tz_localize(ts_tz)
            else:
                end = end.tz_convert(ts_tz)
        else:
            # If parquet timestamps are naive but bounds are tz-aware, drop tz.
            if start.tzinfo is not None:
                start = start.tz_convert("UTC").tz_localize(None)
            if end.tzinfo is not None:
                end = end.tz_convert("UTC").tz_localize(None)

        mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
        return df.loc[mask].reset_index(drop=True)

    q_path_list = [f.replace("\\", "/") for f in files]
    start_str = start_ts.strftime('%Y-%m-%d %H:%M:%S')
    end_str = end_ts.strftime('%Y-%m-%d %H:%M:%S')
    query = f"SELECT * FROM read_parquet({', '.join([repr(p) for p in q_path_list])}) WHERE timestamp >= timestamp '{start_str}' AND timestamp <= timestamp '{end_str}'"
    try:
        df = con.execute(query).fetchdf()
    except Exception:
        # Fallback: try single wildcard query
        query2 = f"SELECT * FROM read_parquet('{os.path.join(PARQUET_BASE, interval, f'symbol={symbol}', '**', '*.parquet')}') WHERE timestamp >= timestamp '{start_str}' AND timestamp <= timestamp '{end_str}'"
        df = con.execute(query2).fetchdf()

    # Convert ts to pandas datetime if present
    if 'ts' in df.columns:
        df['ts'] = pd.to_datetime(df['ts'])
    return df


def list_available_symbols(interval: str = '1min') -> List[str]:
    """List symbols available in the parquet data (very cheap local filesystem scan)."""
    base = os.path.join(PARQUET_BASE, interval)
    if not os.path.exists(base):
        return []

    # Prefer partitioned layout: data/processed/<interval>/symbol=XYZ/...
    symbols: list[str] = []
    for item in os.listdir(base):
        if item.startswith('symbol='):
            symbols.append(item.split('=')[1])

    if symbols:
        return symbols

    # Fallback: flat layout: data/processed/<interval>/XYZ.parquet
    out: list[str] = []
    for item in os.listdir(base):
        if item.lower().endswith('.parquet'):
            out.append(os.path.splitext(item)[0])
    return out
