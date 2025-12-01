"""
Debug plotting for backtest results.

Generates:
- PnL histogram
- Equity curve
- Win/loss distribution
- RVOL distribution

Saves to ml_orb_5m/docs/images/
"""
import sys
sys.path.insert(0, ".")

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Paths
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "backtest"
OUT_DIR = Path(__file__).resolve().parents[3] / "ml_orb_5m" / "docs" / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TRADES_FILE = DATA_DIR / "simulated_trades.parquet"
DAILY_FILE = DATA_DIR / "daily_performance.parquet"

# Load data
trades = pd.read_parquet(TRADES_FILE)
daily = pd.read_parquet(DAILY_FILE)

# Filter to entered trades only
entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()

print(f"Total trades: {len(trades)}")
print(f"Entered: {len(entered)}")
print(f"Win rate: {(entered['pnl_pct'] > 0).mean() * 100:.1f}%")
print(f"Total P&L (1x): ${entered['base_dollar_pnl'].sum():,.2f}")
print(f"Total P&L (2x): ${entered['dollar_pnl'].sum():,.2f}")

# Setup matplotlib
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)
plt.rcParams['font.size'] = 12

# 1. PnL Histogram
fig, ax = plt.subplots()
ax.hist(entered['pnl_pct'].dropna(), bins=50, edgecolor='black', alpha=0.7)
ax.axvline(0, color='red', linestyle='--', linewidth=2)
ax.set_xlabel('P&L %')
ax.set_ylabel('Frequency')
ax.set_title(f'P&L Distribution (N={len(entered)}, Mean={entered["pnl_pct"].mean():.2f}%)')
fig.savefig(OUT_DIR / 'pnl_histogram.png', dpi=150, bbox_inches='tight')
print(f"✓ Saved {OUT_DIR / 'pnl_histogram.png'}")
plt.close(fig)

# 2. Equity Curve
daily_sorted = daily.sort_values('date')
daily_sorted['cumulative_pnl'] = daily_sorted['total_base_pnl'].cumsum()
daily_sorted['equity'] = 1000 + daily_sorted['cumulative_pnl']

fig, ax = plt.subplots()
ax.plot(daily_sorted['date'], daily_sorted['equity'], linewidth=2)
ax.axhline(1000, color='gray', linestyle='--', alpha=0.5)
ax.set_xlabel('Date')
ax.set_ylabel('Equity ($)')
ax.set_title(f'Equity Curve (Start=$1000, End=${daily_sorted["equity"].iloc[-1]:.2f})')
ax.grid(True, alpha=0.3)
fig.savefig(OUT_DIR / 'equity_curve.png', dpi=150, bbox_inches='tight')
print(f"✓ Saved {OUT_DIR / 'equity_curve.png'}")
plt.close(fig)

# 3. Win/Loss by Side
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

for i, side in enumerate(['LONG', 'SHORT']):
    side_trades = entered[entered['side'] == side]
    if len(side_trades) == 0:
        continue
    winners = (side_trades['pnl_pct'] > 0).sum()
    losers = (side_trades['pnl_pct'] < 0).sum()
    axes[i].bar(['Winners', 'Losers'], [winners, losers], color=['green', 'red'], alpha=0.7, edgecolor='black')
    axes[i].set_title(f'{side} Trades (N={len(side_trades)}, WinRate={winners/len(side_trades)*100:.1f}%)')
    axes[i].set_ylabel('Count')

fig.suptitle('Win/Loss Distribution by Side')
fig.savefig(OUT_DIR / 'win_loss_by_side.png', dpi=150, bbox_inches='tight')
print(f"✓ Saved {OUT_DIR / 'win_loss_by_side.png'}")
plt.close(fig)

# 4. RVOL Distribution
fig, ax = plt.subplots()
ax.hist(trades['rvol'], bins=30, edgecolor='black', alpha=0.7)
ax.axvline(trades['rvol'].mean(), color='red', linestyle='--', linewidth=2, label=f'Mean={trades["rvol"].mean():.2f}')
ax.set_xlabel('RVOL')
ax.set_ylabel('Frequency')
ax.set_title(f'RVOL Distribution (Top 20 per day)')
ax.legend()
fig.savefig(OUT_DIR / 'rvol_distribution.png', dpi=150, bbox_inches='tight')
print(f"✓ Saved {OUT_DIR / 'rvol_distribution.png'}")
plt.close(fig)

# 5. P&L by Rank
entered['rank_bin'] = pd.cut(entered['rvol_rank'], bins=[0, 5, 10, 15, 20], labels=['1-5', '6-10', '11-15', '16-20'])
rank_pnl = entered.groupby('rank_bin')['pnl_pct'].agg(['mean', 'count'])

fig, ax = plt.subplots()
ax.bar(range(len(rank_pnl)), rank_pnl['mean'], color='steelblue', alpha=0.7, edgecolor='black')
ax.set_xticks(range(len(rank_pnl)))
ax.set_xticklabels(rank_pnl.index)
ax.axhline(0, color='red', linestyle='--', linewidth=1)
ax.set_xlabel('RVOL Rank Bin')
ax.set_ylabel('Mean P&L %')
ax.set_title('Average P&L by RVOL Rank')
for i, (mean_val, count) in enumerate(zip(rank_pnl['mean'], rank_pnl['count'])):
    ax.text(i, mean_val, f'n={int(count)}', ha='center', va='bottom' if mean_val > 0 else 'top')
fig.savefig(OUT_DIR / 'pnl_by_rank.png', dpi=150, bbox_inches='tight')
print(f"✓ Saved {OUT_DIR / 'pnl_by_rank.png'}")
plt.close(fig)

# 6. Exit Reason Breakdown
fig, ax = plt.subplots()
exit_counts = trades['exit_reason'].value_counts()
ax.bar(exit_counts.index, exit_counts.values, color='coral', alpha=0.7, edgecolor='black')
ax.set_xlabel('Exit Reason')
ax.set_ylabel('Count')
ax.set_title('Exit Reason Distribution')
ax.tick_params(axis='x', rotation=45)
fig.tight_layout()
fig.savefig(OUT_DIR / 'exit_reasons.png', dpi=150, bbox_inches='tight')
print(f"✓ Saved {OUT_DIR / 'exit_reasons.png'}")
plt.close(fig)

print(f"\n✅ All plots saved to {OUT_DIR}")
