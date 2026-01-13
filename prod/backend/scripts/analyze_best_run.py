import pandas as pd
import numpy as np
import warnings
from datetime import datetime

# Suppress warnings
warnings.filterwarnings('ignore')

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_DIR = r"c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)"
RUN_FOLDER = "batch_long_top10_micro_small"
TRADES_FILE = f"{BASE_DIR}\\data\\backtest\\orb\\runs\\compound\\{RUN_FOLDER}\\simulated_trades.parquet"
DAILY_FILE = f"{BASE_DIR}\\data\\backtest\\orb\\runs\\compound\\{RUN_FOLDER}\\daily_performance.parquet"
YEARLY_FILE = f"{BASE_DIR}\\data\\backtest\\orb\\runs\\compound\\{RUN_FOLDER}\\yearly_results.parquet"

def print_header(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def load_data():
    try:
        trades = pd.read_parquet(TRADES_FILE)
        daily = pd.read_parquet(DAILY_FILE)
        yearly = pd.read_parquet(YEARLY_FILE)
        
        # Get start equity
        start_equity = yearly.iloc[0]['start_equity']
        
        # Ensure dates are datetime objects
        if 'trade_date' in trades.columns:
            trades['date'] = pd.to_datetime(trades['trade_date'])
        elif 'entry_date' in trades.columns:
            trades['date'] = pd.to_datetime(trades['entry_date'])
        
        if 'date' in daily.columns:
            daily['date'] = pd.to_datetime(daily['date'])
        
        daily.set_index('date', inplace=True)
        
        # Standardize Daily Column Names
        if 'total_leveraged_pnl' in daily.columns:
            daily['daily_pnl'] = daily['total_leveraged_pnl']
        else:
            daily['daily_pnl'] = daily['daily_pnl'] # Assume exists if logic fails?
            
        # Reconstruct Equity Curve
        daily['equity'] = start_equity + daily['daily_pnl'].cumsum()
        
        return trades, daily
    except Exception as e:
        print(f"Error loading files: {e}")
        return None, None

def analyze_streaks(series, condition_func):
    """
    Analyzes streaks where condition_func(value) is True.
    Returns: Max Streak, Average Streak Count
    """
    bool_series = series.apply(condition_func)
    blocks = (bool_series != bool_series.shift()).cumsum()
    streaks = bool_series.groupby(blocks).apply(lambda x: len(x) if x.iloc[0] else 0)
    true_streaks = streaks[streaks > 0]
    
    if len(true_streaks) == 0:
        return 0, 0.0
        
    return true_streaks.max(), true_streaks.mean()

def analyze_monthly(daily):
    # Resample to Monthly
    monthly = daily.resample('M').agg({
        'daily_pnl': 'sum',
        'equity': 'last' # Closing equity of the month
    })
    
    # Calculate Monthly Return (%)
    monthly['prev_equity'] = monthly['equity'].shift(1)
    
    # Handle the first month separately to avoid NaN
    if not monthly.empty:
        # Reconstruct theoretical start equity for that month
        start_equity = daily['equity'].iloc[0] - daily['daily_pnl'].iloc[0]
        monthly.iloc[0, monthly.columns.get_loc('prev_equity')] = start_equity
    
    monthly['pct_return'] = (monthly['daily_pnl'] / monthly['prev_equity']) * 100
    
    print_header("Month-by-Month Analysis")
    print(f"{'Year-Month':<12} | {'Net Profit ($)':>15} | {'Return (%)':>10}")
    print("-" * 45)
    
    for date, row in monthly.iterrows():
        pnl_str = f"${row['daily_pnl']:,.2f}"
        ret_str = f"{row['pct_return']:>.2f}%"
        print(f"{date.strftime('%Y-%m'):<12} | {pnl_str:>15} | {ret_str:>10}")

    if not monthly.empty:
        best_month = monthly.loc[monthly['daily_pnl'].idxmax()]
        worst_month = monthly.loc[monthly['daily_pnl'].idxmin()]
        
        print("-" * 45)
        print(f"Best Month:  {best_month.name.strftime('%Y-%m')} (${best_month['daily_pnl']:,.2f})")
        print(f"Worst Month: {worst_month.name.strftime('%Y-%m')} (${worst_month['daily_pnl']:,.2f})")

def analyze_day_of_week(trades):
    # 0=Monday, 6=Sunday
    trades['dow'] = trades['date'].dt.day_name()
    trades['dow_idx'] = trades['date'].dt.dayofweek
    
    grouped = trades.groupby(['dow_idx', 'dow'])
    
    dow_stats = pd.DataFrame({
        'Total Profit': grouped['dollar_pnl'].sum(),
        'Avg Profit': grouped['dollar_pnl'].mean(),
        'Trade Count': grouped['ticker'].count()
    })
    
    win_counts = trades[trades['dollar_pnl'] > 0].groupby(['dow_idx', 'dow'])['ticker'].count()
    total_counts = grouped['ticker'].count()
    win_counts = win_counts.reindex(total_counts.index, fill_value=0)
    
    dow_stats['Win Rate'] = (win_counts / total_counts) * 100
    
    print_header("Day of Week Performance")
    print(f"{'Day':<10} | {'Trades':>8} | {'Win Rate':>8} | {'Total Profit ($)':>18} | {'Avg Profit ($)':>15}")
    print("-" * 70)
    
    for idx, row in dow_stats.iterrows():
        day_name = idx[1]
        print(f"{day_name:<10} | {row['Trade Count']:>8.0f} | {row['Win Rate']:>7.1f}% | {row['Total Profit']:>18,.2f} | {row['Avg Profit']:>15.2f}")

def analyze_daily_activity(trades):
    trades_per_day = trades.groupby('date')['ticker'].count()
    
    print_header("Daily Trading Activity")
    print(f"Average Trades/Day: {trades_per_day.mean():.2f}")
    print(f"Median Trades/Day:  {trades_per_day.median():.0f}")
    print(f"Max Trades/Day:     {trades_per_day.max()}")
    print(f"Min Trades/Day:     {trades_per_day.min()}") 

def analyze_streaks_report(trades, daily):
    print_header("Streak Analysis (Survival Metrics)")
    
    # Trade Streaks
    max_win_streak, avg_win_streak = analyze_streaks(trades['dollar_pnl'], lambda x: x > 0)
    max_loss_streak, avg_loss_streak = analyze_streaks(trades['dollar_pnl'], lambda x: x <= 0)
    
    print("--- Individual Trades ---")
    print(f"Max Consecutive Wins:   {max_win_streak}")
    print(f"Avg Consecutive Wins:   {avg_win_streak:.2f}")
    print(f"Max Consecutive Losses: {max_loss_streak}")
    print(f"Avg Consecutive Losses: {avg_loss_streak:.2f}")
    
    # Daily Streaks
    max_win_days, avg_win_days = analyze_streaks(daily['daily_pnl'], lambda x: x > 0)
    max_loss_days, avg_loss_days = analyze_streaks(daily['daily_pnl'], lambda x: x <= 0)
    
    print("\n--- Daily PnL ---")
    print(f"Max Consecutive Winning Days: {max_win_days}")
    print(f"Avg Consecutive Winning Days: {avg_win_days:.2f}")
    print(f"Max Consecutive Losing Days:  {max_loss_days}")
    print(f"Avg Consecutive Losing Days:  {avg_loss_days:.2f}")

def calculate_drawdown(daily):
    daily['hwm'] = daily['equity'].cummax()
    daily['drawdown'] = daily['equity'] - daily['hwm']
    daily['drawdown_pct'] = (daily['drawdown'] / daily['hwm']) * 100
    
    max_dd_dollar = daily['drawdown'].min()
    max_dd_pct = daily['drawdown_pct'].min()
    
    at_hwm = daily['drawdown'] == 0
    is_drawdown = ~at_hwm
    if is_drawdown.any():
        blocks = (is_drawdown != is_drawdown.shift()).cumsum()
        dd_durations = is_drawdown.groupby(blocks).sum()
        true_dd_blocks = dd_durations[is_drawdown.groupby(blocks).first()]
        if not true_dd_blocks.empty:
            max_duration_days = true_dd_blocks.max()
        else:
            max_duration_days = 0
    else:
        max_duration_days = 0
    
    print_header("Drawdown Analysis")
    print(f"Max Drawdown ($):   ${max_dd_dollar:,.2f}")
    print(f"Max Drawdown (%):   {max_dd_pct:.2f}%")
    print(f"Longest Recovery:   {max_duration_days} days (Trading Days)")
    
    current_dd = daily['drawdown_pct'].iloc[-1]
    print(f"Current Drawdown:   {current_dd:.2f}%")

def main():
    print(f"Analyzing Run: {RUN_FOLDER}")
    trades, daily = load_data()
    
    if trades is None:
        return

    total_trades = len(trades)
    win_rate = (len(trades[trades['dollar_pnl'] > 0]) / total_trades) * 100
    profit_factor = trades[trades['dollar_pnl'] > 0]['dollar_pnl'].sum() / abs(trades[trades['dollar_pnl'] < 0]['dollar_pnl'].sum())
    
    print_header("Executive Summary")
    print(f"Total Trades:       {total_trades}")
    print(f"Win Rate:           {win_rate:.2f}%")
    print(f"Profit Factor:      {profit_factor:.2f}")
    print(f"Final Equity:       ${daily['equity'].iloc[-1]:,.2f}")
    print(f"Total Net Profit:   ${daily['daily_pnl'].sum():,.2f}")
    
    analyze_monthly(daily)
    analyze_day_of_week(trades)
    analyze_daily_activity(trades)
    analyze_streaks_report(trades, daily)
    calculate_drawdown(daily)

if __name__ == "__main__":
    main()
