import pandas as pd
from pathlib import Path

print("=" * 80)
print("DATA SCHEMA DOCUMENTATION")
print("=" * 80)

# 1. Historical Shares
print("\n1. HISTORICAL SHARES (data/raw/historical_shares.parquet)")
print("-" * 80)
shares = pd.read_parquet('data/raw/historical_shares.parquet')
print(f"Shape: {shares.shape[0]:,} rows × {shares.shape[1]} columns")
print(f"\nColumns and Types:")
for col, dtype in shares.dtypes.items():
    print(f"  - {col}: {dtype}")
print(f"\nSample row:")
print(shares.iloc[0])
print(f"\nDate range: {shares['date'].min()} to {shares['date'].max()}")
print(f"Unique symbols: {shares['symbol'].nunique():,}")
print(f"Shares range: {shares['shares_outstanding'].min():,.0f} to {shares['shares_outstanding'].max():,.0f}")

# 2. Daily Data
print("\n\n2. DAILY DATA (data/processed/daily/{SYMBOL}.parquet)")
print("-" * 80)
daily = pd.read_parquet('data/processed/daily/A.parquet')
print(f"Example file: A.parquet")
print(f"Shape: {daily.shape[0]:,} rows × {daily.shape[1]} columns")
print(f"\nColumns and Types:")
for col, dtype in daily.dtypes.items():
    print(f"  - {col}: {dtype}")
print(f"\nSample row:")
print(daily.iloc[0])
print(f"\nDate range: {daily['date'].min()} to {daily['date'].max()}")
print(f"Missing 'shares_outstanding': {'YES' if 'shares_outstanding' not in daily.columns else 'NO'}")

# 3. 5-minute Data
print("\n\n3. INTRADAY 5-MINUTE DATA (data/processed/5min/{SYMBOL}.parquet)")
print("-" * 80)
try:
    intraday = pd.read_parquet('data/processed/5min/A.parquet')
    print(f"Example file: A.parquet")
    print(f"Shape: {intraday.shape[0]:,} rows × {intraday.shape[1]} columns")
    print(f"\nColumns and Types:")
    for col, dtype in intraday.dtypes.items():
        print(f"  - {col}: {dtype}")
    print(f"\nSample row:")
    print(intraday.iloc[0])
    print(f"\nDate range: {intraday['datetime'].min()} to {intraday['datetime'].max()}")
except FileNotFoundError:
    print("File not found: data/processed/5min/A.parquet")
except Exception as e:
    print(f"Error reading 5min data: {e}")

# 4. Count files
print("\n\n4. DATA FILES COUNT")
print("-" * 80)
daily_files = list(Path('data/processed/daily').glob('*.parquet'))
print(f"Daily parquet files: {len(daily_files):,}")

try:
    intraday_files = list(Path('data/processed/5min').glob('*.parquet'))
    print(f"5-minute parquet files: {len(intraday_files):,}")
except:
    print("5-minute files: unable to count")

print("\n" + "=" * 80)
