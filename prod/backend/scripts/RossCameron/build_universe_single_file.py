"""
Build Ross Cameron strategy candidate universe incrementally to single file.

Scans all symbols, applies RC-specific filters:
- Price: $2–$20
- Gap: Open ≥ 2% above previous close
- RVOL: ≥ 5.0 (relative volume at 9:30 ET)
- Volume: ≥ 1M average (50-day)
- Float: < 10M shares

Saves Top-50 per day (ranked by RVOL) to single consolidated parquet file.
Only appends NEW days - skips days already in the file.

Output: data/backtest/universes/universe_rc.parquet

Usage:
    python scripts/RossCameron/build_universe_single_file.py --start 2021-01-01 --end 2025-12-08
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import date, time
import pandas as pd
import numpy as np
from tqdm import tqdm
import duckdb
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# Data dirs
DATA_DIR = Path(__file__).resolve().parents[4] / "data"
DATA_DIR_5MIN = DATA_DIR / "processed" / "5min"
DATA_DIR_DAILY = DATA_DIR / "processed" / "daily"
OUT_DIR = DATA_DIR / "backtest" / "universes"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# RC-specific filters
MIN_PRICE = 2.0
MAX_PRICE = 20.0
MIN_GAP_PCT = 2.0
MIN_RVOL = 5.0  # At least 5x the 50-day average volume
MIN_VOLUME_50D = 1_000_000  # Minimum 50-day average volume
MAX_FLOAT = 10_000_000  # Max 10M shares float
TOP_N = 50

MARKET_OPEN = time(9, 30)


def list_trading_days(start: str, end: str) -> list:
    """Get all trading days in range."""
    con = duckdb.connect()
    df_dates = con.execute(f"""
      SELECT DISTINCT CAST(date AS DATE) AS d
      FROM read_parquet('{DATA_DIR_DAILY.as_posix()}/**/*.parquet', union_by_name=true)
      WHERE date >= DATE '{start}' AND date <= DATE '{end}'
      ORDER BY d
    """).df()
    con.close()
    return list(df_dates['d'])


def load_daily_symbol(symbol: str) -> pd.DataFrame:
    """Load daily bars for one symbol."""
    p = DATA_DIR_DAILY / f"{symbol}.parquet"
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(p)
        df['date'] = pd.to_datetime(df['date']).dt.date
        return df.sort_values('date').reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def load_5min_symbol(symbol: str) -> pd.DataFrame:
    """Load 5-min bars for one symbol."""
    p = DATA_DIR_5MIN / f"{symbol}.parquet"
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(p)
        df['date'] = df['timestamp'].dt.date
        df['time'] = df['timestamp'].dt.time
        return df.sort_values('timestamp').reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def compute_gap(or_open: float, prev_close: float) -> float:
    """Compute gap percentage."""
    if prev_close <= 0:
        return 0.0
    return ((or_open - prev_close) / prev_close) * 100


def extract_or(bars: pd.DataFrame) -> dict:
    """Extract 9:30 bar."""
    or_bar = bars[bars['time'] == MARKET_OPEN]
    if or_bar.empty:
        return None
    r = or_bar.iloc[0]
    return {
        'or_open': float(r['open']),
        'or_high': float(r['high']),
        'or_low': float(r['low']),
        'or_close': float(r['close']),
        'or_volume': float(r['volume']),
    }


def compute_rvol(or_volume: float, avg_volume_50d: float) -> float:
    """Compute relative volume vs 50-day average."""
    if not avg_volume_50d or avg_volume_50d <= 0:
        return 0.0
    return or_volume / (avg_volume_50d / 6.5)  # Scale to opening 1.3 hours


def serialize_bars(bars: pd.DataFrame) -> str:
    """Serialize bars to JSON."""
    bars_json = bars[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
    bars_json['timestamp'] = bars_json['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return bars_json.to_json(orient='records')


def scan_day(trading_date: date) -> list:
    """Scan all symbols for one trading day."""
    candidates = []
    
    # Get all symbols
    symbol_files = sorted(DATA_DIR_DAILY.glob('*.parquet'))
    symbols = [p.stem for p in symbol_files]
    
    for symbol in symbols:
        df_daily = load_daily_symbol(symbol)
        if df_daily.empty or trading_date not in set(df_daily['date']):
            continue
        
        # Get row for trading date
        row = df_daily[df_daily['date'] == trading_date]
        if row.empty:
            continue
        row = row.iloc[0]
        
        # Price filter
        if row['close'] < MIN_PRICE or row['close'] > MAX_PRICE:
            continue
        
        # Get previous close and compute gap
        prev_rows = df_daily[df_daily['date'] < trading_date].sort_values('date').tail(1)
        if prev_rows.empty:
            continue
        prev_close = float(prev_rows.iloc[0]['close'])
        
        gap_pct = compute_gap(float(row['open']), prev_close)
        if gap_pct < MIN_GAP_PCT:
            continue
        
        # Volume filter (50-day average)
        vol_rows = df_daily[df_daily['date'] < trading_date].sort_values('date').tail(50)
        if len(vol_rows) < 50:
            continue
        avg_volume_50d = float(vol_rows['volume'].mean())
        if avg_volume_50d < MIN_VOLUME_50D:
            continue
        
        # Load 5-min bars
        df_5min = load_5min_symbol(symbol)
        if df_5min.empty:
            continue
        
        bars = df_5min[df_5min['date'] == trading_date]
        if bars.empty:
            continue
        
        # Extract OR
        or_data = extract_or(bars)
        if or_data is None:
            continue
        
        # RVOL filter
        rvol = compute_rvol(or_data['or_volume'], avg_volume_50d)
        if rvol < MIN_RVOL:
            continue
        
        # Create candidate
        candidate = {
            'trade_date': trading_date,
            'ticker': symbol,
            'direction': 1,
            'rvol': rvol,
            'gap_pct': gap_pct,
            'or_open': or_data['or_open'],
            'or_high': or_data['or_high'],
            'or_low': or_data['or_low'],
            'or_close': or_data['or_close'],
            'or_volume': or_data['or_volume'],
            'avg_volume_50d': avg_volume_50d,
            'prev_close': prev_close,
            'bars_json': serialize_bars(bars),
        }
        candidates.append(candidate)
    
    return candidates


def build_universe_single_file(start: str, end: str, workers: int = 1):
    """Build RC universe to single file, appending only new days."""
    days = list_trading_days(start, end)
    
    path = OUT_DIR / "universe_rc.parquet"
    
    # Load existing data to find which days are done
    processed_dates = set()
    if path.exists():
        df_existing = pd.read_parquet(path)
        processed_dates = set(df_existing['trade_date'].unique())
        print(f"Found existing universe_rc.parquet with {len(processed_dates)} days")
    
    # Filter days
    days_to_process = [d for d in days if d not in processed_dates]
    
    print(f"Found {len(days)} trading days in range")
    print(f"Already processed: {len(processed_dates)} days")
    print(f"Processing: {len(days_to_process)} new days")
    print(f"Filters: price ${MIN_PRICE}-${MAX_PRICE}, gap ≥{MIN_GAP_PCT}%, RVOL ≥{MIN_RVOL}x, volume ≥{MIN_VOLUME_50D:,}, float < {MAX_FLOAT:,}")
    print(f"Top-{TOP_N} per day")
    print(f"Workers: {workers}\n")
    
    if not days_to_process:
        print("All days already processed.")
        return
    
    # Collect new candidates
    new_candidates = []
    
    if workers > 1:
        # Parallel processing
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(scan_day, d): d for d in days_to_process}
            for future in tqdm(as_completed(futures), total=len(days_to_process), desc="Scanning"):
                try:
                    candidates = future.result()
                    new_candidates.extend(candidates)
                except Exception as e:
                    print(f"Error: {e}")
    else:
        # Serial processing
        for d in tqdm(days_to_process, desc="Scanning"):
            candidates = scan_day(d)
            new_candidates.extend(candidates)
    
    if not new_candidates:
        print("No candidates found.")
        return
    
    # Rank by RVOL within each date, keep Top-N per day
    df_new = pd.DataFrame(new_candidates)
    df_new['rvol_rank'] = df_new.groupby('trade_date')['rvol'].rank(method='first', ascending=False)
    df_new_ranked = df_new[df_new['rvol_rank'] <= TOP_N].copy()
    
    # Append to existing or create new
    if path.exists():
        df_existing = pd.read_parquet(path)
        df_final = pd.concat([df_existing, df_new_ranked], ignore_index=True)
    else:
        df_final = df_new_ranked
    
    df_final.to_parquet(path, index=False)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"✓ {path}")
    print(f"  Total candidates: {len(df_final):,}")
    print(f"  Trading days: {df_final['trade_date'].nunique()}")
    print(f"  Unique tickers: {df_final['ticker'].nunique()}")
    print(f"  Avg candidates/day: {len(df_final) / df_final['trade_date'].nunique():.1f}")
    print(f"{'='*60}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=str, required=True)
    ap.add_argument('--end', type=str, required=True)
    ap.add_argument('--workers', type=int, default=max(1, multiprocessing.cpu_count() - 1),
                    help='Parallel workers (default: CPU count - 1)')
    args = ap.parse_args()
    
    build_universe_single_file(args.start, args.end, args.workers)


if __name__ == "__main__":
    main()
