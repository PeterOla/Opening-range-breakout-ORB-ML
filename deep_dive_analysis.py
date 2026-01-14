import pandas as pd
import numpy as np
import os
import calendar

def get_max_consecutive_losses(trades_df):
    if trades_df.empty or 'pnl_net' not in trades_df.columns:
        return 0
    
    # Create boolean series: True if loss, False if win/breakeven
    is_loss = trades_df['pnl_net'] < 0
    
    # Group consecutive True values
    # cumsum() increments every time the value changes. 
    # By separating groups of True/False, we can count the size of True groups.
    # We want groups where is_loss is True.
    groups = is_loss.ne(is_loss.shift()).cumsum()
    
    # Filter for only loss groups and get counts
    loss_streaks = is_loss[is_loss].groupby(groups).count()
    
    if loss_streaks.empty:
        return 0
    return loss_streaks.max()

def get_max_consecutive_losing_days(daily_df):
    if daily_df.empty or 'pnl' not in daily_df.columns:
        return 0
    
    # Analyze daily PnL
    is_loss = daily_df['pnl'] < 0
    groups = is_loss.ne(is_loss.shift()).cumsum()
    loss_streaks = is_loss[is_loss].groupby(groups).count()
    
    if loss_streaks.empty:
        return 0
    return loss_streaks.max()

def analyze_run(run_path, label):
    daily_path = os.path.join(run_path, "daily_performance.parquet")
    trades_path = os.path.join(run_path, "simulated_trades.parquet")
    
    if not os.path.exists(daily_path) or not os.path.exists(trades_path):
        print(f"Missing data for {label}")
        return None

    daily_df = pd.read_parquet(daily_path)
    trades_df = pd.read_parquet(trades_path)
    
    daily_df['date'] = pd.to_datetime(daily_df['date'])
    daily_df['month'] = daily_df['date'].dt.month
    daily_df['day_name'] = daily_df['date'].dt.day_name()
    daily_df['pnl'] = daily_df['total_leveraged_pnl'] # Use leveraged PnL for compound results
    
    # 1. Monthly Returns (Ensure all months present)
    monthly_pnl = daily_df.groupby('month')['pnl'].sum()
    monthly_pnl_dict = {calendar.month_abbr[m]: v for m, v in monthly_pnl.items()}
    
    # 2. Day of Week Analysis
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    day_stats = daily_df.groupby('day_name')['pnl'].agg(['sum', 'mean', 'count'])
    day_stats = day_stats.reindex(days_order)
    
    # 3. Streaks
    max_losing_streak_trades = get_max_consecutive_losses(trades_df)
    max_losing_streak_days = get_max_consecutive_losing_days(daily_df)
    
    # 4. Other Decision Metrics
    avg_win = trades_df[trades_df['pnl_net'] > 0]['pnl_net'].mean() if not trades_df[trades_df['pnl_net'] > 0].empty else 0
    avg_loss = trades_df[trades_df['pnl_net'] < 0]['pnl_net'].mean() if not trades_df[trades_df['pnl_net'] < 0].empty else 0
    
    return {
        "label": label,
        "max_consecutive_losses": max_losing_streak_trades,
        "max_consecutive_losing_days": max_losing_streak_days,
        "monthly_pnl": monthly_pnl_dict,
        "day_stats": day_stats,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_profit": daily_df['pnl'].sum()
    }

def print_comparison(run1, run2):
    print(f"\n{'Metric':<25} | {run1['label']:<25} | {run2['label']:<25}")
    print("-" * 80)
    
    # General Stats
    print(f"{'Total Profit':<25} | ${run1['total_profit']:<24,.0f} | ${run2['total_profit']:<24,.0f}")
    print(f"{'Avg Win':<25} | ${run1['avg_win']:<24,.0f} | ${run2['avg_win']:<24,.0f}")
    print(f"{'Avg Loss':<25} | ${run1['avg_loss']:<24,.0f} | ${run2['avg_loss']:<24,.0f}")
    print(f"{'Max Consec. Loss (Trds)':<25} | {run1['max_consecutive_losses']:<25} | {run2['max_consecutive_losses']:<25}")
    print(f"{'Max Consec. Loss (Days)':<25} | {run1['max_consecutive_losing_days']:<25} | {run2['max_consecutive_losing_days']:<25}")
    
    print("-" * 80)
    print(f"Monthly Returns (2021)")
    print("-" * 80)
    all_months = list(calendar.month_abbr)[1:]
    for m in all_months:
        v1 = run1['monthly_pnl'].get(m, 0)
        v2 = run2['monthly_pnl'].get(m, 0)
        print(f"{m:<25} | ${v1:<24,.0f} | ${v2:<24,.0f}")

    print("-" * 80)
    print(f"Performance by Day of Week (Total PnL)")
    print("-" * 80)
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    for d in days:
        v1 = run1['day_stats'].loc[d, 'sum'] if d in run1['day_stats'].index else 0
        v2 = run2['day_stats'].loc[d, 'sum'] if d in run2['day_stats'].index else 0
        print(f"{d:<25} | ${v1:<24,.0f} | ${v2:<24,.0f}")
        
    print("-" * 80)
    print(f"Best Day (Mean PnL/Day)")
    print("-" * 80)
    for d in days:
        v1 = run1['day_stats'].loc[d, 'mean'] if d in run1['day_stats'].index else 0
        v2 = run2['day_stats'].loc[d, 'mean'] if d in run2['day_stats'].index else 0
        print(f"{d:<25} | ${v1:<24,.0f} | ${v2:<24,.0f}")

# Main Execution
base_path = r"C:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\runs\compound"

# Examining the "Sweet Spot" 0.90 Threshold
run_top20 = analyze_run(os.path.join(base_path, "Sent_First_2021_Thresh_0.9"), "Top 20 (> 0.90)")
run_top5 = analyze_run(os.path.join(base_path, "Sent_Top5_2021_Thresh_0.9"), "Top 5 (> 0.90)")

if run_top20 and run_top5:
    print_comparison(run_top20, run_top5)
