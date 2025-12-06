#!/usr/bin/env python
"""Inspect the actual schema of daily and 5-min parquet files."""
import pandas as pd
from pathlib import Path

print("="*70)
print("DAILY DATA SCHEMA")
print("="*70)
daily_files = list(Path('data/processed/daily').glob('*.parquet'))
print(f"\nTotal daily parquets: {len(daily_files)}")

# Load and inspect one
df_daily = pd.read_parquet(daily_files[0])
print(f"\nColumns: {df_daily.columns.tolist()}")
print(f"Shape: {df_daily.shape}")
print(f"\nFirst 5 rows:")
print(df_daily.head(5))
print(f"\nData types:\n{df_daily.dtypes}")
print(f"\nUnique symbols in sample file: {df_daily['symbol'].nunique()}")
print(f"Sample symbols: {df_daily['symbol'].unique()[:5]}")

print("\n" + "="*70)
print("5-MIN DATA SCHEMA")
print("="*70)
min5_files = list(Path('data/processed/5min').glob('*.parquet'))
print(f"\nTotal 5-min parquets: {len(min5_files)}")

df_5min = pd.read_parquet(min5_files[0])
print(f"\nColumns: {df_5min.columns.tolist()}")
print(f"Shape: {df_5min.shape}")
print(f"\nFirst 5 rows:")
print(df_5min.head(5))
print(f"\nData types:\n{df_5min.dtypes}")
print(f"\nTimestamp range:")
print(f"  Min: {df_5min['timestamp'].min()}")
print(f"  Max: {df_5min['timestamp'].max()}")
print(f"\nUnique symbols in sample: {df_5min['symbol'].nunique()}")
print(f"Sample symbols: {df_5min['symbol'].unique()[:5]}")

# Check for specific date
print("\n" + "="*70)
print("DATA AVAILABILITY FOR 2025-11-03")
print("="*70)

date_2025_11_03 = pd.Timestamp('2025-11-03').date()

# Daily
df_daily['date'] = pd.to_datetime(df_daily['date']).dt.date
df_daily_nov03 = df_daily[df_daily['date'] == date_2025_11_03]
print(f"\nDaily records for 2025-11-03: {len(df_daily_nov03)}")
if len(df_daily_nov03) > 0:
    print(f"Sample daily data:")
    cols = ['date', 'symbol', 'open', 'close', 'volume']
    print(df_daily_nov03[cols].head(10))

# 5-min
df_5min['date'] = pd.to_datetime(df_5min['timestamp']).dt.date
df_5min_nov03 = df_5min[df_5min['date'] == date_2025_11_03]
print(f"\n5-min records for 2025-11-03: {len(df_5min_nov03)}")
if len(df_5min_nov03) > 0:
    print(f"Time range: {df_5min_nov03['timestamp'].min()} to {df_5min_nov03['timestamp'].max()}")
    print(f"Symbols: {sorted(df_5min_nov03['symbol'].unique())[:10]}")
    
    # Check 9:30 bars
    df_5min_nov03['time'] = pd.to_datetime(df_5min_nov03['timestamp']).dt.time
    df_930 = df_5min_nov03[df_5min_nov03['time'] == pd.Timestamp('09:30:00').time()]
    print(f"\n9:30 ET bars on that date: {len(df_930)}")
    if len(df_930) > 0:
        print("Sample 9:30 bars:")
        print(df_930[['symbol', 'timestamp', 'open', 'high', 'low', 'close', 'volume']].head(5))
    
    # Intersection
    daily_syms = set(df_daily_nov03['symbol'].unique())
    min5_syms = set(df_5min_nov03['symbol'].unique())
    intersection = daily_syms & min5_syms
    print(f"\nSymbols in both daily & 5-min on that date: {len(intersection)}")
    if intersection:
        print(f"Examples: {sorted(list(intersection))[:10]}")

print("\n" + "="*70)
print("ORB UNIVERSE REFERENCE")
print("="*70)
# Check existing ORB universe for comparison
ref_universe = Path('data/backtest/universe_or_atr050/universe_or_atr050_20251101_20251130.parquet')
if ref_universe.exists():
    df_ref = pd.read_parquet(ref_universe)
    print(f"\nORB universe columns: {df_ref.columns.tolist()}")
    print(f"Shape: {df_ref.shape}")
    print(f"Sample:")
    print(df_ref.head(3))
