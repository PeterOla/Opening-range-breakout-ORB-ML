"""Generate equity curve plot with drawdown shading."""
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
import numpy as np

def plot_equity_curve(daily_pnl_path: str, output_path: str):
    """Create equity curve plot with drawdown shading.
    
    Args:
        daily_pnl_path: Path to all_daily_pnl.csv
        output_path: Path to save the plot PNG
    """
    # Load data
    df = pd.read_csv(daily_pnl_path, parse_dates=['date'])
    df = df.sort_values('date').reset_index(drop=True)
    
    # Compute drawdown
    equity = df['equity'].values
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), 
                                     gridspec_kw={'height_ratios': [3, 1]},
                                     sharex=True)
    
    # Plot 1: Equity curve
    ax1.plot(df['date'], equity / 1000, linewidth=2, color='#26a69a', label='Equity')
    ax1.fill_between(df['date'], 0, equity / 1000, alpha=0.1, color='#26a69a')
    
    ax1.set_ylabel('Equity ($1,000s)', fontsize=12, fontweight='bold')
    ax1.set_title('ORB Strategy — Equity Curve (2021–2025)', 
                  fontsize=14, fontweight='bold', pad=20)
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.legend(loc='upper left', fontsize=10)
    
    # Format y-axis
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}K'))
    
    # Add metrics annotation
    final_equity = equity[-1]
    start_equity = equity[0]
    total_return = (final_equity / start_equity - 1) * 100
    max_dd = drawdown.min() * 100
    
    textstr = '\n'.join((
        f'Start: ${start_equity:,.0f}',
        f'End: ${final_equity:,.0f}',
        f'Return: +{total_return:,.1f}%',
        f'Max DD: {max_dd:.2f}%',
    ))
    props = dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor='gray')
    ax1.text(0.02, 0.98, textstr, transform=ax1.transAxes, fontsize=10,
             verticalalignment='top', bbox=props, family='monospace')
    
    # Plot 2: Drawdown
    ax2.fill_between(df['date'], drawdown * 100, 0, 
                     where=(drawdown < 0), color='#ef5350', alpha=0.6, 
                     label='Drawdown', interpolate=True)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.8, alpha=0.3)
    
    ax2.set_ylabel('Drawdown (%)', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Date', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.legend(loc='lower left', fontsize=10)
    
    # Format x-axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    # Adjust layout and save
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✓ Equity curve saved to: {output_path}")
    plt.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate equity curve plot")
    parser.add_argument("--input", type=str, 
                       default="results_combined_top20/all_daily_pnl.csv",
                       help="Path to all_daily_pnl.csv")
    parser.add_argument("--output", type=str,
                       default="results_combined_top20/equity_curve.png",
                       help="Path to save plot PNG")
    
    args = parser.parse_args()
    
    plot_equity_curve(args.input, args.output)
