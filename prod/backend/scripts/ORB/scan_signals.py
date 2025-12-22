import sys
import argparse
from pathlib import Path
import pandas as pd
import duckdb
from datetime import datetime, timedelta
from core.config import settings, get_strategy_config

# Setup paths
BASE_DIR = Path(__file__).resolve().parents[4]
DATA_DIR = BASE_DIR / "data"
DAILY_DIR = DATA_DIR / "processed" / "daily"
RAW_DIR = DATA_DIR / "raw"

def load_ticker_info():
    """Load ticker info including shares outstanding."""
    # Try multiple sources for shares outstanding
    # 1. active_tickers.csv
    path = RAW_DIR / "active_tickers.csv"
    if path.exists():
        df = pd.read_csv(path)
        # Normalize columns
        if 'shares_outstanding' in df.columns:
            return df[['ticker', 'shares_outstanding', 'name']]
        elif 'outstanding_shares' in df.columns:
            return df[['ticker', 'outstanding_shares', 'name']].rename(columns={'outstanding_shares': 'shares_outstanding'})
    
    print("Warning: Could not find shares_outstanding in active_tickers.csv")
    return pd.DataFrame(columns=['ticker', 'shares_outstanding', 'name'])

def scan_market(min_atr=0.50, min_volume=100_000, top_n=None):
    """Scan the local data for the latest trading signals."""
    
    if top_n is None:
        strategy = get_strategy_config()
        top_n = int(strategy["top_n"])

    print(f"Scanning local data in {DAILY_DIR}...")
    
    # Use DuckDB to query the latest date across all parquet files
    con = duckdb.connect()
    
    # 1. Find the latest date
    print("Finding latest available date...")
    latest_date_query = f"""
        SELECT MAX(date) as max_date 
        FROM read_parquet('{DAILY_DIR}/*.parquet')
    """
    try:
        latest_date = con.execute(latest_date_query).fetchone()[0]
    except Exception as e:
        print(f"Error reading data: {e}")
        return

    if not latest_date:
        print("No data found.")
        return

    print(f"Latest Data Date: {latest_date}")
    
    # 2. Fetch data for that date
    print("Fetching candidates...")
    # Extract ticker from filename (assumes format .../TICKER.parquet)
    # Windows path separator is backslash, but DuckDB might normalize. 
    # We'll use a regex that handles both / and \
    query = f"""
        SELECT 
            regexp_extract(filename, '.*[\\\\/]([^\\\\/]+)\.parquet', 1) as ticker,
            date, 
            open, 
            high, 
            low, 
            close, 
            volume, 
            atr_14, 
            avg_volume_14,
            shares_outstanding,
            (volume / avg_volume_14) as rvol
        FROM read_parquet('{DAILY_DIR}/*.parquet', filename=true)
        WHERE date = '{latest_date}'
        AND volume >= {min_volume}
        AND atr_14 >= {min_atr}
    """
    df_candidates = con.execute(query).fetchdf()
    
    if df_candidates.empty:
        print("No candidates found matching criteria.")
        return

    # 3. Merge with Shares Outstanding (Skipped - using data from parquet)
    # df_info = load_ticker_info()
    # if not df_info.empty:
    #     df_candidates = df_candidates.merge(df_info, on='ticker', how='left')
    # else:
    #     df_candidates['shares_outstanding'] = 0 # Default to 0 if missing
    df_candidates['name'] = 'Unknown' # Name not in daily parquet

    # 4. Filter based on Universe Settings
    universe_mode = settings.ORB_UNIVERSE.lower()
    
    if universe_mode in ("micro", "micro_small"):
        # Micro Cap definition: < 50M shares (approx <$250M cap)
        df_filtered = df_candidates[df_candidates['shares_outstanding'] < 50_000_000].copy()
        print(f"Filtered for Micro Caps (<50M shares) [Mode: {universe_mode}]. Found {len(df_filtered)}.")
    else:
        # Default to ALL (or apply other logic for 'large', etc. if defined)
        df_filtered = df_candidates.copy()
        print(f"Universe: {universe_mode.upper()} (No share count filter). Found {len(df_filtered)}.")
    
    # 5. Rank by RVOL
    df_final = df_filtered.sort_values('rvol', ascending=False).head(top_n)
    
    # 6. Output
    print(f"\n{'='*80}")
    print(f"🚀 WATCHLIST FOR NEXT SESSION (Based on Data from {latest_date})")
    print(f"Criteria: Universe={universe_mode}, ATR >= {min_atr}, Vol >= {min_volume:,}, Top {top_n} RVOL")
    print(f"{'='*80}")
    
    cols = ['ticker', 'close', 'atr_14', 'volume', 'rvol', 'shares_outstanding', 'name']
    
    # Format for display
    display_df = df_final.copy()
    display_df['volume'] = display_df['volume'].apply(lambda x: f"{x:,.0f}")
    display_df['shares_outstanding'] = display_df['shares_outstanding'].apply(lambda x: f"{x/1_000_000:.1f}M" if pd.notnull(x) else "N/A")
    display_df['rvol'] = display_df['rvol'].apply(lambda x: f"{x:.1f}x")
    display_df['atr_14'] = display_df['atr_14'].apply(lambda x: f"{x:.2f}")
    display_df['close'] = display_df['close'].apply(lambda x: f"${x:.2f}")
    
    print(display_df[cols].to_string(index=False))
    print(f"{'='*80}")
    print("\n⚠️  TRADING PLAN (LONG & SHORT):")
    print("1. Wait for Market Open (9:30 AM ET).")
    print("2. Identify Opening Range (First 5-min or 15-min candle).")
    print("3. LONG ENTRY: Buy if price breaks ABOVE the Opening Range High.")
    print("   - STOP: Set Stop Loss at 10% of ATR below Entry.")
    print("4. SHORT ENTRY: Sell if price breaks BELOW the Opening Range Low.")
    print("   - STOP: Set Stop Loss at 10% of ATR above Entry.")
    print("   (Example: If ATR is 0.50, Stop distance is $0.05)")
    print("5. SIZE: Max 1% of Daily Volume (Liquidity Cap).")

if __name__ == "__main__":
    scan_market()
