"""
Fetch Full Universe News (Backtest Pipeline)
============================================
Fetches 1 year of news for the entire Micro-Cap Universe (2,744 symbols).

Output: ORB_Live_Trader/backtest/data/news/news_micro_full_1y.parquet
"""

import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from tqdm import tqdm
import time
import os

# Add project root to path (for core.config if needed, or just dotenv here)
PROJECT_ROOT = Path(__file__).resolve().parents[3] # ORB_Live_Trader/backtest/pipeline -> ORB_Live_Trader -> .. -> Root
# ORB_Live_Trader is the root for this context if we want to be self-contained?
# But we need settings.ALPACA_API_KEY. Assuming .env is at ORB_Live_Trader/config/.env

sys.path.insert(0, str(PROJECT_ROOT))

# Load Env directly if core.config not available or complex
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "config" / ".env")

try:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
except ImportError:
    print("Error: alpaca-py not installed.")
    sys.exit(1)

# Config
# Input Universe (Assuming it exists in main data dir or needs to be copied)
# User mapped c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)
DATA_DIR = PROJECT_ROOT / "data" 
UNIVERSE_FILE = DATA_DIR / "backtest" / "orb" / "universe" / "universe_micro_full.parquet"

# Output relative to THIS script location
PIPELINE_DIR = Path(__file__).parent
BACKTEST_DIR = PIPELINE_DIR.parent
OUTPUT_DIR = BACKTEST_DIR / "data" / "news"
OUTPUT_FILE = OUTPUT_DIR / "news_micro_full_1y.parquet"

BATCH_SIZE = 40  # Symbols per request

def fetch_news_batch(client, symbols, start_dt, end_dt):
    """Fetch news for a batch of symbols using Time-Walking pagination (Backwards)."""
    all_items = []
    
    current_end = end_dt
    
    while True:
        try:
            req = NewsRequest(
                symbols=",".join(symbols),
                start=start_dt,
                end=current_end,
                limit=50,
                include_content=False,
                sort="DESC" # Explicitly request newest first
            )
            
            resp = client.get_news(req)
            
            # Robust extraction
            items = []
            if hasattr(resp, "news"):
                items = resp.news
            elif isinstance(resp, list):
                items = resp
            elif hasattr(resp, "data"):
                items = resp.data
                if isinstance(items, dict) and "news" in items:
                    items = items["news"]
            
            if not items:
                break
                
            for n in items:
                # Find which of our queried symbols appear in this news item
                matched_symbols = [s for s in symbols if s in n.symbols]
                
                # Create one row per matched symbol (handles multi-mention news)
                for symbol in matched_symbols:
                    all_items.append({
                        "symbol": symbol,
                        "timestamp": n.created_at,
                        "headline": n.headline,
                        "summary": n.summary,
                        "url": n.url,
                        "source": n.source
                    })
            
            # Time Walking Logic
            oldest_ts = items[-1].created_at
            
            if len(items) < 50:
                break
                
            current_end = oldest_ts - timedelta(microseconds=1)
            
            if current_end <= start_dt:
                break
                
            time.sleep(0.1) 
            
        except Exception as e:
            print(f"Error fetching batch: {e}")
            time.sleep(1)
            break
            
    return all_items

def main():
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    
    if not api_key:
        print("Error: ALPACA_API_KEY not set in environment.")
        return

    if not UNIVERSE_FILE.exists():
        print(f"Error: Universe file not found: {UNIVERSE_FILE}")
        # Try finding it in the project if path changed
        # Fallback to local copy if user provided?
        return

    print(f"Loading universe from {UNIVERSE_FILE.name}...")
    df = pd.read_parquet(UNIVERSE_FILE)
    
    col = 'ticker' if 'ticker' in df.columns else 'symbol'
    unique_symbols = sorted(df[col].unique())
    print(f"Total Symbols to Scan: {len(unique_symbols)}")
    
    # Setup Range (2021 Full Year)
    start_dt = datetime(2021, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(2021, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    print(f"Time Range: {start_dt.date()} to {end_dt.date()}")

    # Init Client
    client = NewsClient(api_key, api_secret)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    all_news_rows = []
    chunks = [unique_symbols[i:i + BATCH_SIZE] for i in range(0, len(unique_symbols), BATCH_SIZE)]
    
    print(f"Processing in {len(chunks)} batches...")
    
    for i, batch in enumerate(tqdm(chunks, desc="Fetching News")):
        news_items = fetch_news_batch(client, batch, start_dt, end_dt)
        if news_items:
            all_news_rows.extend(news_items)
            
        if (i + 1) % 10 == 0 and all_news_rows:
             temp_df = pd.DataFrame(all_news_rows)
             # Optional: temp save
             # temp_df.to_parquet(OUTPUT_DIR / "news_partial.parquet")
    
    if not all_news_rows:
        print("No news found.")
        return

    print("Saving final dataset...")
    final_df = pd.DataFrame(all_news_rows)
    final_df = final_df.drop_duplicates(subset=['headline', 'symbol', 'timestamp'])
    
    final_df.to_parquet(OUTPUT_FILE)
    print(f"✅ Saved {len(final_df)} news items to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
