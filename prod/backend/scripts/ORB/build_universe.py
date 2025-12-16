"""
Build ORB universe (Top 50 by RVOL).

Scans all symbols once per day, filters by criteria, and saves the Top 50 ranked by Relative Volume.
Output: data/backtest/universe.parquet

DATA FORMAT REQUIREMENTS:
  Daily data (data/processed/daily/*.parquet):
    - date column: datetime64[ns, UTC] — midnight UTC for each trading day
    - atr_14, avg_volume_14 must be pre-computed
    
  5-Min data (data/processed/5min/*.parquet):
    - datetime column: datetime64[ns, America/New_York] — ET timestamps
    - Contains pre-market (04:00 ET) through after-hours (19:55 ET) bars

Usage:
    python scripts/ORB/build_universe.py --start 2021-01-01 --end 2025-12-09 \\
        --min-price 5 --min-volume 1000000 --workers 8
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import date, time, datetime
from typing import Optional, List, Dict
import pandas as pd
import numpy as np
from tqdm import tqdm
import duckdb
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import gc

# Data dirs
DATA_DIR = Path(__file__).resolve().parents[4] / "data"
DATA_DIR_5MIN = DATA_DIR / "processed" / "5min"
DATA_DIR_DAILY = DATA_DIR / "processed" / "daily"
OUT_DIR = DATA_DIR / "backtest" / "orb" / "universe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OR_START = time(9, 30)
OR_END = time(16, 0)    # 4:00 PM ET closing time


ALL_CATEGORIES = [
    "micro",
    "small",
    "large",
    "all",
    "unknown",
    "micro_unknown",
    "micro_small_unknown",
]


def list_trading_days(start: str, end: str) -> List[date]:
    """Build trading days from daily parquet data."""
    start_dt = pd.Timestamp(start).date()
    end_dt = pd.Timestamp(end).date()
    
    all_dates = set()
    # Sample a few files to get dates quickly instead of reading all
    sample_files = list(DATA_DIR_DAILY.glob("*.parquet"))[:100]
    for p in sample_files:
        try:
            df = pd.read_parquet(p, columns=['date'])
            if 'date' in df.columns:
                dates = pd.to_datetime(df['date']).dt.date
                all_dates.update(dates)
        except Exception:
            continue
    
    # Filter to range and sort
    result = sorted([d for d in all_dates if start_dt <= d <= end_dt])
    return result


def load_daily(symbol: str) -> Optional[pd.DataFrame]:
    p = DATA_DIR_DAILY / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        if 'date' not in df.columns or df.empty:
            return None
        # Ensure date is timezone-naive for comparison
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
        return df
    except Exception:
        return None


def load_5min_full(symbol: str) -> Optional[pd.DataFrame]:
    """Load full 5-min history for a symbol."""
    p = DATA_DIR_5MIN / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        if df.empty or 'datetime' not in df.columns:
            return None
        
        # Pre-calculate date and time columns for fast filtering
        df['datetime'] = pd.to_datetime(df['datetime'])
        df['date_et'] = df['datetime'].dt.date
        df['time'] = df['datetime'].dt.time
        return df
    except Exception:
        return None


def extract_or(bars: pd.DataFrame) -> Optional[dict]:
    """Extract the Opening Range as the first regular-hours 5-min bar (9:30-16:00 ET)."""
    # First try for exact 9:30
    or_row = bars[bars['time'] == OR_START]
    if not or_row.empty:
        r = or_row.iloc[0]
        return {
            'or_open': float(r['open']),
            'or_high': float(r['high']),
            'or_low': float(r['low']),
            'or_close': float(r['close']),
            'or_volume': float(r['volume']),
        }
    
    # Fallback: first bar within regular trading hours
    rth_mask = (bars['time'] >= OR_START) & (bars['time'] <= OR_END)
    rth_bars = bars[rth_mask].sort_values('datetime')
    
    if rth_bars.empty:
        return None
    
    r = rth_bars.iloc[0]
    return {
        'or_open': float(r['open']),
        'or_high': float(r['high']),
        'or_low': float(r['low']),
        'or_close': float(r['close']),
        'or_volume': float(r['volume']),
    }


def compute_rvol(or_volume: float, avg_volume_14: float) -> float:
    """Compute relative volume (scaled to full day)."""
    if not avg_volume_14 or avg_volume_14 <= 0:
        return 0.0
    return (or_volume * 78.0) / avg_volume_14


def serialize_bars(bars: pd.DataFrame) -> str:
    """Serialize 5-min bars to JSON string."""
    bars_clean = bars[['datetime', 'open', 'high', 'low', 'close', 'volume']].copy()
    bars_clean['datetime'] = bars_clean['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return bars_clean.to_json(orient='records')


def process_symbol_bulk(symbol: str, start_date: date, end_date: date, min_price: float, min_volume: int) -> List[dict]:
    """Process a single symbol for the entire date range (Efficient I/O)."""
    candidates = []
    
    # 1. Load Data
    df_daily = load_daily(symbol)
    if df_daily is None:
        return []
        
    df_5min = load_5min_full(symbol)
    if df_5min is None:
        return []

    # 2. Filter Daily to range
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    mask = (df_daily['date'] >= start_ts) & (df_daily['date'] <= end_ts)
    df_daily_range = df_daily[mask]
    
    if df_daily_range.empty:
        return []

    # 3. Iterate Days
    for _, daily_row in df_daily_range.iterrows():
        trading_date = daily_row['date'].date()
        
        # Metrics
        atr_14 = float(daily_row['atr_14']) if pd.notna(daily_row['atr_14']) else None
        avg_vol = float(daily_row['avg_volume_14']) if pd.notna(daily_row['avg_volume_14']) else None
        shares = int(daily_row['shares_outstanding']) if pd.notna(daily_row['shares_outstanding']) else None
        
        # Pre-filters (Fast)
        if not atr_14 or atr_14 < 0.50:
            continue
        if not avg_vol or avg_vol < min_volume:
            continue
            
        # Get 5-min bars for this day (In-Memory Slice)
        day_bars = df_5min[df_5min['date_et'] == trading_date].copy()
        if day_bars.empty:
            continue
            
        # Extract OR
        or_data = extract_or(day_bars)
        if not or_data:
            continue
            
        # Price Filter
        if or_data['or_open'] < min_price:
            continue
            
        # Direction
        if or_data['or_close'] > or_data['or_open']:
            direction = 1
        elif or_data['or_close'] < or_data['or_open']:
            direction = -1
        else:
            continue
            
        # RVOL
        rvol = compute_rvol(or_data['or_volume'], avg_vol)
        if rvol < 1.0:
            continue
            
        # Build Candidate
        candidate = {
            'trade_date': trading_date,
            'ticker': symbol,
            'direction': direction,
            'rvol': rvol,
            'or_open': or_data['or_open'],
            'or_high': or_data['or_high'],
            'or_low': or_data['or_low'],
            'or_close': or_data['or_close'],
            'or_volume': or_data['or_volume'],
            'atr_14': atr_14,
            'avg_volume_14': avg_vol,
            'prev_close': float(daily_row['close']), # Approx prev close logic simplified
            'shares_outstanding': shares,
            'bars_json': serialize_bars(day_bars),
        }
        candidates.append(candidate)
        
    return candidates


def build_universe_bulk(
    start: str,
    end: str,
    min_price: float,
    min_volume: int,
    workers: int = 1,
    top_n: int = 50,
    categories: Optional[List[str]] = None,
):
    """Build universe using efficient symbol-centric processing in yearly chunks."""
    start_dt = pd.Timestamp(start).date()
    end_dt = pd.Timestamp(end).date()
    
    # Generate yearly chunks
    years = range(start_dt.year, end_dt.year + 1)
    
    all_universe_files = {
        "micro": OUT_DIR / "universe_micro.parquet",
        "small": OUT_DIR / "universe_small.parquet",
        "large": OUT_DIR / "universe_large.parquet",
        "all": OUT_DIR / "universe_all.parquet",
        "unknown": OUT_DIR / "universe_unknown.parquet",
        "micro_unknown": OUT_DIR / "universe_micro_unknown.parquet",
        "micro_small_unknown": OUT_DIR / "universe_micro_small_unknown.parquet",
    }

    if categories is None:
        categories = ["micro", "small", "large", "all"]
    categories = list(categories)
    invalid = [c for c in categories if c not in ALL_CATEGORIES]
    if invalid:
        raise ValueError(f"Invalid categories: {invalid}. Allowed: {ALL_CATEGORIES}")

    universe_files = {k: all_universe_files[k] for k in categories}
    
    symbols = [p.stem for p in DATA_DIR_DAILY.glob("*.parquet")]
    print(f"Processing {len(symbols)} symbols from {start} to {end}")
    print(f"Workers: {workers}")

    for year in years:
        year_start = max(start_dt, date(year, 1, 1))
        year_end = min(end_dt, date(year, 12, 31))
        
        if year_start > year_end:
            continue
            
        print(f"\n=== Processing Year {year} ({year_start} to {year_end}) ===")
        
        # 1. Collect all candidates for the year
        all_candidates = []
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(process_symbol_bulk, sym, year_start, year_end, min_price, min_volume): sym 
                for sym in symbols
            }
            
            for future in tqdm(as_completed(futures), total=len(symbols), desc=f"Scanning {year}"):
                try:
                    res = future.result()
                    if res:
                        all_candidates.extend(res)
                except Exception as e:
                    pass # logger.error(f"Error: {e}")
        
        if not all_candidates:
            print(f"No candidates found for {year}")
            continue
            
        # 2. Group by Date and Rank
        print(f"Ranking {len(all_candidates)} candidates...")
        df_all = pd.DataFrame(all_candidates)
        
        # Categorize
        results = {k: [] for k in universe_files.keys()}
        
        # Group by date to rank
        for trade_date, group in df_all.groupby('trade_date'):
            # Sort by RVOL
            group = group.sort_values('rvol', ascending=False)

            if 'all' in results:
                top_all = group.head(top_n).copy()
                top_all['rvol_rank'] = range(1, len(top_all) + 1)
                results['all'].append(top_all)

            if 'unknown' in results:
                unknown = group[pd.isna(group['shares_outstanding'])]
                top_unknown = unknown.head(top_n).copy()
                top_unknown['rvol_rank'] = range(1, len(top_unknown) + 1)
                results['unknown'].append(top_unknown)

            if 'micro_unknown' in results:
                micro_unknown = group[(group['shares_outstanding'] < 50_000_000) | (pd.isna(group['shares_outstanding']))]
                top_micro_unknown = micro_unknown.head(top_n).copy()
                top_micro_unknown['rvol_rank'] = range(1, len(top_micro_unknown) + 1)
                results['micro_unknown'].append(top_micro_unknown)

            if 'micro' in results:
                micro = group[group['shares_outstanding'] < 50_000_000]
                top_micro = micro.head(top_n).copy()
                top_micro['rvol_rank'] = range(1, len(top_micro) + 1)
                results['micro'].append(top_micro)

            if 'small' in results:
                small = group[(group['shares_outstanding'] >= 50_000_000) & (group['shares_outstanding'] < 150_000_000)]
                top_small = small.head(top_n).copy()
                top_small['rvol_rank'] = range(1, len(top_small) + 1)
                results['small'].append(top_small)

            if 'large' in results:
                large = group[group['shares_outstanding'] >= 150_000_000]
                top_large = large.head(top_n).copy()
                top_large['rvol_rank'] = range(1, len(top_large) + 1)
                results['large'].append(top_large)

            if 'micro_small_unknown' in results:
                msu = group[(group['shares_outstanding'] < 150_000_000) | (pd.isna(group['shares_outstanding']))]
                top_msu = msu.head(top_n).copy()
                top_msu['rvol_rank'] = range(1, len(top_msu) + 1)
                results['micro_small_unknown'].append(top_msu)

        # 3. Save/Append
        for cat, dfs in results.items():
            if not dfs:
                continue
            
            new_df = pd.concat(dfs, ignore_index=True)
            file_path = universe_files[cat]
            
            if file_path.exists():
                try:
                    existing = pd.read_parquet(file_path)
                    # Remove overlapping dates from existing to avoid dupes
                    existing = existing[~existing['trade_date'].isin(new_df['trade_date'])]
                    combined = pd.concat([existing, new_df], ignore_index=True)
                    combined = combined.sort_values(['trade_date', 'rvol_rank'])
                    combined.to_parquet(file_path)
                except Exception:
                    new_df.to_parquet(file_path)
            else:
                new_df.to_parquet(file_path)
                
            print(f"  ✓ {cat}: Saved {len(new_df)} rows")
            
        # Clear memory
        del all_candidates
        del df_all
        del results
        gc.collect()


def main():
    ap = argparse.ArgumentParser(description='Build ORB universe (ATR ≥ 0.50) efficiently')
    ap.add_argument('--start', type=str, required=True, help='Start date (YYYY-MM-DD)')
    ap.add_argument('--end', type=str, required=True, help='End date (YYYY-MM-DD)')
    ap.add_argument('--min-price', type=float, default=5.0, help='Minimum share price (default: $5.00)')
    ap.add_argument('--min-volume', type=int, default=1_000_000, help='Minimum avg volume (default: 1M)')
    ap.add_argument('--top-n', type=int, default=50, help='Top N candidates per day (default: 50)')
    ap.add_argument(
        '--categories',
        nargs='+',
        default=['micro', 'small', 'large', 'all'],
        choices=ALL_CATEGORIES,
        help='Which universes to build (default: micro small large all)'
    )
    ap.add_argument('--workers', type=int, default=max(1, multiprocessing.cpu_count() - 1),
                    help='Parallel workers (default: CPU count - 1)')
    args = ap.parse_args()

    build_universe_bulk(
        args.start,
        args.end,
        args.min_price,
        args.min_volume,
        args.workers,
        top_n=args.top_n,
        categories=args.categories,
    )


if __name__ == "__main__":
    main()
