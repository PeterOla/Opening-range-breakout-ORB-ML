import sys
from pathlib import Path
import pandas as pd
import json
from datetime import datetime
import logging

# Setup paths
# This script is in prod/backend/scripts/
# We want to add prod/backend to sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from scripts.DataPipeline.config import DATA_RAW, DAILY_DIR

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("populate_ignore")

def main():
    logger.info("Starting population of missing shares ignore list...")

    # 1. Load All Tickers
    tickers_path = DATA_RAW / "nasdaq_nyse_tickers.csv"
    if not tickers_path.exists():
        logger.error("nasdaq_nyse_tickers.csv not found.")
        return

    tickers = pd.read_csv(tickers_path)
    all_symbols = set(tickers['symbol'].unique())
    logger.info(f"Total symbols in universe: {len(all_symbols)}")

    # 2. Load Existing Shares
    shares_path = DATA_RAW / "historical_shares.parquet"
    if shares_path.exists():
        existing = pd.read_parquet(shares_path)
        existing_symbols = set(existing['symbol'].dropna().unique())
    else:
        existing_symbols = set()
    
    logger.info(f"Symbols with shares in parquet: {len(existing_symbols)}")

    # 3. Identify candidates (missing from parquet)
    candidates = sorted([s for s in (all_symbols - existing_symbols) if pd.notna(s)])
    logger.info(f"Candidates missing from parquet: {len(candidates)}")

    # 4. Check Daily Parquet files (to exclude ones that have shares locally)
    really_missing = []
    
    logger.info(f"Checking {len(candidates)} candidate files for local shares data...")
    for i, symbol in enumerate(candidates):
        if i % 100 == 0:
            print(f"Checked {i}/{len(candidates)}...", end='\r')
            
        daily_path = DAILY_DIR / f"{symbol}.parquet"
        has_local = False
        if daily_path.exists():
            try:
                # Try to read just the columns we need
                # Note: If 'shares_outstanding' is missing, read_parquet might fail if we request it specifically in some versions
                # So we read all and check columns
                df = pd.read_parquet(daily_path)
                if 'shares_outstanding' in df.columns and df['shares_outstanding'].notna().any():
                    has_local = True
            except Exception:
                pass
        
        if not has_local:
            really_missing.append(symbol)

    print(f"Checked {len(candidates)}/{len(candidates)}")
    logger.info(f"Confirmed missing shares for: {len(really_missing)} symbols")

    # 5. Write to ignore list
    ignore_file = DATA_RAW / "missing_shares_ignore.json"
    
    current_ignore = {}
    if ignore_file.exists():
        try:
            with open(ignore_file, 'r') as f:
                current_ignore = json.load(f)
        except:
            pass
    
    today = datetime.now().isoformat()
    count_new = 0
    for s in really_missing:
        if s not in current_ignore:
            current_ignore[s] = today
            count_new += 1
            
    with open(ignore_file, 'w') as f:
        json.dump(current_ignore, f, indent=2)
        
    logger.info(f"Added {count_new} symbols to {ignore_file}")
    logger.info(f"Total ignored symbols: {len(current_ignore)}")

if __name__ == "__main__":
    main()
