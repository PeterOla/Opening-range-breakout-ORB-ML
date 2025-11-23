"""
Plot equity curves and build summary for Top20 backtest outputs.
Reads: ml_orb_5m/results/backtest_top20/equity_curve_*.csv
Writes: ml_orb_5m/results/backtest_top20/equity_curve_comparison.png and backtest_summary_top20.csv
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
BACKTEST_DIR = BASE_DIR / "results" / "backtest_top20"
OUT_IMG = BACKTEST_DIR / "equity_curve_comparison_top20.png"
OUT_SUMMARY = BACKTEST_DIR / "backtest_summary_top20.csv"

# Find equity curve files
files = list(BACKTEST_DIR.glob('equity_curve_*.csv'))
if not files:
    print(f"No equity curve files found in {BACKTEST_DIR}")

# Load and plot
plt.figure(figsize=(12, 8))
summary_rows = []
per_strategy_imgs = []
metrics = []
for f in files:
    name = f.stem.replace('equity_curve_', '')
    df = pd.read_csv(f)
    if 'equity' not in df.columns:
        print(f"File {f} doesn't contain 'equity' column")
        continue
    # Keep absolute curve (for per-strategy plots) and also normalize for comparison
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    start_val = df['equity'].iloc[0]
    df['equity_norm'] = df['equity'] / start_val
    # Normalized plot on combined chart
    plt.plot(df['date'], df['equity_norm'], label=name)

    # Save per-strategy absolute curve
    out_abs = BACKTEST_DIR / f"equity_curve_{name}_abs.png"
    plt.figure(figsize=(12, 6))
    plt.plot(df['date'], df['equity'], label=f"{name} (abs)")
    plt.title(f"{name} - Daily Equity (Absolute)")
    plt.xlabel('Date')
    plt.ylabel('Equity ($)')
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_abs)
    plt.close()
    per_strategy_imgs.append((name, out_abs))

    # Compute some summary stats from the file
    total_return = df['equity'].iloc[-1] / start_val - 1
    # Max drawdown
    peak = df['equity'].cummax()
    drawdown = (df['equity'] - peak) / peak
    max_dd = drawdown.min()
    # Approx sharpe: daily returns
    df['return'] = df['equity'].pct_change().fillna(0)
    if df['return'].std() > 0:
        sharpe = df['return'].mean() / df['return'].std() * (252**0.5)
    else:
        sharpe = 0.0
    trades_taken = None
    trade_log_path = BACKTEST_DIR / f"trade_log_{name}.csv"
    if trade_log_path.exists():
        tdf = pd.read_csv(trade_log_path)
        trades_taken = len(tdf)
    summary_rows.append({
        'Strategy': name,
        'Final Equity': df['equity'].iloc[-1],
        'Total Return': total_return,
        'Sharpe': sharpe,
        'Max Drawdown': max_dd,
        'Trades': trades_taken
    })
    metrics.append((name, total_return, sharpe, max_dd, trades_taken))

plt.legend()
plt.title('Top20 Backtest: Baseline vs LSTM Percentiles (Normalized)')
plt.ylabel('Normalized Equity')
plt.xlabel('Date')
plt.tight_layout()
plt.savefig(OUT_IMG)
print(f"Saved comparison image to {OUT_IMG}")

# Save summary CSV
summary_df = pd.DataFrame(summary_rows)
summary_df.to_csv(OUT_SUMMARY, index=False)
print(f"Saved summary to {OUT_SUMMARY}")

# Also print the summary
print(summary_df.to_string(index=False))

# Create a bar chart for Total Return and Sharpe
if len(metrics) > 0:
    mdf = pd.DataFrame(metrics, columns=['Strategy', 'TotalReturn', 'Sharpe', 'MaxDD', 'Trades'])
    fig, ax = plt.subplots(1, 2, figsize=(16, 6))
    # Total Return
    sns.barplot(x='Strategy', y='TotalReturn', data=mdf, ax=ax[0], palette='viridis')
    ax[0].set_title('Total Return by Strategy')
    ax[0].set_ylabel('Total Return')
    # Sharpe
    sns.barplot(x='Strategy', y='Sharpe', data=mdf, ax=ax[1], palette='magma')
    ax[1].set_title('Sharpe Ratio by Strategy')
    ax[1].set_ylabel('Sharpe')
    plt.tight_layout()
    out_metrics = BACKTEST_DIR / 'backtest_metrics_top20.png'
    plt.savefig(out_metrics)
    print(f"Saved metrics chart to {out_metrics}")
