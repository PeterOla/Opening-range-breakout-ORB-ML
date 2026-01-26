"""
Deep Analysis: 5% ATR vs 10% ATR Stops
Comprehensive breakdown of backtest performance
"""

import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

# Load data
base = Path(__file__).resolve().parents[4]
trades_5 = pd.read_parquet(base / 'data/backtest/orb/runs/compound/ROLLING24H_Sent_090_Top5_5ATR/simulated_trades.parquet')
trades_10 = pd.read_parquet(base / 'data/backtest/orb/runs/compound/ROLLING24H_Sent_090_Top5_10ATR/simulated_trades.parquet')
daily_5 = pd.read_parquet(base / 'data/backtest/orb/runs/compound/ROLLING24H_Sent_090_Top5_5ATR/daily_performance.parquet')
daily_10 = pd.read_parquet(base / 'data/backtest/orb/runs/compound/ROLLING24H_Sent_090_Top5_10ATR/daily_performance.parquet')

print("=" * 100)
print("DEEP DIVE ANALYSIS: 5% ATR vs 10% ATR STOPS")
print("=" * 100)

# Prepare trade data
for df in [trades_5, trades_10]:
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df['day_of_week'] = df['trade_date'].dt.day_name()
    df['month'] = df['trade_date'].dt.month_name()
    df['month_num'] = df['trade_date'].dt.month
    df['quarter'] = df['trade_date'].dt.quarter
    df['year'] = df['trade_date'].dt.year
    df['is_winner'] = df['pnl_net'] > 0
    df['r_multiple'] = df['pnl_gross'] / (df['entry_price'] * df['shares'] * df['stop_distance_pct'] / 100)
    
    # Entry time hour
    df['entry_hour'] = pd.to_datetime(df['entry_time']).dt.hour
    df['entry_minute'] = pd.to_datetime(df['entry_time']).dt.minute
    
    # Hold time (minutes)
    df['hold_minutes'] = (pd.to_datetime(df['exit_time']) - pd.to_datetime(df['entry_time'])).dt.total_seconds() / 60

# Prepare daily data
for df in [daily_5, daily_10]:
    df['date'] = pd.to_datetime(df['date'])
    df['day_of_week'] = df['date'].dt.day_name()
    df['is_positive'] = df['total_leveraged_pnl'] > 0
    df['month'] = df['date'].dt.month
    df['year'] = df['date'].dt.year

results = {}

# ============================================================================
# 1. STREAK ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("1. STREAK ANALYSIS")
print("=" * 100)

def calc_streaks(df):
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['streak_id'] = (df['is_winner'] != df['is_winner'].shift()).cumsum()
    streaks = df.groupby('streak_id').agg({'is_winner': ['first', 'count']}).reset_index()
    streaks.columns = ['sid', 'is_win', 'length']
    win_streaks = streaks[streaks['is_win'] == True]['length'].tolist()
    loss_streaks = streaks[streaks['is_win'] == False]['length'].tolist()
    return {
        'max_win': max(win_streaks) if win_streaks else 0,
        'max_loss': max(loss_streaks) if loss_streaks else 0,
        'avg_win': np.mean(win_streaks) if win_streaks else 0,
        'avg_loss': np.mean(loss_streaks) if loss_streaks else 0
    }

def calc_daily_streaks(df):
    df = df.sort_values('date').reset_index(drop=True)
    df['streak_id'] = (df['is_positive'] != df['is_positive'].shift()).cumsum()
    streaks = df.groupby('streak_id').agg({'is_positive': ['first', 'count']}).reset_index()
    streaks.columns = ['sid', 'is_pos', 'length']
    win_days = streaks[streaks['is_pos'] == True]['length'].tolist()
    loss_days = streaks[streaks['is_pos'] == False]['length'].tolist()
    return max(win_days) if win_days else 0, max(loss_days) if loss_days else 0

s5 = calc_streaks(trades_5)
s10 = calc_streaks(trades_10)
dw5, dl5 = calc_daily_streaks(daily_5)
dw10, dl10 = calc_daily_streaks(daily_10)

results['streaks'] = {
    '5_pct': {'trade': s5, 'daily_win': dw5, 'daily_loss': dl5},
    '10_pct': {'trade': s10, 'daily_win': dw10, 'daily_loss': dl10}
}

print("\n5% ATR:")
print(f"  Max win streak: {s5['max_win']} trades | Max loss streak: {s5['max_loss']} trades")
print(f"  Max win days: {dw5} | Max loss days: {dl5}")

print("\n10% ATR:")
print(f"  Max win streak: {s10['max_win']} trades | Max loss streak: {s10['max_loss']} trades")
print(f"  Max win days: {dw10} | Max loss days: {dl10}")

# ============================================================================
# 2. DAY OF WEEK
# ============================================================================
print("\n" + "=" * 100)
print("2. DAY OF WEEK ANALYSIS")
print("=" * 100)

dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

print("\n5% ATR - Trade Performance by Day:")
dow_5 = trades_5.groupby('day_of_week').agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean'
})
print(dow_5.reindex(dow_order).to_string())

print("\n10% ATR - Trade Performance by Day:")
dow_10 = trades_10.groupby('day_of_week').agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean'
})
print(dow_10.reindex(dow_order).to_string())

results['day_of_week'] = {
    '5_pct': dow_5.reindex(dow_order).to_dict(),
    '10_pct': dow_10.reindex(dow_order).to_dict()
}

# ============================================================================
# 3. PRICE RANGE ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("3. STOCK PRICE RANGE ANALYSIS")
print("=" * 100)

for df in [trades_5, trades_10]:
    df['price_bucket'] = pd.cut(df['entry_price'], 
                                  bins=[0, 1, 2, 5, 10, 20, 50, 1000],
                                  labels=['<$1', '$1-2', '$2-5', '$5-10', '$10-20', '$20-50', '>$50'])

print("\n5% ATR - By Entry Price:")
price_5 = trades_5.groupby('price_bucket', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(price_5.to_string())

print("\n10% ATR - By Entry Price:")
price_10 = trades_10.groupby('price_bucket', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(price_10.to_string())

results['price_ranges'] = {
    '5_pct': price_5.to_dict(),
    '10_pct': price_10.to_dict()
}

# ============================================================================
# 4. RVOL RANGE ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("4. RVOL RANGE ANALYSIS")
print("=" * 100)

for df in [trades_5, trades_10]:
    df['rvol_bucket'] = pd.cut(df['rvol'], 
                                 bins=[0, 2, 3, 4, 5, 10, 1000],
                                 labels=['<2', '2-3', '3-4', '4-5', '5-10', '>10'])

print("\n5% ATR - By RVOL:")
rvol_5 = trades_5.groupby('rvol_bucket', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(rvol_5.to_string())

print("\n10% ATR - By RVOL:")
rvol_10 = trades_10.groupby('rvol_bucket', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(rvol_10.to_string())

results['rvol_ranges'] = {
    '5_pct': rvol_5.to_dict(),
    '10_pct': rvol_10.to_dict()
}

# ============================================================================
# 5. ATR RANGE ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("5. ATR (VOLATILITY) RANGE ANALYSIS")
print("=" * 100)

for df in [trades_5, trades_10]:
    df['atr_bucket'] = pd.cut(df['atr_14'], 
                                bins=[0, 0.5, 1.0, 2.0, 5.0, 1000],
                                labels=['0.5-1.0', '1.0-2.0', '2.0-5.0', '>5.0', 'Extreme'])

print("\n5% ATR - By Stock ATR:")
atr_5 = trades_5.groupby('atr_bucket', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(atr_5.to_string())

print("\n10% ATR - By Stock ATR:")
atr_10 = trades_10.groupby('atr_bucket', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(atr_10.to_string())

# ============================================================================
# 6. ENTRY TIMING ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("6. ENTRY TIMING ANALYSIS")
print("=" * 100)

for df in [trades_5, trades_10]:
    df['entry_period'] = pd.cut(df['entry_hour'] + df['entry_minute']/60, 
                                  bins=[9.5, 10, 11, 12, 14, 16],
                                  labels=['09:30-10:00', '10:00-11:00', '11:00-12:00', '12:00-14:00', '14:00-16:00'])

print("\n5% ATR - By Entry Time:")
entry_5 = trades_5.groupby('entry_period', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean'
})
print(entry_5.to_string())

print("\n10% ATR - By Entry Time:")
entry_10 = trades_10.groupby('entry_period', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean'
})
print(entry_10.to_string())

# ============================================================================
# 7. HOLD TIME ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("7. HOLD TIME ANALYSIS")
print("=" * 100)

for df in [trades_5, trades_10]:
    df['hold_bucket'] = pd.cut(df['hold_minutes'], 
                                 bins=[0, 30, 60, 120, 240, 500],
                                 labels=['<30min', '30-60min', '60-120min', '120-240min', '>240min'])

print("\n5% ATR - By Hold Time:")
hold_5 = trades_5.groupby('hold_bucket', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(hold_5.to_string())

print("\n10% ATR - By Hold Time:")
hold_10 = trades_10.groupby('hold_bucket', observed=True).agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(hold_10.to_string())

# ============================================================================
# 8. EXIT REASON BREAKDOWN
# ============================================================================
print("\n" + "=" * 100)
print("8. EXIT REASON ANALYSIS")
print("=" * 100)

print("\n5% ATR - Exit Reasons:")
exit_5 = trades_5.groupby('exit_reason').agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(exit_5.to_string())

print("\n10% ATR - Exit Reasons:")
exit_10 = trades_10.groupby('exit_reason').agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean',
    'pnl_pct': 'mean'
})
print(exit_10.to_string())

# ============================================================================
# 9. MONTHLY/QUARTERLY PERFORMANCE
# ============================================================================
print("\n" + "=" * 100)
print("9. MONTHLY PERFORMANCE")
print("=" * 100)

print("\n5% ATR - By Month:")
month_5 = trades_5.groupby('month_num').agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean'
})
print(month_5.to_string())

print("\n10% ATR - By Month:")
month_10 = trades_10.groupby('month_num').agg({
    'pnl_net': ['count', 'sum', 'mean'],
    'is_winner': 'mean'
})
print(month_10.to_string())

# ============================================================================
# 10. BEST/WORST TRADES
# ============================================================================
print("\n" + "=" * 100)
print("10. BEST & WORST TRADES")
print("=" * 100)

print("\n5% ATR - Top 10 Winners:")
top_5 = trades_5.nlargest(10, 'pnl_net')[['trade_date', 'ticker', 'entry_price', 'pnl_net', 'pnl_pct', 'rvol', 'exit_reason']]
print(top_5.to_string(index=False))

print("\n5% ATR - Top 10 Losers:")
worst_5 = trades_5.nsmallest(10, 'pnl_net')[['trade_date', 'ticker', 'entry_price', 'pnl_net', 'pnl_pct', 'rvol', 'exit_reason']]
print(worst_5.to_string(index=False))

print("\n10% ATR - Top 10 Winners:")
top_10 = trades_10.nlargest(10, 'pnl_net')[['trade_date', 'ticker', 'entry_price', 'pnl_net', 'pnl_pct', 'rvol', 'exit_reason']]
print(top_10.to_string(index=False))

print("\n10% ATR - Top 10 Losers:")
worst_10 = trades_10.nsmallest(10, 'pnl_net')[['trade_date', 'ticker', 'entry_price', 'pnl_net', 'pnl_pct', 'rvol', 'exit_reason']]
print(worst_10.to_string(index=False))

# ============================================================================
# 11. R-MULTIPLE ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("11. R-MULTIPLE ANALYSIS (Risk-Adjusted Returns)")
print("=" * 100)

print("\n5% ATR Stop:")
print(f"  Mean R: {trades_5['r_multiple'].mean():.2f}R")
print(f"  Median R: {trades_5['r_multiple'].median():.2f}R")
print(f"  Max R: {trades_5['r_multiple'].max():.2f}R")
print(f"  Min R: {trades_5['r_multiple'].min():.2f}R")
print(f"  Std Dev: {trades_5['r_multiple'].std():.2f}R")

print("\n10% ATR Stop:")
print(f"  Mean R: {trades_10['r_multiple'].mean():.2f}R")
print(f"  Median R: {trades_10['r_multiple'].median():.2f}R")
print(f"  Max R: {trades_10['r_multiple'].max():.2f}R")
print(f"  Min R: {trades_10['r_multiple'].min():.2f}R")
print(f"  Std Dev: {trades_10['r_multiple'].std():.2f}R")

# ============================================================================
# 12. WINNING vs LOSING TRADE STATS
# ============================================================================
print("\n" + "=" * 100)
print("12. WINNER vs LOSER COMPARISON")
print("=" * 100)

print("\n5% ATR Stop:")
winners_5 = trades_5[trades_5['is_winner'] == True]
losers_5 = trades_5[trades_5['is_winner'] == False]
print(f"  Winners: {len(winners_5)} | Avg P&L: ${winners_5['pnl_net'].mean():.2f} | Avg %: {winners_5['pnl_pct'].mean():.2f}%")
print(f"  Losers: {len(losers_5)} | Avg P&L: ${losers_5['pnl_net'].mean():.2f} | Avg %: {losers_5['pnl_pct'].mean():.2f}%")
print(f"  Winner/Loser ratio: {len(winners_5)/len(losers_5):.2f}")
print(f"  Avg winner / Avg loser: {abs(winners_5['pnl_net'].mean() / losers_5['pnl_net'].mean()):.2f}x")

print("\n10% ATR Stop:")
winners_10 = trades_10[trades_10['is_winner'] == True]
losers_10 = trades_10[trades_10['is_winner'] == False]
print(f"  Winners: {len(winners_10)} | Avg P&L: ${winners_10['pnl_net'].mean():.2f} | Avg %: {winners_10['pnl_pct'].mean():.2f}%")
print(f"  Losers: {len(losers_10)} | Avg P&L: ${losers_10['pnl_net'].mean():.2f} | Avg %: {losers_10['pnl_pct'].mean():.2f}%")
print(f"  Winner/Loser ratio: {len(winners_10)/len(losers_10):.2f}")
print(f"  Avg winner / Avg loser: {abs(winners_10['pnl_net'].mean() / losers_10['pnl_net'].mean()):.2f}x")

print("\n" + "=" * 100)
print("ANALYSIS COMPLETE")
print("=" * 100)
