"""
Build Ross Cameron strategy candidate universes.

Scans all symbols, applies RC-specific filters:
- Price: $2–$20
- Gap: Open ≥ 2% above previous close
- RVOL: ≥ 5.0 (relative volume at 9:30 ET)
- Volume: ≥ 1M average (14-day)

Saves Top-50 per day (ranked by RVOL).

Output: universe_rc_YYYYMMDD_YYYYMMDD.parquet

Usage:
    python scripts/build_ross_cameron_universe.py --start 2021-01-01 --end 2025-12-31
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import date, time
import json
import pandas as pd
import numpy as np
from tqdm import tqdm

# DB imports
from db.database import SessionLocal
from db.models import Ticker

# Data dirs
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DATA_DIR_5MIN = DATA_DIR / "processed" / "5min"
DATA_DIR_DAILY = DATA_DIR / "processed" / "daily"
OUT_DIR = DATA_DIR / "backtest"
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


def get_low_float_tickers() -> set:
    """Fetch tickers with float < 10M from database."""
    db = SessionLocal()
    try:
        tickers = db.query(Ticker.symbol).filter(
            Ticker.float.isnot(None),
            Ticker.float < MAX_FLOAT
        ).all()
        return {t.symbol for t in tickers}
    except Exception as e:
        print(f"Error fetching float data: {e}")
        return set()
    finally:
        db.close()


def load_daily_symbol(symbol: str) -> pd.DataFrame:
    """Load daily bars for one symbol."""
    p = DATA_DIR_DAILY / f"{symbol}.parquet"
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(p)
        
        # Normalize column names
        df.columns = df.columns.str.lower()
        
        # Ensure date is datetime
        if 'date' in df.columns:
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


def compute_metrics(df_daily: pd.DataFrame) -> pd.DataFrame:
    """Add 50-day avg volume and prev_close to daily data."""
    if df_daily.empty:
        return df_daily
    
    df = df_daily.copy().sort_values('date').reset_index(drop=True)
    
    # Previous close (simple shift within this symbol's history)
    df['prev_close'] = df['close'].shift(1)
    
    # 50-day rolling average volume (RC strategy uses 50-day average)
    df['avg_volume_50d'] = df['volume'].rolling(window=50, min_periods=1).mean()
    
    # Gap % (only valid where prev_close exists)
    df['gap_pct'] = ((df['open'] - df['prev_close']) / df['prev_close'] * 100.0)
    
    return df


def extract_or(bars: pd.DataFrame) -> dict:
    """Extract 9:30 ET opening range bar."""
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


def compute_rvol(or_volume: float, avg_volume_14: float) -> float:
    """Compute relative volume at opening (scaled to full day = 78 bars)."""
    if not avg_volume_14 or avg_volume_14 <= 0:
        return 0.0
    return (or_volume * 78.0) / avg_volume_14


def serialize_bars(bars: pd.DataFrame) -> str:
    """Serialize 5-min bars to JSON."""
    bars_clean = bars[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
    bars_clean['timestamp'] = bars_clean['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return json.dumps(bars_clean.to_dict('records'))


def scan_symbol(symbol: str, start_date: date, end_date: date) -> list:
    """Scan one symbol for all RC candidates in date range."""
    # Load daily
    df_daily = load_daily_symbol(symbol)
    if df_daily.empty:
        return []
    
    # Compute metrics
    df_daily = compute_metrics(df_daily)
    
    # Filter to date range
    df_daily = df_daily[(df_daily['date'] >= start_date) & (df_daily['date'] <= end_date)]
    if df_daily.empty:
        return []
    
    # Apply basic filters
    mask = (
        (df_daily['open'] >= MIN_PRICE) &
        (df_daily['open'] <= MAX_PRICE) &
        (df_daily['gap_pct'] >= MIN_GAP_PCT) &
        (df_daily['avg_volume_50d'] >= MIN_VOLUME_50D) &
        (df_daily['prev_close'].notna())
    )

    # Apply Float Filter (Shares Outstanding)
    if 'shares_outstanding' in df_daily.columns:
        mask = mask & (df_daily['shares_outstanding'] < MAX_FLOAT) & (df_daily['shares_outstanding'] > 0)
    else:
        # If shares data is missing, we cannot verify float criteria.
        # Exclude to be safe/strict.
        return []

    df_candidates = df_daily[mask]
    
    if df_candidates.empty:
        return []
    
    # Load 5-min bars
    df_5min = load_5min_symbol(symbol)
    if df_5min.empty:
        return []
    
    # For each candidate day, extract bars and compute RVOL
    candidates = []
    for _, row in df_candidates.iterrows():
        trading_date = row['date']
        
        # Get 5-min bars for this day
        bars = df_5min[df_5min['date'] == trading_date]
        if bars.empty:
            continue
        
        bars = bars.sort_values('timestamp').reset_index(drop=True)
        
        # Extract OR bar
        or_data = extract_or(bars)
        if or_data is None:
            continue
        
        # Compute RVOL (relative to 50-day average)
        rvol = compute_rvol(or_data['or_volume'], row['avg_volume_50d'])
        if rvol < MIN_RVOL:
            continue
        
        # Direction
        if or_data['or_close'] > or_data['or_open']:
            direction = 1
        elif or_data['or_close'] < or_data['or_open']:
            direction = -1
        else:
            continue  # Doji, skip
        
        # Create candidate
        candidate = {
            'trade_date': trading_date,
            'ticker': symbol,
            'direction': direction,
            'rvol': rvol,
            'gap_pct': row['gap_pct'],
            'or_open': or_data['or_open'],
            'or_high': or_data['or_high'],
            'or_low': or_data['or_low'],
            'or_close': or_data['or_close'],
            'or_volume': or_data['or_volume'],
            'avg_volume_50d': float(row['avg_volume_50d']),
            'prev_close': float(row['prev_close']),
            'shares_outstanding': int(row['shares_outstanding']) if 'shares_outstanding' in row else None,
            'bars_json': serialize_bars(bars),
        }
        candidates.append(candidate)
    
    return candidates


def build_universe(start: str, end: str):
    """Build universe by scanning all symbols."""
    start_date = pd.to_datetime(start).date()
    end_date = pd.to_datetime(end).date()
    
    # Get list of all symbol files
    symbol_files = sorted(DATA_DIR_DAILY.glob('*.parquet'))
    all_symbols = {p.stem for p in symbol_files}
    
    # We no longer pre-filter by DB float. We filter dynamically per day.
    symbols = sorted(list(all_symbols))
    
    print(f"Building Ross Cameron universe from {len(symbols)} symbols")
    print(f"Date range: {start_date} to {end_date}")
    print(f"Filters: price ${MIN_PRICE}-${MAX_PRICE}, gap ≥{MIN_GAP_PCT}%, RVOL ≥{MIN_RVOL}x, volume ≥{MIN_VOLUME_50D:,} (50-day avg), float < {MAX_FLOAT:,}")
    print(f"Top-{TOP_N} per day\n")
    
    if not symbols:
        print("No symbols to scan!")
        return

    # Scan all symbols
    all_candidates = []
    for symbol in tqdm(symbols, desc="Scanning symbols"):
        candidates = scan_symbol(symbol, start_date, end_date)
        all_candidates.extend(candidates)
    
    if not all_candidates:
        print("No candidates found!")
        return
    
    # Group by date and rank by RVOL
    df_all = pd.DataFrame(all_candidates)
    
    # Rank by RVOL within each date, keep Top-N per day
    df_ranked = df_all.copy()
    df_ranked['rvol_rank'] = df_ranked.groupby('trade_date')['rvol'].rank(method='first', ascending=False)
    df_final = df_ranked[df_ranked['rvol_rank'] <= TOP_N].copy()
    
    # Save
    date_suffix = f"{start.replace('-', '')}_{end.replace('-', '')}"
    path_out = OUT_DIR / f"universe_rc_{date_suffix}.parquet"
    df_final.to_parquet(path_out, index=False)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"✓ {path_out}")
    print(f"  Total candidates: {len(df_final):,}")
    print(f"  Trading days: {df_final['trade_date'].nunique()}")
    print(f"  Unique tickers: {df_final['ticker'].nunique()}")
    print(f"  Avg candidates/day: {len(df_final) / df_final['trade_date'].nunique():.1f}")
    print(f"{'='*60}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=str, required=True)
    ap.add_argument('--end', type=str, required=True)
    args = ap.parse_args()
    
    build_universe(args.start, args.end)


if __name__ == "__main__":
    main()
