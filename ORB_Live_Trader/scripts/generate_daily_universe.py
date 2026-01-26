"""
Generate daily Top 5 universe from sentiment + bars data.
Applies filters (ATR, volume, direction), ranks by RVOL, selects Top 5.
Inserts into DuckDB daily_universe table.

Run at 09:28 ET: python scripts/generate_daily_universe.py
"""
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import duckdb

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
SENTIMENT_DIR = DATA_DIR / "sentiment"
BARS_5MIN_DIR = DATA_DIR / "bars" / "5min"
UNIVERSES_DIR = DATA_DIR / "universes"
STATE_DIR = Path(__file__).parent.parent / "state"
DB_PATH = STATE_DIR / "orb_state.duckdb"
LOG_DIR = Path(__file__).parent.parent / "logs" / "runs"

# Filters (matching backtest)
ATR_MIN = 0.5
VOLUME_MIN = 100_000
DIRECTION_LONG = 1
TOP_N = 5

def log(message: str, level: str = "INFO"):
    """Terminal logger with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{level}] [GEN_UNIVERSE] {message}")
    sys.stdout.flush()

def load_sentiment_candidates(trade_date: datetime.date) -> pd.DataFrame:
    """Load today's sentiment candidates"""
    
    sentiment_path = SENTIMENT_DIR / f"daily_{trade_date}.parquet"
    
    if not sentiment_path.exists():
        log(f"No sentiment file for {trade_date}", level="ERROR")
        return pd.DataFrame()
    
    df = pd.read_parquet(sentiment_path)
    df = df[df['trade_date'] == trade_date].copy()
    
    log(f"Loaded {len(df)} sentiment candidates")
    return df

def enrich_with_bars(candidates: pd.DataFrame, trade_date: datetime.date) -> pd.DataFrame:
    """Enrich candidates with 5-min bar OR metrics"""
    
    bars_folder = BARS_5MIN_DIR / str(trade_date)
    
    if not bars_folder.exists():
        log(f"No 5-min bars folder for {trade_date}", level="ERROR")
        return pd.DataFrame()
    
    enriched = []
    
    for _, row in candidates.iterrows():
        symbol = row['symbol']
        bar_file = bars_folder / f"{symbol}.parquet"
        
        if not bar_file.exists():
            log(f"{symbol}: No 5-min bars - skipping", level="WARNING")
            continue
        
        # Load bars and extract OR metrics (should be in first row)
        bars_df = pd.read_parquet(bar_file)
        
        if len(bars_df) == 0:
            log(f"{symbol}: Empty bars file - skipping", level="WARNING")
            continue
        
        # OR metrics are stored as columns in the bars dataframe
        first_bar = bars_df.iloc[0]
        
        enriched.append({
            'symbol': symbol,
            'sentiment_score': row['positive_score'],
            'rvol': first_bar['rvol'],
            'or_high': first_bar['or_high'],
            'or_low': first_bar['or_low'],
            'or_open': first_bar['or_open'],
            'or_close': first_bar['or_close'],
            'or_volume': first_bar['or_volume'],
            'atr_14': first_bar['atr_14'],
            'avg_volume_14': first_bar['avg_volume_14'],
            'direction': first_bar['direction']
        })
    
    enriched_df = pd.DataFrame(enriched)
    log(f"Enriched {len(enriched_df)}/{len(candidates)} candidates with bars")
    
    return enriched_df

def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Apply backtest filters: ATR, volume, direction"""
    
    initial_count = len(df)
    
    # ATR filter
    df = df[df['atr_14'] >= ATR_MIN].copy()
    log(f"After ATR filter (>= {ATR_MIN}): {len(df)}/{initial_count}")
    
    # Volume filter
    df = df[df['avg_volume_14'] >= VOLUME_MIN].copy()
    log(f"After volume filter (>= {VOLUME_MIN:,}): {len(df)}/{initial_count}")
    
    # Direction filter (LONG only)
    df = df[df['direction'] == DIRECTION_LONG].copy()
    log(f"After direction filter (LONG only): {len(df)}/{initial_count}")
    
    return df

def rank_and_select_top_n(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Rank by RVOL descending and select Top N"""
    
    df = df.sort_values('rvol', ascending=False).head(n).copy()
    log(f"Selected Top {n} by RVOL")
    
    return df

