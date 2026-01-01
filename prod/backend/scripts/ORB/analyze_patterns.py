import pandas as pd
import numpy as np
from pathlib import Path

# Paths
RUN_DIR = Path(r'c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\runs\compound\5year_micro_small_top5_compound')
TRADES_FILE = RUN_DIR / 'simulated_trades.parquet'
REPORT_DIR = RUN_DIR / 'reports'
REPORT_DIR.mkdir(exist_ok=True)

def analyze_feature(df, feature_name, bins=10, qcut=True):
    """Analyze performance by feature bins."""
    data = df.copy()
    
    # Create bins
    try:
        if qcut:
            data['bin'] = pd.qcut(data[feature_name], bins, duplicates='drop')
        else:
            data['bin'] = pd.cut(data[feature_name], bins)
    except Exception as e:
        print(f"Skipping {feature_name}: {e}")
        return None

    # Aggregate
    stats = data.groupby('bin', observed=True).agg(
        count=('pnl_pct', 'count'),
        win_rate=('is_win', 'mean'),
        avg_pnl=('pnl_pct', 'mean'),
        total_pnl=('dollar_pnl', 'sum'),
        avg_dollar_pnl=('dollar_pnl', 'mean')
    ).reset_index()
    
    stats['win_rate'] = stats['win_rate'] * 100
    stats['feature'] = feature_name
    return stats

def main():
    print(f"Loading {TRADES_FILE}...")
    df = pd.read_parquet(TRADES_FILE)
    
    # Feature Engineering
    df['is_win'] = df['pnl_pct'] > 0
    df['gap_pct'] = (df['or_open'] - df['prev_close']) / df['prev_close'] * 100
    df['or_width_pct'] = (df['or_high'] - df['or_low']) / df['or_open'] * 100
    df['log_volume'] = np.log10(df['or_volume'])
    
    features = {
        'rvol': {'qcut': True, 'bins': 10},
        'gap_pct': {'qcut': True, 'bins': 10},
        'or_width_pct': {'qcut': True, 'bins': 10},
        'entry_price': {'qcut': True, 'bins': 10},
        'stop_distance_pct': {'qcut': True, 'bins': 10},
        'atr_14': {'qcut': True, 'bins': 10}
    }
    
    all_stats = []
    
    print("\n--- Pattern Analysis ---")
    
    for feature, config in features.items():
        print(f"Analyzing {feature}...")
        stats = analyze_feature(df, feature, bins=config['bins'], qcut=config['qcut'])
        if stats is not None:
            all_stats.append(stats)
            
            print(f"\nResults for {feature}:")
            print(f"{'Range':<30} | {'Count':>6} | {'Win Rate':>8} | {'Avg P&L':>10}")
            print("-" * 65)
            for _, row in stats.iterrows():
                print(f"{str(row['bin']):<30} | {row['count']:>6} | {row['win_rate']:>7.1f}% | ${row['avg_dollar_pnl']:>9.2f}")

    # Save detailed report
    if all_stats:
        full_report = pd.concat(all_stats, ignore_index=True)
        full_report.to_csv(REPORT_DIR / 'pattern_analysis.csv', index=False)
        print(f"\nSaved detailed analysis to {REPORT_DIR / 'pattern_analysis.csv'}")

    # --- Sweet Spot Search ---
    # Simple rule induction: Find combination of 2 filters that maximizes Win Rate
    print("\n--- Sweet Spot Search (Experimental) ---")
    # Define simple splits (median)
    median_rvol = df['rvol'].median()
    median_gap = df['gap_pct'].median()
    median_width = df['or_width_pct'].median()
    
    # Example: High RVOL + Moderate Gap
    mask = (df['rvol'] > median_rvol) & (df['gap_pct'] < median_gap)
    subset = df[mask]
    wr = subset['is_win'].mean() * 100
    print(f"High RVOL (> {median_rvol:.1f}) & Low Gap (< {median_gap:.1f}%):")
    print(f"  Trades: {len(subset)} | Win Rate: {wr:.1f}% | Avg P&L: ${subset['dollar_pnl'].mean():.2f}")

    # Example: Tight OR + High RVOL
    mask = (df['or_width_pct'] < median_width) & (df['rvol'] > median_rvol)
    subset = df[mask]
    wr = subset['is_win'].mean() * 100
    print(f"Tight OR (< {median_width:.1f}%) & High RVOL (> {median_rvol:.1f}):")
    print(f"  Trades: {len(subset)} | Win Rate: {wr:.1f}% | Avg P&L: ${subset['dollar_pnl'].mean():.2f}")

if __name__ == "__main__":
    main()
