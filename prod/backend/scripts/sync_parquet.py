"""
Copy delta parquet files into processed partitions and optionally validate the merge.

This script finds every delta file written under `data/deltas/<interval>/symbol=<symbol>/day=<YYYY-MM-DD>`,
runs `merge_symbol_day` for each pair, then runs a quick DuckDB query to ensure the partition is readable.
"""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
from typing import Iterable
from data_access.historical import query_symbol_range
from core.config import settings
from scripts.eod_merge import merge_symbol_day


def iter_delta_partitions(intervals: Iterable[str]) -> Iterable[tuple[str, datetime.date]]:
    base = Path(settings.DELTA_BASE_PATH)
    for interval in intervals:
        interval_dir = base / interval
        if not interval_dir.exists():
            continue
        for symbol_dir in sorted(interval_dir.glob('symbol=*')):
            symbol = symbol_dir.name.split('=', 1)[1]
            for day_dir in sorted(symbol_dir.glob('day=*')):
                day_str = day_dir.name.split('=', 1)[1]
                try:
                    day = datetime.strptime(day_str, '%Y-%m-%d').date()
                except ValueError:
                    continue
                yield interval, symbol, day


def sync_all(intervals: Iterable[str], verify: bool = False):
    for interval, symbol, day in iter_delta_partitions(intervals):
        print(f"[sync] Merging {symbol} {day} {interval}")
        merge_symbol_day(symbol, day, interval=interval)
        if verify:
            start = datetime(day.year, day.month, day.day, 0, 0)
            end = datetime(day.year, day.month, day.day, 23, 59)
            df = query_symbol_range(symbol, start, end, interval=interval)
            if df.empty:
                print(f"[sync][warning] Verification returned empty DataFrame for {symbol} {day}")
            else:
                print(f"[sync] Verified {len(df)} rows ({symbol} {day})")


def main():
    parser = argparse.ArgumentParser(description="Merge delta parquet files for every symbol/day into processed partitions")
    parser.add_argument('--interval', '-i', action='append', default=['1min'], help='Intervals to process (default: 1min)')
    parser.add_argument('--verify', action='store_true', help='After merging, run DuckDB query to ensure data reads back')
    args = parser.parse_args()
    sync_all(args.interval, verify=args.verify)


if __name__ == '__main__':
    main()
