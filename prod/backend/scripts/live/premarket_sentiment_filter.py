"""
Pre-Market Sentiment Filter
===========================

Scans universe for Technical Candidates (Pre-Market Gap) -> Then runs Sentiment Analysis.
Intended to be run at 09:00 AM EST (Pre-Market).

Logic:
1. Load Micro Universe (2,744 symbols).
2. Fetch Market Snapshots (Price/Gap).
3. Rank by Pre-Market Gap % (Desc).
4. Select Top 100 Gappers.
5. Fetch News (last 24h) for ONLY the Top 100.
6. Run FinBERT.
7. Output: JSON allowlist (Sentiment > 0.6).

Usage:
    python prod/backend/scripts/live/premarket_sentiment_filter.py --universe micro
"""

import sys

# Force UTF-8 for Windows consoles to support emojis 🚀
if sys.platform == "win32":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

import argparse
import pandas as pd
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional
import os

# Add project root to path
project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))

try:
    from prod.backend.scripts.data.annotate_news_sentiment import SentimentAnnotator
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest, StockSnapshotRequest
    from alpaca.data.historical import StockHistoricalDataClient
    from core.config import settings
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

# Configuration
SENTIMENT_THRESHOLD = 0.6
LOOKBACK_HOURS = 24  # Fetch news from last 24h
TECHNICAL_TOP_N = 100 # How many gap candidates to check for news

def fetch_snapshots_and_rank(symbols: List[str], api_key: str, api_secret: str) -> List[str]:
    """Fetch snapshots and rank by Pre-Market Gap."""
    print(f"Fetching snapshots for {len(symbols)} symbols...")
    
    data_client = StockHistoricalDataClient(api_key, api_secret)
    
    # Alpaca limits might apply, do in batches
    BATCH_SIZE = 1000
    snapshots = {}
    
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i+BATCH_SIZE]
        try:
            # get_stock_snapshot returns { symbol: Snapshot, ... }
            batch_snaps = data_client.get_stock_snapshot(batch)
            snapshots.update(batch_snaps)
            print(f"  Fetched {i} to {min(i+BATCH_SIZE, len(symbols))}")
        except Exception as e:
            print(f"  Error fetching snapshot batch: {e}")

    candidates = []
    
    for sym, snap in snapshots.items():
        if not snap: 
            continue
            
        # Snapshot object structure: 
        # snap.daily_bar (Bar), snap.prev_daily_bar (Bar), snap.latest_trade (Trade)
        
        # Determine Pre-market Gap
        # Gap = (Current - PrevClose) / PrevClose
        
        prev_close = 0.0
        current_price = 0.0
        
        # Get Prev Close
        if snap.prev_daily_bar:
            prev_close = snap.prev_daily_bar.close
        
        # Get Current Price (Pre-market)
        # 1. Latest Trade is best
        if snap.latest_trade:
            current_price = snap.latest_trade.price
        # 2. Daily Bar Open (if bar exists for today)
        elif snap.daily_bar:
            current_price = snap.daily_bar.open
            
        if prev_close > 0 and current_price > 0:
            gap_pct = (current_price - prev_close) / prev_close
            
            # We want Positive Gaps for Long strategy
            if gap_pct > 0:
                candidates.append((sym, gap_pct))
                
    # Sort
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    # Top N
    top_n = candidates[:TECHNICAL_TOP_N]
    
    if len(top_n) > 0:
        print(f"Top Gap: {top_n[0][0]} (+{top_n[0][1]*100:.2f}%)")
        print(f"100th Gap: {top_n[-1][0]} (+{top_n[-1][1]*100:.2f}%)")
    
    return [x[0] for x in top_n]

def fetch_live_news(symbols: List[str], api_key: str, api_secret: str) -> pd.DataFrame:
    """Fetch recent news for symbols using Alpaca API."""
    print(f"Fetching news for {len(symbols)} candidates...")
    
    client = NewsClient(api_key=api_key, secret_key=api_secret)
    BATCH_SIZE = 50
    all_news = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i+BATCH_SIZE]
        try:
            request_params = NewsRequest(
                symbols=batch,
                start=start_time,
                limit=10, 
                include_content=False 
            )
            news = client.get_news(request_params)
            for n in news.news:
                all_news.append({
                    'timestamp': n.created_at,
                    'symbol': n.symbols[0] if n.symbols else 'UNKNOWN',
                    'headline': n.headline
                })
        except Exception:
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
    annotator = SentimentAnnotator()
    unique_headlines = news_df['headline'].unique().tolist()
    print(f"Scoring {len(unique_headlines)} unique headlines...")
    
    results = annotator.predict_batch(unique_headlines, batch_size=32)
    
    scores_data = []
    for h, res in zip(unique_headlines, results):
        scores_data.append({
            'headline': h,
            'positive_score': res.get('positive', 0)
        })
        
    scores_df = pd.DataFrame(scores_data)
    return news_df.merge(scores_df, on='headline', how='left')

def calculate_allowlist(scored_df: pd.DataFrame) -> Dict:
    """Aggregate scores."""
    stats = scored_df.groupby('symbol').agg({
        'positive_score': 'mean',
        'headline': 'count'
    }).reset_index()
    
    allowed = stats[stats['positive_score'] > SENTIMENT_THRESHOLD]['symbol'].tolist()
    rejected = stats[stats['positive_score'] <= SENTIMENT_THRESHOLD]['symbol'].tolist()
    details = stats.set_index('symbol').to_dict(orient='index')
    
    return {
        "allowed": allowed,
        "rejected": rejected,
        "details": details,
        "timestamp": datetime.now().isoformat()
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", type=str, default="micro")
    parser.add_argument("--output", type=str)
    args = parser.parse_args()
    
    # 1. Load Universe
    uni_map = { "micro": "universe_micro_full.parquet" }
    fname = uni_map.get(args.universe, "universe_micro_full.parquet")
    fpath = project_root / "data" / "backtest" / "orb" / "universe" / fname
    
    if not fpath.exists():
        print(f"Universe file missing: {fpath}")
        return
        
    print(f"Loading universe: {fname}")
    df = pd.read_parquet(fpath)
    col = 'ticker' if 'ticker' in df.columns else 'symbol'
    all_symbols = df[col].unique().tolist()
    print(f"Universe Size: {len(all_symbols)}")
    
    if not all_symbols:
        return

    api_key = settings.ALPACA_API_KEY
    api_secret = settings.ALPACA_API_SECRET

    # 2. Technical Rank (Gap)
    # This aligns with Backtest: We only look at top technical candidates
    top_candidates = fetch_snapshots_and_rank(all_symbols, api_key, api_secret)
    
    if not top_candidates:
        print("No gap candidates found.")
        return

    # 3. News & Sentiment
    news_df = fetch_live_news(top_candidates, api_key, api_secret)
    
    allowlist_data = {}
    if news_df.empty:
        print("No news found for top candidates.")
        allowlist_data = {"allowed": [], "rejected": [], "details": {}, "timestamp": datetime.now().isoformat()}
    else:
        scored_df = score_news(news_df)
        allowlist_data = calculate_allowlist(scored_df)
        
    # 4. Save
    today_str = datetime.now().strftime("%Y-%m-%d")
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = project_root / "data" / "sentiment" / f"allowlist_{today_str}.json"
        
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(allowlist_data, f, indent=2)
        
    print(f"\n✅ Saved to {out_path}")
    print(f"   Allowed: {len(allowlist_data['allowed'])}")
    if allowlist_data['allowed']:
        print(f"   {allowlist_data['allowed']}")

if __name__ == "__main__":
    main()
