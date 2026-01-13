import pandas as pd
from pathlib import Path

# Config
RUNS_DIR = Path("data/backtest/orb/runs/compound")
RUNS = [
    "news_v2_micro_tz",
    "news_v2_small_tz",
    "news_v2_micro_only_tz", # Typo in user request potentially, but we have news_v2_micro_tz
    "news_v2_micro_small_tz",
    "news_v2_micro_unknown_tz",
    "news_v2_micro_small_unknown_tz",
    "news_v2_large_tz",
    "news_v2_all_tz",
    "news_v2_unknown_tz"
]

def analyze_run(run_name):
    path = RUNS_DIR / run_name / "simulated_trades.parquet"
    if not path.exists():
        return None

    df = pd.read_parquet(path)
    df['year'] = pd.to_datetime(df['trade_date']).dt.year
    
    # 1. Overall Stats
    total_trades = len(df)
    entered = df[df['exit_reason'] != 'NO_ENTRY']
    
    if entered.empty:
        return None

    win_rate = (entered['pnl_pct'] > 0).mean() * 100
    
    # Prft Factor
    gross_win = entered[entered['pnl_pct'] > 0]['base_dollar_pnl'].sum()
    gross_loss = abs(entered[entered['pnl_pct'] < 0]['base_dollar_pnl'].sum())
    pf = gross_win / gross_loss if gross_loss > 0 else 0
    
    # Avg Trades Per Day
    daily_counts = entered.groupby('trade_date').size()
    avg_trades_day = daily_counts.mean()
    
    # Yearly Performance (Sum percent or just list equity?) 
    # Let's pull from yearly_results.parquet for clean Returns
    yearly_path = RUNS_DIR / run_name / "yearly_results.parquet"
    year_map = {}
    if yearly_path.exists():
        df_y = pd.read_parquet(yearly_path)
        for _, row in df_y.iterrows():
            year_map[int(row['year'])] = row['year_return_pct']
            
    return {
        "Run": run_name,
        "PF": pf,
        "WinRate": win_rate,
        "Trades/Day": avg_trades_day,
        "2021": year_map.get(2021, 0),
        "2022": year_map.get(2022, 0),
        "2023": year_map.get(2023, 0),
        "2024": year_map.get(2024, 0),
        "2025": year_map.get(2025, 0)
    }

results = []
print(f"{'Run Name':<35} | {'PF':<5} | {'WR%':<5} | {'Tr/Day':<6} | {'2021%':<8} | {'2022%':<8} | {'2023%':<8} | {'2024%':<8} | {'2025%':<8}")
print("-" * 115)

for run in RUNS:
    res = analyze_run(run)
    if res:
        results.append(res)
        print(f"{res['Run']:<35} | {res['PF']:<5.2f} | {res['WinRate']:<5.1f} | {res['Trades/Day']:<6.1f} | {res['2021']:<8.1f} | {res['2022']:<8.0f} | {res['2023']:<8.1f} | {res['2024']:<8.1f} | {res['2025']:<8.1f}")

