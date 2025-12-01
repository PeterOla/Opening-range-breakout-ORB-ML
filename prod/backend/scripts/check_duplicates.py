"""Check for duplicates in backtest output files."""
import pandas as pd

print("=" * 60)
print("CHECKING SIMULATED_TRADES.PARQUET FOR DUPLICATES")
print("=" * 60)

trades = pd.read_parquet('data/backtest/simulated_trades.parquet')
print(f"\nTotal rows: {len(trades)}")

# Check for exact duplicates
exact_dups = trades.duplicated(keep=False)
print(f"Exact duplicate rows: {exact_dups.sum()}")

# Check for duplicate (date, ticker, side) combinations
key_cols = ['trade_date', 'ticker', 'side']
unique_keys = trades.drop_duplicates(subset=key_cols)
print(f"\nUnique (date, ticker, side) combinations: {len(unique_keys)}")
print(f"Duplicate keys: {len(trades) - len(unique_keys)}")

if len(trades) > len(unique_keys):
    print("\n" + "=" * 60)
    print("DUPLICATE ENTRIES FOUND!")
    print("=" * 60)
    
    # Show duplicates
    dups = trades[trades.duplicated(subset=key_cols, keep=False)].sort_values(key_cols)
    print(f"\nTotal duplicate rows: {len(dups)}")
    
    print("\nSample duplicates:")
    print(dups[['trade_date', 'ticker', 'side', 'rvol_rank', 'entry_price', 
                'exit_price', 'pnl_pct', 'entry_time', 'exit_time']].head(20))
    
    # Group to see how many times each key appears
    print("\nDuplicate frequency:")
    dup_counts = trades.groupby(key_cols).size()
    dup_counts = dup_counts[dup_counts > 1].sort_values(ascending=False)
    print(dup_counts.head(10))
else:
    print("\n✅ No duplicates found!")

print("\n" + "=" * 60)
print("CHECKING DAILY_PERFORMANCE.PARQUET")
print("=" * 60)

daily = pd.read_parquet('data/backtest/daily_performance.parquet')
print(f"\nTotal rows: {len(daily)}")
print(f"Unique dates: {daily['date'].nunique()}")

if len(daily) > daily['date'].nunique():
    print("\n⚠️  Duplicate dates found!")
    dup_dates = daily[daily.duplicated(subset=['date'], keep=False)].sort_values('date')
    print(dup_dates)
else:
    print("✅ No duplicate dates!")

print("\nDaily performance summary:")
print(daily)
