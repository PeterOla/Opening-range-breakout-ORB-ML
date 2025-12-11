import pandas as pd
from pathlib import Path

# Define runs
runs = [
    {'name': 'Micro (<50M)', 'path': 'compound_top20_micro'},
    {'name': 'Small (50-150M)', 'path': 'compound_top20_small'},
    {'name': 'Large (>150M)', 'path': 'compound_top20_large'},
    {'name': 'All', 'path': 'test_compound_atr_stop'}
]

base_dir = Path('data/backtest')
results = []

for run in runs:
    yearly_path = base_dir / run['path'] / 'yearly_results.parquet'
    trades_path = base_dir / run['path'] / 'simulated_trades.parquet'
    
    if yearly_path.exists() and trades_path.exists():
        # Load data
        df_yearly = pd.read_parquet(yearly_path)
        df_trades = pd.read_parquet(trades_path)
        
        # Calculate metrics
        final_equity = df_yearly.iloc[-1]['end_equity']
        total_return = ((final_equity - 1000) / 1000) * 100
        
        entered = df_trades[df_trades['exit_reason'] != 'NO_ENTRY']
        win_rate = len(entered[entered['pnl_pct'] > 0]) / len(entered) * 100
        
        gross_profit = entered[entered['pnl_pct'] > 0]['base_dollar_pnl'].sum()
        gross_loss = abs(entered[entered['pnl_pct'] < 0]['base_dollar_pnl'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0
        
        # Yearly returns
        y2021 = df_yearly[df_yearly['year'] == 2021]['year_return_pct'].values[0] if not df_yearly[df_yearly['year'] == 2021].empty else 0
        y2022 = df_yearly[df_yearly['year'] == 2022]['year_return_pct'].values[0] if not df_yearly[df_yearly['year'] == 2022].empty else 0
        y2023 = df_yearly[df_yearly['year'] == 2023]['year_return_pct'].values[0] if not df_yearly[df_yearly['year'] == 2023].empty else 0
        y2024 = df_yearly[df_yearly['year'] == 2024]['year_return_pct'].values[0] if not df_yearly[df_yearly['year'] == 2024].empty else 0
        y2025 = df_yearly[df_yearly['year'] == 2025]['year_return_pct'].values[0] if not df_yearly[df_yearly['year'] == 2025].empty else 0
        
        results.append({
            'Universe': run['name'],
            'Final Equity ($)': f"${final_equity:,.0f}",
            'Total Return': f"{total_return:,.0f}%",
            'Win Rate': f"{win_rate:.1f}%",
            'Profit Factor': f"{profit_factor:.2f}",
            '2021': f"{y2021:+.0f}%",
            '2022': f"{y2022:+.0f}%",
            '2023': f"{y2023:+.0f}%",
            '2024': f"{y2024:+.0f}%",
            '2025': f"{y2025:+.0f}%"
        })

# Create DataFrame
df_results = pd.DataFrame(results)
print(df_results.to_markdown(index=False))

# Save to file
with open('data/backtest/comparison_summary.md', 'w') as f:
    f.write("# Strategy Comparison: Top 20 ORB (10% ATR Stop)\n\n")
    f.write(df_results.to_markdown(index=False))
