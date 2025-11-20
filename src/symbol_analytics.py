"""Generate symbol leaderboard and RVOL bucket analysis."""
import pandas as pd
from pathlib import Path
import numpy as np


def compute_symbol_leaderboard(trades_path: str, output_dir: str):
    """Create leaderboard of best/worst performing symbols.
    
    Args:
        trades_path: Path to all_trades.csv
        output_dir: Directory to save output CSV
    """
    df = pd.read_csv(trades_path, parse_dates=['date'])
    
    # Group by symbol
    symbol_stats = df.groupby('symbol').agg({
        'net_pnl': ['sum', 'count', 'mean'],
        'date': ['min', 'max']
    }).reset_index()
    
    # Flatten column names
    symbol_stats.columns = ['symbol', 'total_pnl', 'n_trades', 'avg_pnl', 'first_trade', 'last_trade']
    
    # Compute win rate and cumulative R
    win_rates = df.groupby('symbol').apply(
        lambda x: (x['net_pnl'] > 0).sum() / len(x) if len(x) > 0 else 0
    ).rename('win_rate')
    
    # Approximate R-multiples (assuming net_pnl already accounts for risk-adjusted sizing)
    # For exact R, we'd need stop distance per trade; for now, use normalized P&L
    # Simple proxy: cumulative P&L / (n_trades * avg_abs_pnl)
    cumulative_r = df.groupby('symbol').apply(
        lambda x: x['net_pnl'].sum() / (abs(x['net_pnl']).mean() * len(x)) if len(x) > 0 and abs(x['net_pnl']).mean() > 0 else 0
    ).rename('cumulative_r')
    
    # Merge
    symbol_stats = symbol_stats.merge(win_rates, on='symbol', how='left')
    symbol_stats = symbol_stats.merge(cumulative_r, on='symbol', how='left')
    
    # Sort by total P&L
    symbol_stats = symbol_stats.sort_values('total_pnl', ascending=False)
    
    # Save full leaderboard
    output_path = Path(output_dir) / "symbol_leaderboard.csv"
    symbol_stats.to_csv(output_path, index=False)
    print(f"✓ Full leaderboard saved to: {output_path}")
    
    # Print top 10 and bottom 10
    print("\n" + "="*80)
    print("TOP 10 BEST PERFORMERS")
    print("="*80)
    top10 = symbol_stats.head(10)[['symbol', 'total_pnl', 'n_trades', 'win_rate', 'cumulative_r']]
    print(top10.to_string(index=False))
    
    print("\n" + "="*80)
    print("TOP 10 WORST PERFORMERS")
    print("="*80)
    bottom10 = symbol_stats.tail(10)[['symbol', 'total_pnl', 'n_trades', 'win_rate', 'cumulative_r']]
    print(bottom10.to_string(index=False))
    
    return symbol_stats


def compute_rvol_bucket_analysis(trades_path: str, output_dir: str):
    """Analyze performance by RVOL buckets.
    
    Args:
        trades_path: Path to all_trades.csv
        output_dir: Directory to save output CSV
    """
    df = pd.read_csv(trades_path, parse_dates=['date'])
    
    # Check if or_rvol_14 column exists
    if 'or_rvol_14' not in df.columns:
        print("⚠ Warning: 'or_rvol_14' column not found in trades. Skipping RVOL analysis.")
        return None
    
    # Define RVOL buckets
    bins = [0, 1.0, 1.5, 2.0, 3.0, 5.0, float('inf')]
    labels = ['<1.0', '1.0-1.5', '1.5-2.0', '2.0-3.0', '3.0-5.0', '>5.0']
    
    df['rvol_bucket'] = pd.cut(df['or_rvol_14'], bins=bins, labels=labels)
    
    # Compute metrics per bucket
    bucket_stats = df.groupby('rvol_bucket').agg({
        'net_pnl': ['sum', 'mean', 'count'],
    }).reset_index()
    
    # Flatten columns
    bucket_stats.columns = ['rvol_bucket', 'total_pnl', 'avg_pnl', 'n_trades']
    
    # Win rate per bucket
    win_rates = df.groupby('rvol_bucket').apply(
        lambda x: (x['net_pnl'] > 0).sum() / len(x) if len(x) > 0 else 0
    ).rename('win_rate')
    
    # Approximate R per bucket
    avg_r = df.groupby('rvol_bucket').apply(
        lambda x: x['net_pnl'].mean() / abs(x['net_pnl']).mean() if len(x) > 0 and abs(x['net_pnl']).mean() > 0 else 0
    ).rename('avg_r')
    
    bucket_stats = bucket_stats.merge(win_rates, on='rvol_bucket', how='left')
    bucket_stats = bucket_stats.merge(avg_r, on='rvol_bucket', how='left')
    
    # Save
    output_path = Path(output_dir) / "rvol_bucket_analysis.csv"
    bucket_stats.to_csv(output_path, index=False)
    print(f"✓ RVOL bucket analysis saved to: {output_path}")
    
    # Print
    print("\n" + "="*80)
    print("RVOL BUCKET ANALYSIS")
    print("="*80)
    print(bucket_stats.to_string(index=False))
    
    return bucket_stats


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate symbol analytics")
    parser.add_argument("--trades", type=str,
                       default="results_combined_top20/all_trades.csv",
                       help="Path to all_trades.csv")
    parser.add_argument("--output-dir", type=str,
                       default="results_combined_top20",
                       help="Directory to save outputs")
    
    args = parser.parse_args()
    
    # Symbol leaderboard
    compute_symbol_leaderboard(args.trades, args.output_dir)
    
    # RVOL bucket analysis
    compute_rvol_bucket_analysis(args.trades, args.output_dir)
