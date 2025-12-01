"""
Pre-compute daily metrics (ATR, avg volume, prev close) from parquet files.

Reads all daily parquet files from data/processed/daily/ and computes:
- 14-day ATR
- 14-day average volume
- Previous day close
- Filter flags (price >= $5, ATR >= $0.50, avg_vol >= 1M)

Stores results in daily_metrics_historical table.

Usage:
    python scripts/compute_daily_metrics.py [--symbols AAPL,MSFT] [--start 2021-01-01] [--end 2025-11-28]
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
from tqdm import tqdm
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from db.database import engine, SessionLocal
from db.models import DailyMetricsHistorical


# Constants
DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "processed" / "daily"
MIN_PRICE = 5.0
MIN_ATR = 0.50
MIN_AVG_VOLUME = 1_000_000
ATR_PERIOD = 14
BATCH_SIZE = 10000  # Insert in batches for performance


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()
    
    return atr


def compute_avg_volume(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute rolling average volume."""
    return df['volume'].rolling(window=period).mean()


def process_symbol(symbol: str, start_date: str = None, end_date: str = None) -> list[dict]:
    """Process a single symbol's parquet file."""
    parquet_path = DATA_DIR / f"{symbol}.parquet"
    
    if not parquet_path.exists():
        return []
    
    try:
        df = pd.read_parquet(parquet_path)
    except Exception as e:
        print(f"Error reading {symbol}: {e}")
        return []
    
    if df.empty:
        return []
    
    # Ensure date is datetime
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    
    # Filter by date range if specified
    if start_date:
        df = df[df['date'] >= start_date]
    if end_date:
        df = df[df['date'] <= end_date]
    
    if df.empty:
        return []
    
    # Compute metrics
    df['atr_14'] = compute_atr(df, ATR_PERIOD)
    df['avg_volume_14'] = compute_avg_volume(df, ATR_PERIOD)
    df['prev_close'] = df['close'].shift(1)
    
    # Filter flags
    df['meets_price_filter'] = df['close'] >= MIN_PRICE
    df['meets_atr_filter'] = df['atr_14'] >= MIN_ATR
    df['meets_volume_filter'] = df['avg_volume_14'] >= MIN_AVG_VOLUME
    df['passes_all_filters'] = (
        df['meets_price_filter'] & 
        df['meets_atr_filter'] & 
        df['meets_volume_filter']
    )
    
    # Only keep rows where we have enough history for ATR calculation
    df = df.dropna(subset=['atr_14', 'avg_volume_14', 'prev_close'])
    
    if df.empty:
        return []
    
    # Convert to records
    records = []
    for _, row in df.iterrows():
        # Convert pandas Timestamp to Python datetime
        date_val = row['date']
        if hasattr(date_val, 'to_pydatetime'):
            date_val = date_val.to_pydatetime()
        
        records.append({
            'symbol': symbol,
            'date': date_val,
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': float(row['volume']),
            'atr_14': float(row['atr_14']),
            'avg_volume_14': float(row['avg_volume_14']),
            'prev_close': float(row['prev_close']),
            'meets_price_filter': bool(row['meets_price_filter']),
            'meets_atr_filter': bool(row['meets_atr_filter']),
            'meets_volume_filter': bool(row['meets_volume_filter']),
            'passes_all_filters': bool(row['passes_all_filters']),
        })
    
    return records


def bulk_insert_metrics(records: list[dict]):
    """Bulk insert metrics to database in smaller chunks (no upsert)."""
    if not records:
        return 0
    
    CHUNK_SIZE = 500  # Smaller chunks to avoid memory issues
    inserted = 0
    
    for i in range(0, len(records), CHUNK_SIZE):
        chunk = records[i:i + CHUNK_SIZE]
        
        with engine.connect() as conn:
            # Simple insert without conflict handling (faster)
            stmt = insert(DailyMetricsHistorical.__table__).values(chunk)
            try:
                conn.execute(stmt)
                conn.commit()
                inserted += len(chunk)
            except Exception as e:
                # Skip if duplicate
                conn.rollback()
                # Try one by one
                for rec in chunk:
                    try:
                        single_stmt = insert(DailyMetricsHistorical.__table__).values([rec])
                        with engine.connect() as c2:
                            c2.execute(single_stmt)
                            c2.commit()
                            inserted += 1
                    except Exception:
                        pass  # Skip duplicates
    
    return inserted


def get_processed_symbols() -> set:
    """Get set of symbols that have already been processed."""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT DISTINCT symbol FROM daily_metrics_historical"))
        return {row[0] for row in result.fetchall()}


def main():
    parser = argparse.ArgumentParser(description='Compute daily metrics from parquet files')
    parser.add_argument('--symbols', type=str, help='Comma-separated list of symbols (default: all)')
    parser.add_argument('--start', type=str, default='2021-01-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=None, help='End date (YYYY-MM-DD)')
    parser.add_argument('--skip-existing', action='store_true', help='Skip symbols already in DB')
    args = parser.parse_args()
    
    # Get list of symbols
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
    else:
        symbols = [f.stem for f in DATA_DIR.glob('*.parquet')]
    
    # Skip already processed symbols if requested
    if args.skip_existing:
        processed = get_processed_symbols()
        original_count = len(symbols)
        symbols = [s for s in symbols if s not in processed]
        print(f"Skipping {original_count - len(symbols)} already processed symbols")
    
    print(f"Processing {len(symbols)} symbols from {args.start} to {args.end or 'latest'}")
    print(f"Data directory: {DATA_DIR}")
    
    if not symbols:
        print("No symbols to process.")
        return
    
    # Process symbols with progress bar
    total_records = 0
    batch_records = []
    
    for symbol in tqdm(symbols, desc="Computing metrics"):
        records = process_symbol(symbol, args.start, args.end)
        batch_records.extend(records)
        
        # Insert in batches
        if len(batch_records) >= BATCH_SIZE:
            inserted = bulk_insert_metrics(batch_records)
            total_records += inserted
            batch_records = []
    
    # Insert remaining records
    if batch_records:
        inserted = bulk_insert_metrics(batch_records)
        total_records += inserted
    
    print(f"\n✓ Inserted {total_records:,} daily metrics records")
    
    # Print summary stats
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT symbol) as symbols,
                MIN(date) as min_date,
                MAX(date) as max_date,
                SUM(CASE WHEN passes_all_filters THEN 1 ELSE 0 END) as passing_filter
            FROM daily_metrics_historical
        """))
        row = result.fetchone()
        print(f"\nDatabase summary:")
        print(f"  Total records: {row[0]:,}")
        print(f"  Unique symbols: {row[1]:,}")
        print(f"  Date range: {row[2]} to {row[3]}")
        print(f"  Passing all filters: {row[4]:,} ({row[4]/row[0]*100:.1f}%)")


if __name__ == "__main__":
    main()
