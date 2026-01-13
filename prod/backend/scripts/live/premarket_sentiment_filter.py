"""
Pre-Market Sentiment Filter
===========================

Scans news for a list of symbols (or the active universe) and filters them based on Sentiment Analysis.
Intended to be run at 09:00 AM EST (Pre-Market).

Logic:
1. Fetch news (last 24h or since 4 AM) for given symbols.
2. Run FinBERT Sentiment Analysis.
3. Filter: Keep only if Mean Positive Score > 0.6.
4. Output: JSON allowlist for the day.

Usage:
    python prod/backend/scripts/live/premarket_sentiment_filter.py --symbols AAPL,TSLA,GME
    python prod/backend/scripts/live/premarket_sentiment_filter.py --universe micro
"""

import sys
import argparse
import pandas as pd
import json
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from typing import List, Dict, Optional
import os

# Add project root to path
# prod/backend/scripts/live/premarket_sentiment_filter.py -> ... -> root
project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))

try:
    from prod.backend.scripts.data.annotate_news_sentiment import SentimentAnnotator
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    from alpaca.common.exceptions import APIError
    from core.config import settings
except ImportError as e:
    print(f"Import Error: {e}")
    print("Ensure you are running from the project root or have set PYTHONPATH.")
    sys.exit(1)

# Configuration
SENTIMENT_THRESHOLD = 0.6
LOOKBACK_HOURS = 24  # Fetch news from last 24h

def fetch_live_news(symbols: List[str], api_key: str, api_secret: str) -> pd.DataFrame:
    """Fetch recent news for symbols using Alpaca API."""
    print(f"Fetching news for {len(symbols)} symbols...")
    
    client = NewsClient(api_key=api_key, secret_key=api_secret)
    
    # Alpaca limits symbols per request (usually 50 is safe)
    BATCH_SIZE = 50
    all_news = []
    
    # Start fetch from: PREVIOUS day close? Or midnight?
    # Usually "Today's news" implies since midnight or pre-market.
    # But backtests might have included news from prev evening.
    # Let's use last 24h to capture overnight news.
    start_time = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i+BATCH_SIZE]
        try:
            request_params = NewsRequest(
                symbols=batch,
                start=start_time,
                limit=50,  # Max headlines per symbol-batch combo
                include_content=False # We only need headline/summary
            )
            news = client.get_news(request_params)
            
            for n in news.news:
                all_news.append({
                    'timestamp': n.created_at,
                    'symbol': n.symbols[0] if n.symbols else 'UNKNOWN', # Primary symbol usually first
                    'headline': n.headline,
                    'summary': n.summary,
                    'url': n.url
                })
                
        except Exception as e:
            # print(f"Error fetching batch {i}: {e}") # Reduce noise
            pass
            
    if not all_news:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_news)
    print(f"Fetched {len(df)} headlines.")
    return df

def score_news(news_df: pd.DataFrame) -> pd.DataFrame:
    """Score news using FinBERT."""
    if news_df.empty:
        return news_df
        
    print("Initializing FinBERT model...")
    # Auto-detect device (uses CUDA if available)
    annotator = SentimentAnnotator()
    
    # Only unique headlines to save time
    unique_headlines = news_df['headline'].unique().tolist()
    print(f"Scoring {len(unique_headlines)} unique headlines...")
    
    # Run batch prediction
    # SentimentAnnotator.predict_batch returns list of dicts:
    # [{'positive': 0.9, 'negative': 0.05, 'neutral': 0.05, 'label': 'positive'}, ...]
    results = annotator.predict_batch(unique_headlines, batch_size=32)
    
    # Create DataFrame from results
    scores_data = []
    for h, res in zip(unique_headlines, results):
        scores_data.append({
            'headline': h,
            'positive_score': res.get('positive', 0),
            'negative_score': res.get('negative', 0),
            'neutral_score': res.get('neutral', 0),
            'sentiment_label': res.get('label', 'neutral')
        })
        
    scores_df = pd.DataFrame(scores_data)
    
    # Merge back to original news
    merged = news_df.merge(scores_df, on='headline', how='left')
    return merged

