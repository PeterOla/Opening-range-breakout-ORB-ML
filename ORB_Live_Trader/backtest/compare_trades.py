"""Compare backtest trades with live trades - Output to file."""
import pandas as pd
from pathlib import Path
from datetime import date

# Load backtest trades
bt_path = Path(r'c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\ORB_Live_Trader\backtest\data\runs\compound\compare_2026\simulated_trades.parquet')
bt = pd.read_parquet(bt_path)
bt['trade_date'] = pd.to_datetime(bt['trade_date']).dt.date

# Live trades from log analysis
live_trades = {
    '2026-01-26': ['LE', 'LRHC', 'VWAV', 'STC', 'DCOM'],
    '2026-01-27': ['GABC', 'MPWR', 'BNAI'],
    '2026-01-28': ['LPTH', 'NBHC', 'AVAV', 'BNAI', 'SLE'],
}

output = []
output.append("=" * 80)
output.append("BACKTEST vs LIVE COMPARISON REPORT")
output.append("=" * 80)

total_match = 0
total_live = 0
total_bt = 0

for dt_str, live_syms in live_trades.items():
    dt = date.fromisoformat(dt_str)
    bt_day = bt[bt['trade_date'] == dt]
    bt_syms = sorted(bt_day['ticker'].unique().tolist()) if len(bt_day) > 0 else []
    
    output.append(f"\n{dt_str}:")
    output.append(f"  Backtest Top 5: {bt_syms[:5]}")
    output.append(f"  Live Watchlist: {live_syms}")
    
    in_both = set(live_syms) & set(bt_syms)
    only_live = set(live_syms) - set(bt_syms)
    only_bt = set(bt_syms) - set(live_syms)
    
    total_match += len(in_both)
    total_live += len(only_live)
    total_bt += len(only_bt)
    
    if in_both:
        output.append(f"  [MATCH]: {sorted(in_both)}")
    if only_live:
        output.append(f"  [LIVE ONLY]: {sorted(only_live)}")
    if only_bt:
        output.append(f"  [BACKTEST ONLY]: {sorted(only_bt)}")

output.append("\n" + "=" * 80)
output.append("SUMMARY:")
output.append(f"  Total matching symbols: {total_match}")
output.append(f"  Symbols only in live: {total_live}")
output.append(f"  Symbols only in backtest: {total_bt}")

output.append("\n" + "=" * 80)
output.append("BACKTEST TRADES:")
output.append(f"Columns: {bt.columns.tolist()}")
output.append("")
for _, row in bt.iterrows():
    output.append(f"  {row['trade_date']} | {row['ticker']} | {row['side']} | Entry: ${row.get('entry_price', 0):.2f} | Exit: ${row.get('exit_price', 0):.2f} | Gross: ${row.get('gross_pnl', 0):.2f}")

# Write to file
result = "\n".join(output)
Path("comparison_report.txt").write_text(result)
print(result)
