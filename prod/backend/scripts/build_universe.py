"""
Build daily ORB candidate universes (one-time scan, cache for fast testing).

Scans all symbols once, splits into ATR ≥ 0.20 and ATR ≥ 0.50 universes.
Saves Top-50 per day (ranked by RVOL) for flexibility.

Output: universe_020_*.parquet and universe_050_*.parquet

Usage:
    python scripts/build_universe.py --start 2021-01-01 --end 2025-12-31
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import date, time
from typing import Optional, List
import pandas as pd
import numpy as np
from tqdm import tqdm
import duckdb
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# Data dirs
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DATA_DIR_5MIN = DATA_DIR / "processed" / "5min"
DATA_DIR_DAILY = DATA_DIR / "processed" / "daily"
OUT_DIR = DATA_DIR / "backtest"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OR_START = time(9, 30)
TOP_N = 50  # Save Top-50 per day for flexibility


def list_trading_days(start: str, end: str) -> List[date]:
    """Build trading days from daily parquet data."""
    con = duckdb.connect()
    df_dates = con.execute(f"""
      SELECT DISTINCT CAST(date AS DATE) AS d
      FROM read_parquet('{DATA_DIR_DAILY.as_posix()}/**/*.parquet', union_by_name=true)
      WHERE date >= DATE '{start}' AND date <= DATE '{end}'
      ORDER BY d
    """).df()
    con.close()
    return list(df_dates['d'])


def load_daily(symbol: str) -> Optional[pd.DataFrame]:
    p = DATA_DIR_DAILY / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        if 'date' not in df.columns or df.empty:
            return None
        return df
    except Exception:
        return None


def load_5min(symbol: str, trading_date: date) -> Optional[pd.DataFrame]:
    p = DATA_DIR_5MIN / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        if df.empty:
            return None
        ts_col = 'timestamp' if 'timestamp' in df.columns else ('date' if 'date' in df.columns else None)
        if ts_col is None:
            return None
        dt = pd.to_datetime(df[ts_col])
        df['datetime'] = dt
        df['date_only'] = df['datetime'].dt.date
        day = df[df['date_only'] == trading_date].copy()
        if day.empty:
            return None
        day['time'] = day['datetime'].dt.time
        return day.sort_values('datetime').reset_index(drop=True)
    except Exception:
        return None


def extract_or(bars: pd.DataFrame) -> Optional[dict]:
    """Extract the 9:30 ET bar as the Opening Range."""
    or_row = bars[bars['time'] == OR_START]
    if or_row.empty:
        return None
    r = or_row.iloc[0]
    return {
        'or_open': float(r['open']),
        'or_high': float(r['high']),
        'or_low': float(r['low']),
        'or_close': float(r['close']),
        'or_volume': float(r['volume']),
    }


def compute_daily_metrics(df_daily: pd.DataFrame, target_date: date) -> Optional[dict]:
    """Compute ATR(14), avg volume(14), prev close."""
    hist = df_daily[df_daily['date'] < target_date].sort_values('date').tail(20)
    if hist.empty:
        return None
    hist = hist.copy()
    hist['prev_close_calc'] = hist['close'].shift(1)
    hist = hist.dropna(subset=['prev_close_calc'])
    if len(hist) < 14:
        return None
    tr = np.maximum(hist['high'] - hist['prev_close_calc'],
                    np.maximum(hist['prev_close_calc'] - hist['low'], hist['high'] - hist['low']))
    atr14 = pd.Series(tr).rolling(14).mean().iloc[-1] if len(tr) >= 14 else np.nan
    avg_vol14 = hist['volume'].rolling(14).mean().iloc[-1] if len(hist) >= 14 else np.nan
    prev_row = df_daily[df_daily['date'] < target_date].sort_values('date').tail(1)
    prev_close = float(prev_row['close'].iloc[0]) if not prev_row.empty else np.nan
    return {
        'atr_14': float(atr14) if not np.isnan(atr14) else None,
        'avg_volume_14': float(avg_vol14) if not np.isnan(avg_vol14) else None,
        'prev_close': prev_close if not np.isnan(prev_close) else None,
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


def build_day_universe(trading_date: date, min_price: float, min_volume: int) -> dict:
    """Build candidates for one day. Returns dict with atr020 and atr050 lists (Top-50 each)."""
    if hasattr(trading_date, 'date'):
        trading_date = trading_date.date()
    
    candidates_020 = []
    candidates_050 = []
    symbols = [p.stem for p in DATA_DIR_DAILY.glob("*.parquet")]
    
    for symbol in symbols:
        df_daily = load_daily(symbol)
        if df_daily is None or trading_date not in set(df_daily['date']):
            continue
        
        metrics = compute_daily_metrics(df_daily, trading_date)
        if not metrics:
            continue
        
        bars = load_5min(symbol, trading_date)
        if bars is None:
            continue
        
        or_data = extract_or(bars)
        if or_data is None:
            continue
        
        # Base filters
        if or_data['or_open'] < min_price:
            continue
        if not metrics['avg_volume_14'] or metrics['avg_volume_14'] < min_volume:
            continue
        
        # Direction
        if or_data['or_close'] > or_data['or_open']:
            direction = 1
        elif or_data['or_close'] < or_data['or_open']:
            direction = -1
        else:
            continue  # doji
        
        rvol = compute_rvol(or_data['or_volume'], metrics['avg_volume_14'])
        if rvol < 1.0:
            continue
        
        # Base candidate
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
            'atr_14': metrics['atr_14'],
            'avg_volume_14': metrics['avg_volume_14'],
            'prev_close': metrics['prev_close'],
            'bars_json': serialize_bars(bars),
        }
        
        # Split by ATR
        if metrics['atr_14'] and metrics['atr_14'] >= 0.50:
            candidates_050.append(candidate.copy())
        if metrics['atr_14'] and metrics['atr_14'] >= 0.20:
            candidates_020.append(candidate.copy())
    
    # Sort by RVOL, take Top-50, add ranks
    for candidates_list in [candidates_020, candidates_050]:
        if candidates_list:
            candidates_list.sort(key=lambda x: x['rvol'], reverse=True)
            candidates_list[:] = candidates_list[:TOP_N]  # Limit to Top-50
            for rank, c in enumerate(candidates_list, 1):
                c['rvol_rank'] = rank
    
    return {'atr020': candidates_020, 'atr050': candidates_050}


def save_checkpoint(candidates_020, candidates_050, df_020_existing, df_050_existing, path_020, path_050):
    """Save checkpoint to parquet."""
    df_020_new = pd.DataFrame(candidates_020) if candidates_020 else pd.DataFrame()
    df_050_new = pd.DataFrame(candidates_050) if candidates_050 else pd.DataFrame()
    
    # Merge with existing
    if df_020_existing is not None and not df_020_new.empty:
        df_020_final = pd.concat([df_020_existing, df_020_new], ignore_index=True)
    elif df_020_existing is not None:
        df_020_final = df_020_existing
    elif not df_020_new.empty:
        df_020_final = df_020_new
    else:
        df_020_final = pd.DataFrame()
    
    if df_050_existing is not None and not df_050_new.empty:
        df_050_final = pd.concat([df_050_existing, df_050_new], ignore_index=True)
    elif df_050_existing is not None:
        df_050_final = df_050_existing
    elif not df_050_new.empty:
        df_050_final = df_050_new
    else:
        df_050_final = pd.DataFrame()
    
    # Write
    if not df_020_final.empty:
        df_020_final.to_parquet(path_020, index=False)
    if not df_050_final.empty:
        df_050_final.to_parquet(path_050, index=False)
    
    return df_020_final, df_050_final


def build_universe(start: str, end: str, min_price: float, min_volume: int, workers: int = 1):
    """Build two universes (ATR ≥ 0.20 and ATR ≥ 0.50) with checkpointing and optional parallelism."""
    days = list_trading_days(start, end)
    print(f"Building TWO universes for {len(days)} trading days")
    print(f"Filters: price ≥ ${min_price}, volume ≥ {min_volume:,}, RVOL ≥ 1.0")
    print(f"Saving Top-{TOP_N} per day per universe")
    print(f"Workers: {workers} | Checkpoint: every 50 days\n")
    
    # Paths
    date_suffix = f"{start.replace('-', '')}_{end.replace('-', '')}"
    path_020 = OUT_DIR / f"universe_020_{date_suffix}.parquet"
    path_050 = OUT_DIR / f"universe_050_{date_suffix}.parquet"
    
    # Resume from checkpoint
    if path_020.exists():
        df_020_existing = pd.read_parquet(path_020)
        processed = set(df_020_existing['trade_date'].unique())
        days = [d for d in days if d not in processed]
        print(f"Resuming: {len(processed)} days done, {len(days)} remaining\n")
        df_050_existing = pd.read_parquet(path_050) if path_050.exists() else None
    else:
        df_020_existing = None
        df_050_existing = None
    
    if not days:
        print("All days already processed.")
        return
    
    candidates_020 = []
    candidates_050 = []
    checkpoint_counter = 0
    
    if workers > 1:
        # Parallel processing
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(build_day_universe, d, min_price, min_volume): d for d in days}
            for future in tqdm(as_completed(futures), total=len(days), desc=f"Scanning ({workers} workers)"):
                try:
                    day_result = future.result()
                    candidates_020.extend(day_result['atr020'])
                    candidates_050.extend(day_result['atr050'])
                    
                    checkpoint_counter += 1
                    if checkpoint_counter >= 50:
                        df_020_existing, df_050_existing = save_checkpoint(
                            candidates_020, candidates_050,
                            df_020_existing, df_050_existing,
                            path_020, path_050
                        )
                        candidates_020 = []
                        candidates_050 = []
                        checkpoint_counter = 0
                except Exception as e:
                    print(f"Error processing day: {e}")
    else:
        # Serial processing
        for d in tqdm(days, desc="Scanning"):
            day_result = build_day_universe(d, min_price, min_volume)
            candidates_020.extend(day_result['atr020'])
            candidates_050.extend(day_result['atr050'])
            
            checkpoint_counter += 1
            if checkpoint_counter >= 50:
                df_020_existing, df_050_existing = save_checkpoint(
                    candidates_020, candidates_050,
                    df_020_existing, df_050_existing,
                    path_020, path_050
                )
                candidates_020 = []
                candidates_050 = []
                checkpoint_counter = 0
    
    # Final save
    df_020_final, df_050_final = save_checkpoint(
        candidates_020, candidates_050,
        df_020_existing, df_050_existing,
        path_020, path_050
    )
    
    # Summary
    print(f"\n{'='*60}")
    print(f"✓ {path_020}")
    if not df_020_final.empty:
        print(f"  Candidates: {len(df_020_final):,} | Days: {df_020_final['trade_date'].nunique()} | Tickers: {df_020_final['ticker'].nunique()}")
    
    print(f"\n✓ {path_050}")
    if not df_050_final.empty:
        print(f"  Candidates: {len(df_050_final):,} | Days: {df_050_final['trade_date'].nunique()} | Tickers: {df_050_final['ticker'].nunique()}")
    print(f"{'='*60}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=str, required=True)
    ap.add_argument('--end', type=str, required=True)
    ap.add_argument('--min-price', type=float, default=5.0)
    ap.add_argument('--min-volume', type=int, default=1_000_000)
    ap.add_argument('--workers', type=int, default=max(1, multiprocessing.cpu_count() - 1),
                    help='Parallel workers (default: CPU count - 1)')
    args = ap.parse_args()
    
    build_universe(args.start, args.end, args.min_price, args.min_volume, args.workers)


if __name__ == "__main__":
    main()
