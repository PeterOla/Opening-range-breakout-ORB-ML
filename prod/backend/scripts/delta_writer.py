"""
Simple delta writer to write intraday bars during market hours into `data/deltas`.

Example usage:
python delta_writer.py --symbol=AAPL --interval=1min --outfile="/path/to/bar.parquet"
"""
from __future__ import annotations
import argparse
import os
from datetime import datetime
import pandas as pd
from core.config import settings


def write_delta_dataframe(symbol: str, df: pd.DataFrame, interval: str = '1min') -> str:
    """Write the dataframe to a delta parquet file path for symbol/day and return the path."""
    day_str = datetime.utcnow().strftime('%Y-%m-%d')
    delta_dir = os.path.join(settings.DELTA_BASE_PATH, interval, f"symbol={symbol}", f"day={day_str}")
    os.makedirs(delta_dir, exist_ok=True)
    filename = f"delta-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.parquet"
    path = os.path.join(delta_dir, filename)
    df.to_parquet(path, compression='snappy', index=False)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--interval', default='1min')
    parser.add_argument('--infile', required=True, help='csv or parquet file to write as delta')
    args = parser.parse_args()

    if args.infile.endswith('.csv'):
        df = pd.read_csv(args.infile)
    else:
        df = pd.read_parquet(args.infile)

    path = write_delta_dataframe(args.symbol, df, args.interval)
    print(f'Wrote delta file: {path}')
