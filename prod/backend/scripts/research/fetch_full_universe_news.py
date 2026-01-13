"""
Fetch Full Universe News (Research)
===================================
Fetches 1 year of news for the entire Micro-Cap Universe (2,744 symbols) to support
the "Sentiment First" research hypothesis.

Output: data/research/news_full_universe.parquet
"""

import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from tqdm import tqdm
import time

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest
from core.config import settings

# Config
UNIVERSE_FILE = PROJECT_ROOT / "data" / "backtest" / "orb" / "universe" / "universe_micro_full.parquet"
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "news"
OUTPUT_FILE = OUTPUT_DIR / "news_micro_full_1y.parquet"
DAYS_LOOKBACK = 365
BATCH_SIZE = 40  # Symbols per request (safe limit)

def fetch_news_batch(client, symbols, start_dt, end_dt):
    """Fetch news for a batch of symbols with pagination."""
    all_items = []
    
    # Alpaca 'next_page_token' logic can be tricky, relying on date loop is safer 
    # if volume is huge, but for micro caps, simple pagination should work.
    
    page_token = None
    
    while True:
        try:
            req = NewsRequest(
                symbols=",".join(symbols),
                start=start_dt,
                end=end_dt,
                limit=50,
                page_token=page_token,
                include_content=False
            )
            resp = client.get_news(req)
            
            # Robust handling of response (NewsSet or similar)
            items = []
            if hasattr(resp, "news"):
                items = resp.news
            elif isinstance(resp, list):
                items = resp
            elif hasattr(resp, "data"):
                items = resp.data
                if isinstance(items, dict) and "news" in items:
                    items = items["news"]
            
            if not items:  # Fallback: maybe the response is iterable?
                try:
                    items = list(resp)
                except TypeError:
                    pass

            if not items:
                break
                
            for n in items:
                all_items.append({
                    "symbol": n.symbols[0] if n.symbols else "UNKNOWN", # Primary symbol
                    "timestamp": n.created_at,
                    "headline": n.headline,
                    "summary": n.summary,
                    "url": n.url,
                    "source": n.source
                })
            
            page_token = getattr(resp, "next_page_token", None)
            if not page_token:
                break
                
            time.sleep(0.1) # Rate limit niceness
            
        except Exception as e:
            print(f"Error fetching batch: {e}")
            time.sleep(1)
            break
            
    return all_items

def main():
    if not settings.ALPACA_API_KEY:
        print("Error: ALPACA_API_KEY not set.")
        return

    if not UNIVERSE_FILE.exists():
        print(f"Error: Universe file not found: {UNIVERSE_FILE}")
        return

    print(f"Loading universe from {UNIVERSE_FILE.name}...")
    df = pd.read_parquet(UNIVERSE_FILE)
    
    # Identify symbol column
    col = 'ticker' if 'ticker' in df.columns else 'symbol'
    unique_symbols = sorted(df[col].unique())
    print(f"Total Symbols to Scan: {len(unique_symbols)}")
    
    # Setup Range (2021 Full Year)
    start_dt = datetime(2021, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(2021, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    print(f"Time Range: {start_dt.date()} to {end_dt.date()}")

    # Init Client
    client = NewsClient(settings.ALPACA_API_KEY, settings.ALPACA_API_SECRET)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    all_news_rows = []
    
    # Chunk symbols
    chunks = [unique_symbols[i:i + BATCH_SIZE] for i in range(0, len(unique_symbols), BATCH_SIZE)]
    
    print(f"Processing in {len(chunks)} batches...")
    
    for i, batch in enumerate(tqdm(chunks, desc="Fetching News")):
        news_items = fetch_news_batch(client, batch, start_dt, end_dt)
        if news_items:
            all_news_rows.extend(news_items)
            
        # Optional: Save intermediate results every 10 batches
        if (i + 1) % 10 == 0 and all_news_rows:
             temp_df = pd.DataFrame(all_news_rows)
             temp_df.to_parquet(OUTPUT_DIR / "news_partial.parquet")
    
    if not all_news_rows:
        print("No news found.")
        return

    print("Saving final dataset...")
    final_df = pd.DataFrame(all_news_rows)
    # Deduplicate in case of overlap (though unlikely with unique batches)
    final_df = final_df.drop_duplicates(subset=['headline', 'symbol', 'timestamp'])
    
    final_df.to_parquet(OUTPUT_FILE)
    print(f"✅ Saved {len(final_df)} news items to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
