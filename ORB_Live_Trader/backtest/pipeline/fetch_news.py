"""
Fetch Full Universe News (Backtest Pipeline)
============================================
Fetches 1 year of news for the entire Micro-Cap Universe (2,744 symbols).

Output: C:\Users\Olale\Documents\Financial Data\news\news_micro_full_1y.parquet
"""

import sys
import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from tqdm import tqdm
import time
import os

# Paths
PIPELINE_DIR = Path(__file__).parent
BACKTEST_DIR = PIPELINE_DIR.parent
ORB_LIVE_TRADER_DIR = BACKTEST_DIR.parent  # ORB_Live_Trader/

# Add ORB_Live_Trader to path for dotenv
sys.path.insert(0, str(ORB_LIVE_TRADER_DIR))

from dotenv import load_dotenv
load_dotenv(ORB_LIVE_TRADER_DIR / "config" / ".env")

try:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
except ImportError:
    print("Error: alpaca-py not installed.")
    sys.exit(1)

# Universe file (micro-cap reference list)
UNIVERSE_FILE = ORB_LIVE_TRADER_DIR / "data" / "reference" / "universe_micro_full.parquet"

# Output directory
SHARED_DATA_ROOT = Path(r"C:\Users\Olale\Documents\Financial Data")
OUTPUT_DIR = SHARED_DATA_ROOT / "news"

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
    parser = argparse.ArgumentParser(description="Fetch news for ORB backtest pipeline")
    parser.add_argument("--start-date", type=str, default="2021-01-01", help="Start date YYYY-MM-DD (default: 2021-01-01)")
    parser.add_argument("--end-date", type=str, default="2021-12-31", help="End date YYYY-MM-DD (default: 2021-12-31)")
    parser.add_argument("--output", type=str, default="news_micro_full_1y.parquet", help="Output filename in shared news directory (default: news_micro_full_1y.parquet)")
    args = parser.parse_args()

    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET") or os.getenv("ALPACA_SECRET_KEY")

    if not api_key:
        print("Error: ALPACA_API_KEY not set in environment.")
        return

    if not UNIVERSE_FILE.exists():
        print(f"Error: Universe file not found: {UNIVERSE_FILE}")
        return

    print(f"Loading universe from {UNIVERSE_FILE.name}...")
    df = pd.read_parquet(UNIVERSE_FILE)

    col = 'ticker' if 'ticker' in df.columns else 'symbol'
    unique_symbols = sorted(df[col].unique())
    print(f"Total Symbols to Scan: {len(unique_symbols)}")

    # Parse date range
    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    print(f"Time Range: {start_dt.date()} to {end_dt.date()}")

    output_file = OUTPUT_DIR / args.output

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

    final_df.to_parquet(output_file)
    print(f"✅ Saved {len(final_df)} news items to {output_file}")

if __name__ == "__main__":
    main()
