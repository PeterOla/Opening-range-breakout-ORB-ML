import pandas as pd
from pathlib import Path
import sys

# root is 2 levels up from prod/backend
trades_path = Path("C:/Users/Olale/Documents/Codebase/Quant/Opening Range Breakout (ORB)/data/backtest/orb/runs/compound/opt_Exp5_StopTight_05/simulated_trades.parquet")

print(f"Reading: {trades_path}")
df = pd.read_parquet(trades_path)

print(f"Total Trades: {len(df)}")
print(f"Avg Stop Distance (%): {df['stop_distance_pct'].mean():.4f}%")
print(f"Median Stop Distance (%): {df['stop_distance_pct'].median():.4f}%")
print(f"Min Stop Distance (%): {df['stop_distance_pct'].min():.4f}%")

# Check versus Spread
SPREAD_PCT = 0.1  # 0.1% assumed in code
below_spread = df[df['stop_distance_pct'] < SPREAD_PCT]
print(f"Trades with Stop < Spread ({SPREAD_PCT}%): {len(below_spread)} ({len(below_spread)/len(df)*100:.1f}%)")

# Check PnL of these trades
print(f"PnL of trades with tight stops: ${below_spread['dollar_pnl'].sum():,.2f}")

# Check winners in this group (is it possible to win if stop < spread?)
winners = below_spread[below_spread['pnl_pct'] > 0]
print(f"Winners with Stop < Spread: {len(winners)}")
