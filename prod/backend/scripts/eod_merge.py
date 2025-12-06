"""
EOD merge delta parquet files into processed partitioned parquet files.

Usage:
python eod_merge.py --symbol AAPL --date 2025-12-05 --interval 1min
"""
from __future__ import annotations
import argparse
from datetime import datetime, date
import os
import glob
import duckdb
import pandas as pd
from core.config import settings


def merge_symbol_day(symbol: str, day: date, interval: str = '1min'):
    duckdb_path = settings.DUCKDB_PATH
    con = duckdb.connect(duckdb_path)
    delta_dir = os.path.join(settings.DELTA_BASE_PATH, interval, f"symbol={symbol}", f"day={day.strftime('%Y-%m-%d')}")
    target_dir = os.path.join(settings.PARQUET_BASE_PATH, interval, f"symbol={symbol}", f"year={day.year}", f"month={day.month:02d}", f"day={day.day:02d}")

    delta_files = glob.glob(os.path.join(delta_dir, '*.parquet'))
    if not delta_files:
        print(f"No delta files for {symbol} on {day}")
        return

    os.makedirs(target_dir, exist_ok=True)

    # Gather existing processed files
    existing_files = glob.glob(os.path.join(target_dir, '*.parquet'))

    # Build queries
    files_to_read = existing_files + delta_files
    files_to_read = [f.replace('\\','/') for f in files_to_read]

    print(f"Merging {len(files_to_read)} files for {symbol} on {day}")

    # Build per-file read query and union them
    # Read each file separately with hive partitioning and union in pandas to avoid set op issues
    df_list = []
    for p in files_to_read:
        try:
            df_i = con.execute(f"SELECT * FROM read_parquet({repr(p)}, hive_partitioning => TRUE)").fetchdf()
            # Normalize timestamp column
            if 'ts' in df_i.columns and 'timestamp' not in df_i.columns:
                df_i['timestamp'] = pd.to_datetime(df_i['ts'])
                df_i = df_i.drop(columns=['ts'])
            if 'timestamp' in df_i.columns:
                df_i['timestamp'] = pd.to_datetime(df_i['timestamp'])
            # Keep only known columns
            cols_keep = [c for c in ['timestamp', 'open', 'high', 'low', 'close', 'volume'] if c in df_i.columns]
            df_i = df_i[cols_keep]
            if not df_i.empty:
                df_list.append(df_i)
        except Exception as e:
            print(f"Failed reading {p}: {e}")
            continue

    if not df_list:
        print('No valid files found to merge')
        return

    df = pd.concat(df_list, ignore_index=True)
    if df.empty:
        print('Resulting df empty, skipping write')
        return

    # Optionally dedupe by ts
    # Some parquet writers call the ts column 'ts' or 'timestamp'. Normalize to 'timestamp'
    if 'ts' in df.columns and 'timestamp' not in df.columns:
        df['timestamp'] = pd.to_datetime(df['ts'])
        df = df.drop(columns=['ts'])
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp'], keep='last')

    # Write merged to target dir as new single file
    # To avoid rewriting same file path, write to temp path and then move
    tmp_file = os.path.join(target_dir, f"merged-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.parquet")
    con.execute("COPY df TO '" + tmp_file.replace('\\','/') + "' (FORMAT PARQUET, COMPRESSION 'SNAPPY')")

    print(f"Merged written to {tmp_file}")

    # Optionally, cleanup delta files
    for f in delta_files:
        try:
            os.remove(f)
        except Exception:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--date', required=True, help='YYYY-MM-DD')
    parser.add_argument('--interval', default='1min')
    args = parser.parse_args()

    day = datetime.strptime(args.date, '%Y-%m-%d').date()
    merge_symbol_day(args.symbol, day, args.interval)
