"""Fix combined equity curve"""
import sys
import pandas as pd
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.portfolio_orb import compute_portfolio_metrics

INITIAL_EQUITY = 1000.0

# Load trades
results_dir = Path(__file__).parent.parent / "results" / "results_combined_top20"
trades = pd.read_csv(results_dir / 'all_trades.csv')

# Recalculate daily P&L
daily = (
    trades
    .groupby('date')['net_pnl']
    .sum()
    .reset_index()
    .sort_values('date')
)

# Build equity curve from scratch
eq = INITIAL_EQUITY
equities = []
for _, r in daily.iterrows():
    eq += r['net_pnl']
    equities.append(eq)
daily['equity'] = equities

# Save corrected daily P&L
daily.to_csv(results_dir / 'all_daily_pnl.csv', index=False)

# Recalculate metrics
metrics = compute_portfolio_metrics(trades, daily, INITIAL_EQUITY)

# Update summary
total_pnl = trades['net_pnl'].sum()
final_equity = daily['equity'].iloc[-1]
total_return = total_pnl / INITIAL_EQUITY

with open(results_dir / 'summary.txt', 'w') as f:
    f.write("=== Combined Portfolio Summary (2021-2025) ===\n\n")
    f.write(f"Period: 2021-01-01 to 2025-12-31\n")
    f.write(f"Initial equity: ${INITIAL_EQUITY:,.2f}\n")
    f.write(f"Final equity: ${final_equity:,.2f}\n")
    f.write(f"Total return: {total_return:.2%}\n")
    f.write(f"Total trades: {len(trades):,}\n")
    f.write(f"Win rate: {metrics.get('hit_rate', 0.0):.2%}\n")
    f.write(f"Profit factor: {metrics.get('profit_factor', 0.0):.2f}\n")
    f.write(f"Max drawdown: {metrics.get('max_drawdown', 0.0):.2%}\n")
    f.write(f"CAGR: {metrics.get('cagr', 0.0):.2%}\n")

print("Fixed combined results:")
print(f"Initial: ${INITIAL_EQUITY:,.2f}")
print(f"Final: ${final_equity:,.2f}")
print(f"Total return: {total_return:.2%}")
print(f"Max DD: {metrics['max_drawdown']:.2%}")
print(f"CAGR: {metrics['cagr']:.2%}")
