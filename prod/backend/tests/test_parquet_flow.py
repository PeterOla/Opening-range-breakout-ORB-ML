import os
from datetime import datetime, timedelta, date
import pandas as pd
from core.config import settings
from data_access.historical import query_symbol_range


def create_sample_bars(symbol: str, day: date):
    # create simple 5-min bars for the day (only one bar at 09:30)
    ts = datetime(day.year, day.month, day.day, 9, 30)
    df = pd.DataFrame([
        {
            'timestamp': ts,
            'open': 100.0,
            'high': 101.0,
            'low': 99.5,
            'close': 100.5,
            'volume': 1000,
        }
    ])
    # Write to delta path
    delta_dir = os.path.join(settings.DELTA_BASE_PATH, '1min', f'symbol={symbol}', f'day={day.strftime("%Y-%m-%d")}')
    os.makedirs(delta_dir, exist_ok=True)
    file_path = os.path.join(delta_dir, 'test-delta.parquet')
    df.to_parquet(file_path, compression='snappy', index=False)
    return file_path


def test_eod_merge_and_query(tmp_path):
    # Choose a symbol and day
    symbol = 'TEST'
    day = date.today() - timedelta(days=1)

    # Create a delta file
    delta_path = create_sample_bars(symbol, day)
    assert os.path.exists(delta_path)

    # Run eod_merge script programmatically
    from scripts.eod_merge import merge_symbol_day
    merge_symbol_day(symbol, day, interval='1min')

    # Now query via data_access
    start_ts = datetime(day.year, day.month, day.day, 0, 0)
    end_ts = datetime(day.year, day.month, day.day, 23, 59)
    df = query_symbol_range(symbol, start_ts, end_ts, interval='1min')

    assert not df.empty
    assert 'timestamp' in df.columns
    assert int(df['volume'].iloc[0]) == 1000
    assert float(df['close'].iloc[0]) == 100.5

    # cleanup - remove created parquet files
    # (test runner temp_dir handles cleanup)