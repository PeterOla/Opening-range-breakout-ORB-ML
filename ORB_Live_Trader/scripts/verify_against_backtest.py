"""
Self-Verification System - Backtest Universe Validation

Loads the backtest universe file (source of truth), applies runtime filters,
and verifies they match the simulated trades exactly. Results MUST match 100%.

This ensures:
1. Filter logic is correctly implemented (ATR >= 0.5, volume >= 100k, direction == 1)
2. Ranking logic matches backtest (RVOL descending, Top 5)
3. No regression in selection criteria
4. Universe file integrity

Usage:
    python scripts/verify_against_backtest.py --universe-file PATH --trades-file PATH --num-dates 10
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import List, Dict
import random
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
VERIFICATION_LOG_DIR = Path(__file__).parent.parent / "logs" / "verification"
VERIFICATION_LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str, level: str = "INFO"):
    """Timestamped logger."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] [{level:5s}] {msg}", flush=True)


def load_backtest_universe(universe_file: Path) -> pd.DataFrame:
    """Load backtest universe file (source of truth)."""
    log(f"Loading backtest universe from {universe_file}")
    
    df = pd.read_parquet(universe_file)
    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    
    log(f"Loaded {len(df)} universe candidates")
    log(f"  Date range: {df['trade_date'].min()} to {df['trade_date'].max()}")
    log(f"  Unique dates: {df['trade_date'].nunique()}")
    
    return df


def load_backtest_trades(trades_file: Path) -> pd.DataFrame:
    """Load historical backtest trades."""
    log(f"Loading backtest trades from {trades_file}")
    
    if trades_file.suffix == ".parquet":
        df = pd.read_parquet(trades_file)
    elif trades_file.suffix == ".csv":
        df = pd.read_csv(trades_file, parse_dates=['trade_date', 'entry_time', 'exit_time'])
    else:
        raise ValueError(f"Unsupported file format: {trades_file.suffix}")
    
    log(f"Loaded {len(df)} historical trades")
    return df


def pick_random_dates(trades_df: pd.DataFrame, num_dates: int) -> List[datetime.date]:
    """Pick random dates from backtest trades."""
    all_dates = pd.to_datetime(trades_df['trade_date']).dt.date.unique()
    
    if len(all_dates) < num_dates:
        log(f"WARNING: Only {len(all_dates)} unique dates available, using all")
        return sorted(all_dates)
    
    selected = random.sample(list(all_dates), num_dates)
    selected.sort()
    
    log(f"Selected {len(selected)} random dates for verification:")
    for d in selected:
        log(f"  {d}")
    
    return selected


def apply_filters_and_rank(universe_df: pd.DataFrame, trade_date: datetime.date) -> pd.DataFrame:
    """Apply runtime filters and ranking to universe (matches backtest logic).
    
    Filters:
    - ATR >= 0.5
    - avg_volume >= 100,000
    - direction == 1 (long-only)
    
    Ranking:
    - RVOL descending
    - Top 5
    """
    # Filter to trade date
    day_universe = universe_df[universe_df['trade_date'] == trade_date].copy()
    
    if len(day_universe) == 0:
        log(f"  No universe candidates for {trade_date}")
        return pd.DataFrame()
    
    log(f"  Universe candidates before filters: {len(day_universe)}")
    
    # Apply filters
    filtered = day_universe[
        (day_universe['atr_14'] >= 0.5) &
        (day_universe['avg_volume_14'] >= 100_000) &
        (day_universe['direction'] == 1)
    ].copy()
    
    log(f"  Candidates after filters: {len(filtered)}")
    
    if len(filtered) == 0:
        return pd.DataFrame()
    
    # Sort by RVOL descending, take Top 5
    top_n = filtered.sort_values('rvol', ascending=False).head(5).copy()
    
    log(f"  Top {len(top_n)} by RVOL:")
    for _, row in top_n.iterrows():
        log(f"    {row['ticker']} - RVOL: {row['rvol']:.2f}")
    
    return top_n


