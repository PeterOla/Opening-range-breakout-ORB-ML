import pandas as pd
import numpy as np
from pathlib import Path

# Paths
RUN_DIR = Path(r'c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\runs\compound\5year_micro_small_top5_compound')
DAILY_FILE = RUN_DIR / 'daily_performance.parquet'
REPORT_DIR = RUN_DIR / 'reports'
REPORT_DIR.mkdir(exist_ok=True)

# Load data
try:
    daily = pd.read_parquet(DAILY_FILE)
except FileNotFoundError as e:
    print(f"Error loading files: {e}")
    exit(1)

# --- Preprocessing ---
daily['date'] = pd.to_datetime(daily['date'])
daily['pnl'] = daily['total_leveraged_pnl']
daily['win_rate'] = (daily['winners'] / daily['trades']).fillna(0) * 100

# Add time features
daily['year'] = daily['date'].dt.year
daily['month_name'] = daily['date'].dt.month_name()
daily['day_name'] = daily['date'].dt.day_name()
daily['month_num'] = daily['date'].dt.month
daily['day_num'] = daily['date'].dt.dayofweek  # 0=Monday, 6=Sunday

# --- Aggregations ---

# 1. Yearly
yearly_stats = daily.groupby('year').agg(
    total_pnl=('pnl', 'sum'),
    avg_daily_pnl=('pnl', 'mean'),
    avg_win_rate=('win_rate', 'mean'),
    trading_days=('date', 'count')
).reset_index()

# 2. Monthly (Seasonality across all years)
monthly_stats = daily.groupby('month_name').agg(
    avg_daily_pnl=('pnl', 'mean'),
    total_pnl=('pnl', 'sum'),
    avg_win_rate=('win_rate', 'mean'),
    trading_days=('date', 'count'),
    month_num=('month_num', 'first')
).sort_values('month_num').reset_index()

# 3. Day of Week
daily_stats = daily.groupby('day_name').agg(
    avg_daily_pnl=('pnl', 'mean'),
    total_pnl=('pnl', 'sum'),
    avg_win_rate=('win_rate', 'mean'),
    trading_days=('date', 'count'),
    day_num=('day_num', 'first')
).sort_values('day_num').reset_index()

# --- Deep Dives ---

# 4. March Breakdown (Is it always bad?)
march_data = daily[daily['month_num'] == 3].copy()
march_yearly = march_data.groupby('year').agg(
    total_pnl=('pnl', 'sum'),
    avg_daily_pnl=('pnl', 'mean'),
    avg_win_rate=('win_rate', 'mean'),
    trading_days=('date', 'count')
).reset_index()

# 5. Streak Analysis
daily['is_win'] = daily['pnl'] > 0
# Identify groups of consecutive values
daily['streak_group'] = (daily['is_win'] != daily['is_win'].shift()).cumsum()
# Count size of each group
streak_counts = daily.groupby(['streak_group', 'is_win']).size().reset_index(name='count')

max_win_streak = streak_counts[streak_counts['is_win'] == True]['count'].max()
max_loss_streak = streak_counts[streak_counts['is_win'] == False]['count'].max()
avg_win_streak = streak_counts[streak_counts['is_win'] == True]['count'].mean()
avg_loss_streak = streak_counts[streak_counts['is_win'] == False]['count'].mean()

# Create Streak DataFrame
streak_stats = pd.DataFrame([{
    'metric': 'Max Consecutive Winning Days',
    'value': max_win_streak
}, {
    'metric': 'Max Consecutive Losing Days',
    'value': max_loss_streak
}, {
    'metric': 'Avg Winning Streak (Days)',
    'value': round(avg_win_streak, 2)
}, {
    'metric': 'Avg Losing Streak (Days)',
    'value': round(avg_loss_streak, 2)
}])

# --- Save to CSV ---
yearly_stats.to_csv(REPORT_DIR / 'breakdown_yearly.csv', index=False)
monthly_stats.drop(columns=['month_num']).to_csv(REPORT_DIR / 'breakdown_monthly_seasonality.csv', index=False)
daily_stats.drop(columns=['day_num']).to_csv(REPORT_DIR / 'breakdown_day_of_week.csv', index=False)
march_yearly.to_csv(REPORT_DIR / 'breakdown_march_yearly.csv', index=False)
streak_stats.to_csv(REPORT_DIR / 'breakdown_streaks.csv', index=False)

# --- Generate Markdown Report ---
md_content = f"""# 5-Year Backtest Analysis (2021-2025)
**Strategy:** Micro+Small | Top 5 | Both Sides | Compounding

## 1. Yearly Performance
| Year | Total P&L | Avg Daily P&L | Avg Win Rate | Trading Days |
|------|-----------|---------------|--------------|--------------|
"""

for _, row in yearly_stats.iterrows():
    md_content += f"| {row['year']} | ${row['total_pnl']:,.2f} | ${row['avg_daily_pnl']:,.2f} | {row['avg_win_rate']:.1f}% | {row['trading_days']} |\n"

md_content += """
## 2. Monthly Seasonality (Aggregated)
| Month | Avg Daily P&L | Total P&L | Avg Win Rate | Trading Days |
|-------|---------------|-----------|--------------|--------------|
"""

for _, row in monthly_stats.iterrows():
    md_content += f"| {row['month_name']} | ${row['avg_daily_pnl']:,.2f} | ${row['total_pnl']:,.2f} | {row['avg_win_rate']:.1f}% | {row['trading_days']} |\n"

md_content += """
## 3. Day of Week Performance
| Day | Avg Daily P&L | Total P&L | Avg Win Rate | Trading Days |
|-----|---------------|-----------|--------------|--------------|
"""

for _, row in daily_stats.iterrows():
    md_content += f"| {row['day_name']} | ${row['avg_daily_pnl']:,.2f} | ${row['total_pnl']:,.2f} | {row['avg_win_rate']:.1f}% | {row['trading_days']} |\n"

md_content += """
## 4. March Deep Dive (Year by Year)
| Year | Total P&L | Avg Daily P&L | Avg Win Rate | Trading Days |
|------|-----------|---------------|--------------|--------------|
"""

for _, row in march_yearly.iterrows():
    md_content += f"| {row['year']} | ${row['total_pnl']:,.2f} | ${row['avg_daily_pnl']:,.2f} | {row['avg_win_rate']:.1f}% | {row['trading_days']} |\n"

md_content += f"""
## 5. Streak Analysis
*   **Max Consecutive Winning Days:** {max_win_streak}
*   **Max Consecutive Losing Days:** {max_loss_streak}
*   **Avg Winning Streak:** {avg_win_streak:.1f} days
*   **Avg Losing Streak:** {avg_loss_streak:.1f} days
"""

md_path = REPORT_DIR / '5year_analysis_report.md'
md_path.write_text(md_content, encoding='utf-8')

print(f"Reports saved to: {REPORT_DIR}")
print(f" - {REPORT_DIR / 'breakdown_yearly.csv'}")
print(f" - {REPORT_DIR / 'breakdown_monthly_seasonality.csv'}")
print(f" - {REPORT_DIR / 'breakdown_day_of_week.csv'}")
print(f" - {REPORT_DIR / 'breakdown_march_yearly.csv'}")
print(f" - {md_path}")
