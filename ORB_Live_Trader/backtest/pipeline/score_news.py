"""
Score Full Universe News (Backtest Pipeline)
============================================
Scores the news dataset using FinBERT and generates a Sentiment-Based Universe.

Input: ORB_Live_Trader/backtest/data/news/news_micro_full_1y.parquet
Output: 
  1. ORB_Live_Trader/backtest/data/news/news_micro_full_1y_scored.parquet
  2. ORB_Live_Trader/backtest/data/universe/universe_sentiment_only.parquet
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Ensure we can import utils
PIPELINE_DIR = Path(__file__).parent
sys.path.insert(0, str(PIPELINE_DIR))

try:
    from utils.annotate_news_sentiment import SentimentAnnotator
except ImportError as e:
    print(f"Error: Could not import SentimentAnnotator. {e}")
    sys.path.append(str(PIPELINE_DIR / "utils"))
    from annotate_news_sentiment import SentimentAnnotator

# Paths
BACKTEST_DIR = PIPELINE_DIR.parent
DATA_DIR = BACKTEST_DIR / "data"
INPUT_FILE = DATA_DIR / "news" / "news_micro_full_1y.parquet"
OUTPUT_SCORED_FILE = DATA_DIR / "news" / "news_micro_full_1y_scored.parquet"
OUTPUT_UNIVERSE_FILE = DATA_DIR / "universe" / "universe_sentiment_only.parquet"

SENTIMENT_THRESHOLD = 0.6

def main():
    if not INPUT_FILE.exists():
        print(f"Error: Input file missing: {INPUT_FILE}")
        return

    print(f"Loading {INPUT_FILE}...")
    df = pd.read_parquet(INPUT_FILE)
    print(f"Loaded {len(df)} news items.")

    if df.empty:
        print("No data.")
        return

    # Deduplicate headlines for scoring
    unique_headlines = df['headline'].unique().tolist()
    print(f"Unique headlines to score: {len(unique_headlines)}")

    # Initialize Model
    annotator = SentimentAnnotator()
    results = annotator.predict_batch(unique_headlines)
    
    # Map results back
    score_map = {
        h: res['positive_score'] for h, res in zip(unique_headlines, results)
    }
    
    df['positive_score'] = df['headline'].map(score_map)
    
    OUTPUT_SCORED_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_SCORED_FILE)
    print(f"✅ Saved scored news to {OUTPUT_SCORED_FILE}")

    # Build Universe
    print("Building Sentiment Universe...")
    
    # Ensure datetime
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    
    # Simple +15h shift Logic for Trade Date (same as original script)
    # T-1 09:00 ET (14:00 UTC) -> T
    # T 08:59 ET -> T
    df['trade_date_ts'] = df['timestamp'] + timedelta(hours=15)
    df['trade_date'] = df['trade_date_ts'].dt.date
    
    # Filter by Score
    positive_news = df[df['positive_score'] > SENTIMENT_THRESHOLD]
    
    # Group by Trade Date and Symbol
    daily_stats = df.groupby(['trade_date', 'symbol'])['positive_score'].mean().reset_index()
    
    universe = daily_stats[daily_stats['positive_score'] > SENTIMENT_THRESHOLD].copy()
    
    print(f"Generated {len(universe)} candidate-days for universe.")
    
    # Format for Universe Parquet
    universe = universe.rename(columns={'symbol': 'ticker', 'positive_score': 'sentiment_score'})
    universe['trade_date'] = pd.to_datetime(universe['trade_date'])
    
    universe = universe.sort_values(['trade_date', 'ticker'])
    
    OUTPUT_UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    universe.to_parquet(OUTPUT_UNIVERSE_FILE)
    print(f"✅ Saved Sentiment Universe to {OUTPUT_UNIVERSE_FILE}")

if __name__ == "__main__":
    main()
