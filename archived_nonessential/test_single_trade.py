"""Test feature extraction on single trade"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml_orb_5m.src.features.price_action import extract_price_action_features
import pandas as pd

# Load first few trades
trades_path = Path(__file__).parent.parent / "orb_5m" / "results" / "results_combined_top20" / "all_trades.csv"
trades = pd.read_csv(trades_path, parse_dates=['date', 'entry_time', 'exit_time'])

print("First 5 trades:")
print(trades[['symbol', 'date', 'entry_time', 'net_pnl']].head())
print()

# Test first trade
first_trade = trades.iloc[0]
symbol = first_trade['symbol']
date = first_trade['date']

print(f"Testing: {symbol} on {date}")
print(f"Date type: {type(date)}")
print()

# Check if data files exist
data_dir = Path(__file__).parent.parent / "data" / "processed"
min5_path = data_dir / "5min" / f"{symbol}.parquet"
daily_path = data_dir / "daily" / f"{symbol}.parquet"

print(f"5min file exists: {min5_path.exists()}")
print(f"Daily file exists: {daily_path.exists()}")
print()

# Try to load and inspect the data
if min5_path.exists():
    df5m = pd.read_parquet(min5_path)
    print(f"5min data shape: {df5m.shape}")
    print(f"5min columns: {df5m.columns.tolist()}")
    print(f"5min date range: {df5m.index.min()} to {df5m.index.max()}")
    print(f"5min index type: {type(df5m.index)}")
    print()
    
    # Check if our date exists
    if hasattr(df5m.index, 'date'):
        dates_in_data = df5m.index.date
        target_date = pd.to_datetime(date).date()
        print(f"Target date: {target_date}")
        print(f"Date in data: {target_date in dates_in_data}")
        
        # Show nearby dates
        print("\nFirst 10 dates in 5min data:")
        print(pd.Series(dates_in_data).unique()[:10])

print()
print("=" * 80)
print("Running extract_price_action_features...")
print("=" * 80)

result = extract_price_action_features(symbol, date, str(data_dir))
print(f"\nResult type: {type(result)}")
print(f"Result: {result}")