def compare_universes(filtered_universe: pd.DataFrame, backtest_trades: pd.DataFrame, trade_date: datetime.date) -> Dict:
    """Compare filtered universe with backtest trades for same date."""
    log(f"Comparing universes for {trade_date}...")
    
    # Filter backtest trades to this date
    bt_date_trades = backtest_trades[pd.to_datetime(backtest_trades['trade_date']).dt.date == trade_date].copy()
    
    # Extract symbols
    bt_symbols = set(bt_date_trades['ticker'].tolist()) if len(bt_date_trades) > 0 else set()
    universe_symbols = set(filtered_universe['ticker'].tolist()) if len(filtered_universe) > 0 else set()
    
    missing = bt_symbols - universe_symbols
    extra = universe_symbols - bt_symbols
    
    match = (missing == set() and extra == set())
    
    log(f"  Match: {match}")
    log(f"  Universe Top {len(universe_symbols)}: {sorted(universe_symbols)}")
    log(f"  Backtest trades: {sorted(bt_symbols)}")
    
    if missing:
        log(f"  Missing in universe: {sorted(missing)}", level="WARN")
    if extra:
        log(f"  Extra in universe: {sorted(extra)}", level="WARN")
    
    return {
        'date': trade_date,
        'match': match,
        'universe_symbols': sorted(universe_symbols),
        'backtest_symbols': sorted(bt_symbols),
        'missing': sorted(missing),
        'extra': sorted(extra)
    }


def verify_dates(universe_file: Path, trades_file: Path, num_dates: int = 10):
    """Main verification workflow."""
    log("=" * 80)
    log("BACKTEST VERIFICATION - Universe Validation")
    log("=" * 80)
    
    # Load backtest universe (source of truth)
    df_universe = load_backtest_universe(universe_file)
    
    # Load backtest trades
    df_trades = load_backtest_trades(trades_file)
    
    # Pick random dates
    dates_to_verify = pick_random_dates(df_trades, num_dates)
    
    # Verify each date
    results = []
    
    for i, trade_date in enumerate(dates_to_verify, 1):
        log("")
        log(f"[{i}/{len(dates_to_verify)}] Verifying {trade_date}")
        log("-" * 80)
        
        # Apply filters and ranking to universe
        filtered_universe = apply_filters_and_rank(df_universe, trade_date)
        
        # Compare with backtest trades
        comparison = compare_universes(filtered_universe, df_trades, trade_date)
        results.append(comparison)
    
    # Summary
    log("")
    log("=" * 80)
    log("VERIFICATION SUMMARY")
    log("=" * 80)
    
    matches = sum(1 for r in results if r['match'])
    total = len(results)
    
    log(f"Dates verified: {total}")
    log(f"Perfect matches: {matches}/{total} ({matches*100/total:.1f}%)")
    
    if matches < total:
        log("")
        log("FAILED DATES:", level="ERROR")
        for r in results:
            if not r['match']:
                log(f"  {r['date']}: Missing={r['missing']}, Extra={r['extra']}", level="ERROR")
    
    # Save report
    report_path = VERIFICATION_LOG_DIR / f"verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    import json
    with open(report_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'universe_file': str(universe_file),
            'trades_file': str(trades_file),
            'num_dates': num_dates,
            'matches': matches,
            'total': total,
            'results': [{**r, 'date': str(r['date'])} for r in results]
        }, f, indent=2)
    
    log(f"\nReport saved: {report_path}")
    
    # Exit code
    if matches == total:
        log("\n✓ [PASS] VERIFICATION PASSED - 100% match with backtest", level="INFO")
        return 0
    else:
        log(f"\n✗ [FAIL] VERIFICATION FAILED - {total-matches} mismatches", level="ERROR")
        return 1


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Verify backtest universe against trades")
    parser.add_argument("--universe-file", type=Path, required=True, help="Path to backtest universe file (parquet)")
    parser.add_argument("--trades-file", type=Path, required=True, help="Path to backtest trades file (parquet/csv)")
    parser.add_argument("--num-dates", type=int, default=10, help="Number of random dates to verify")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    if args.seed:
        random.seed(args.seed)
        log(f"Random seed: {args.seed}")
    
    exit_code = verify_dates(args.universe_file, args.trades_file, args.num_dates)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