def calculate_entry_stop_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate entry (or_high) and stop prices (entry - 5% ATR)"""
    
    df['entry_price'] = df['or_high']
    df['stop_price'] = df['entry_price'] - (0.05 * df['atr_14'])
    df['stop_distance_pct'] = ((df['entry_price'] - df['stop_price']) / df['entry_price']) * 100
    
    log("Calculated entry/stop prices")
    return df

def save_to_duckdb(df: pd.DataFrame, trade_date: datetime.date):
    """Insert universe into DuckDB daily_universe table"""
    
    con = duckdb.connect(str(DB_PATH))
    
    # Delete existing records for this date (idempotent)
    con.execute("DELETE FROM daily_universe WHERE date = ?", [trade_date])
    
    # Insert new records
    insert_df = df[['symbol', 'rvol', 'entry_price', 'stop_price', 'atr_14', 
                    'or_high', 'or_low', 'or_open', 'or_close', 'or_volume',
                    'avg_volume_14', 'direction', 'sentiment_score']].copy()
    
    insert_df['date'] = trade_date
    
    con.execute("""
        INSERT INTO daily_universe 
        (date, symbol, rvol, entry_price, stop_price, atr_14, or_high, or_low, 
         or_open, or_close, or_volume, avg_volume_14, direction, sentiment_score)
        SELECT * FROM insert_df
    """)
    
    rows_inserted = con.execute("SELECT COUNT(*) FROM daily_universe WHERE date = ?", [trade_date]).fetchone()[0]
    
    con.close()
    
    log(f"Inserted {rows_inserted} records into DuckDB daily_universe")

def cleanup_old_files(retention_days: int = 30):
    """Delete old universe parquet files"""
    from datetime import timedelta
    
    cutoff_date = datetime.now().date() - timedelta(days=retention_days)
    deleted_count = 0
    
    for file in UNIVERSES_DIR.glob("*.parquet"):
        try:
            file_date = datetime.strptime(file.stem.replace("candidates_", ""), "%Y-%m-%d").date()
            
            if file_date < cutoff_date:
                file.unlink()
                deleted_count += 1
                
        except (ValueError, OSError):
            pass
    
    if deleted_count > 0:
        log(f"Deleted {deleted_count} old universe files")

def main():
    """Main pipeline"""
    
    # Setup
    UNIVERSES_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now().date()
    log(f"Generating universe for {today}")
    
    # Load sentiment candidates
    candidates = load_sentiment_candidates(today)
    
    if len(candidates) == 0:
        log("No sentiment candidates - exiting", level="ERROR")
        sys.exit(1)
    
    # Enrich with bars
    enriched = enrich_with_bars(candidates, today)
    
    if len(enriched) == 0:
        log("No enriched candidates - exiting", level="ERROR")
        sys.exit(1)
    
    # Apply filters
    filtered = apply_filters(enriched)
    
    if len(filtered) == 0:
        log("No candidates passed filters - no trades today", level="WARNING")
        # Still save empty universe to DuckDB
        empty_df = pd.DataFrame()
        output_path = UNIVERSES_DIR / f"candidates_{today}.parquet"
        empty_df.to_parquet(output_path, index=False)
        sys.exit(0)
    
    # Rank and select Top N
    top_n = rank_and_select_top_n(filtered, TOP_N)
    
    # Calculate entry/stop prices
    top_n = calculate_entry_stop_prices(top_n)
    
    # Save to parquet
    output_path = UNIVERSES_DIR / f"candidates_{today}.parquet"
    top_n.to_parquet(output_path, index=False)
    log(f"Saved universe to {output_path.name}")
    
    # Save to DuckDB
    save_to_duckdb(top_n, today)
    
    # Summary
    log("="*80)
    log(f"UNIVERSE SUMMARY ({today})")
    log("="*80)
    for _, row in top_n.iterrows():
        log(f"{row['symbol']}: RVOL={row['rvol']:.2f}, Entry=${row['entry_price']:.2f}, Stop=${row['stop_price']:.2f}, Sentiment={row['sentiment_score']:.3f}")
    log("="*80)
    
    # Cleanup
    cleanup_old_files(30)
    
    log("Universe generation completed successfully")

if __name__ == "__main__":
    main()