def calculate_allowlist(scored_df: pd.DataFrame) -> Dict:
    """Aggregate scores and determine allowlist."""
    if scored_df.empty:
        return {"allowed": [], "rejected": [], "details": {}}
    
    print("Aggregating scores per symbol...")
    # Group by Symbol
    # Logic: Mean Positive Score > Threshold
    stats = scored_df.groupby('symbol').agg({
        'positive_score': 'mean',
        'headline': 'count'
    }).reset_index()
    
    stats.rename(columns={'headline': 'news_count'}, inplace=True)
    
    # Apply Threshold
    allowed_stats = stats[stats['positive_score'] > SENTIMENT_THRESHOLD]
    rejected_stats = stats[stats['positive_score'] <= SENTIMENT_THRESHOLD]
    
    allowed = allowed_stats['symbol'].tolist()
    rejected = rejected_stats['symbol'].tolist()
    
    # Prepare details dict
    details = stats.set_index('symbol').to_dict(orient='index')
    
    print(f"Allowed: {len(allowed)} | Rejected: {len(rejected)}")
    return {
        "allowed": allowed,
        "rejected": rejected,
        "details": details,
        "timestamp": datetime.now().isoformat()
    }

def main():
    parser = argparse.ArgumentParser(description="Live Pre-Market Sentiment Filter")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols (e.g. AAPL,MSFT)")
    parser.add_argument("--universe", type=str, default="micro", help="Universe name (if no symbols provided)")
    parser.add_argument("--output", type=str, help="Custom output path for JSON")
    args = parser.parse_args()
    
    # 1. Determine Symbols
    symbols = []
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        # Load active universe from parquet
        # We assume the standard backtest universes are the source of truth
        uni_map = {
            "micro": "universe_micro.parquet",
            "micro_small": "universe_micro_small.parquet",
            "micro_unknown": "universe_micro_unknown.parquet"
        }
        fname = uni_map.get(args.universe, "universe_micro.parquet")
        fpath = project_root / "data" / "backtest" / "orb" / "universe" / fname
        
        # Check specific 'news_based' subfolder first as that was the baseline
        # (Though live we might want the FULL universe to find new news?)
        # Let's use the 'scan_universe.parquet' if exists or just standard universe.
        
        # Actually, for LIVE, we might have a 'daily_candidates.csv' or similar if cached
        # But defaulting to the big list is safer if filtering later.
        
        if not fpath.exists():
            # Try `news_based` subfolder
            fpath_news = fpath.parent / "news_based" / fname
            if fpath_news.exists():
                fpath = fpath_news
                
        if fpath.exists():
            print(f"Loading universe from {fpath.name}")
            df = pd.read_parquet(fpath)
            # Support 'ticker' or 'symbol' columns
            col = 'ticker' if 'ticker' in df.columns else 'symbol'
            if col in df.columns:
                symbols = df[col].unique().tolist()
            else:
                print(f"Error: No ticker/symbol column in {fpath}")
                return
        else:
            print(f"Universe file not found: {fpath}")
            return

    if not symbols:
        print("No symbols to scan.")
        return
        
    print(f"Scanning {len(symbols)} symbols...")
    
    # 2. Fetch News
    api_key = settings.ALPACA_API_KEY
    api_secret = settings.ALPACA_API_SECRET
    
    if not api_key:
        print("Error: ALPACA_API_KEY not set in environment or .env file.")
        print("Please configure your .env file with Alpaca credentials.")
        return

    news_df = fetch_live_news(symbols, api_key, api_secret)
    
    # 3. Score & Filtering
    allowlist_data = {}
    
    if news_df.empty:
        print("No news found in the last 24h.")
        # If no news, logic dictates NO trades if using "News Based" strategy.
        allowlist_data = {
            "allowed": [],
            "rejected": [],
            "details": {},
            "timestamp": datetime.now().isoformat(),
            "note": "No news found"
        }
    else:
        print(f"Found {len(news_df)} headlines. Scoring...")
        scored_df = score_news(news_df)
        allowlist_data = calculate_allowlist(scored_df)
        
    # 4. Output
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = project_root / "data" / "sentiment" / f"allowlist_{today_str}.json"
        
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, 'w') as f:
        json.dump(allowlist_data, f, indent=2)
        
    print(f"\n✅ Allowlist saved to: {out_path}")
    print(f"   Allowed Symbols: {len(allowlist_data['allowed'])}")
    if len(allowlist_data['allowed']) < 20:
        print(f"   {allowlist_data['allowed']}")

if __name__ == "__main__":
    main()
