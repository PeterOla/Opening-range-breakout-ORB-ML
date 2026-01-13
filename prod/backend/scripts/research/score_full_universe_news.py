"""
Score Full Universe News (Research)
===================================
Scores the 1-year news dataset using FinBERT and generates a Sentiment-Based Universe.

Input: data/research/news/news_micro_full_1y.parquet
Output: 
  1. data/research/news/news_micro_full_1y_scored.parquet (News with scores)
  2. data/backtest/orb/universe/universe_sentiment_only.parquet (Daily candidates > 0.6)
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from prod.backend.scripts.data.annotate_news_sentiment import SentimentAnnotator
except ImportError:
    print("Error: Could not import SentimentAnnotator.")
    sys.exit(1)

INPUT_FILE = PROJECT_ROOT / "data" / "research" / "news" / "news_micro_full_1y.parquet"
OUTPUT_SCORED_FILE = PROJECT_ROOT / "data" / "research" / "news" / "news_micro_full_1y_scored.parquet"
OUTPUT_UNIVERSE_FILE = PROJECT_ROOT / "data" / "backtest" / "orb" / "universe" / "universe_sentiment_only.parquet"

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
    df.to_parquet(OUTPUT_SCORED_FILE)
    print(f"✅ Saved scored news to {OUTPUT_SCORED_FILE}")

    # Build Universe (Group by Date and Symbol)
    print("Building Sentiment Universe...")
    
    # 1. Convert timestamp to Date (Trade Date assumption)
    # News before 16:00 ET belongs to 'Today', News after 16:00 ET belongs to 'Tomorrow'?
    # Or strict 24h rolling?
    # For backtest universe files, 'trade_date' is the date of the session.
    # Pre-market scan at 9:00 AM uses news from prev 24h.
    # So if news is at 2024-01-01 18:00, it applies to 2024-01-02 session.
    # If news is at 2024-01-02 08:00, it applies to 2024-01-02 session.
    
    # Simplification: Shift timestamps by +8 hours? 
    # If news is before 16:00 (market close), it might be stale for next day ORB?
    # But usually ORB uses "Overnight + Premarket".
    # Let's say Cutoff is 16:00 ET previous day.
    # Timestamp is UTC. 16:00 ET = 21:00 UTC (approx).
    # If we shift UTC time by -21 hours? No.
    # Let's just take Date = (Timestamp - 9h).date() + 1 day?
    # If TS is Jan 01 10:00 UTC (5am ET) -> Trade Date Jan 01.
    # If TS is Jan 01 22:00 UTC (5pm ET) -> Trade Date Jan 02.
    
    # Logic: If hour < 14 (9 AM ET approx), it's Today. If hour >= 14, it's Tomorrow.
    # 09:30 ET is ~14:30 UTC.
    # Any news before 14:00 UTC is "Today". News after 14:00 UTC is "Tomorrow"?
    # Actually, let's use the logic: Trade Date is the date of the news if before 9:30 ET?
    # No, usually we want "News that happened since LAST OPEN".
    
    # Let's genericize:
    # Trade Date = Timestamp.date() if time < 14:30 UTC else (Timestamp + 1day).date()
    
    # Ensure datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    
    # Vectorized trade date calculation
    # 14:30 UTC is roughly Market Open.
    # Anything after 09:30 ET (14:30 UTC) is too late for "Pre-market Filter" (it would be live news).
    # But wait, we want to build a universe for the day.
    # The scan runs at 9:00 AM.
    # So it sees everything before 9:00 AM.
    # If news is from yesterday 10:00 AM, is it relevant?
    # Live script uses lookback=24h. So Yes.
    
    # So, for Trade Date T:
    # We include news from [T-1 09:00] to [T 09:00].
    # Which effectively maps to Trade Date T.
    
    # So, shift timestamp by -14h (approx 9AM ET in UTC ish)?
    # If TS is T 08:00 AM -> T.
    # If TS is T-1 10:00 AM -> T.
    # Effective Mapping: Trade Date = (Timestamp + Shift).date()?
    # If we want T 09:00 to map to T, and T-1 09:01 to map to T.
    # If we subtract 9 hours?
    # T 09:00 -> T 00:00 -> Date T.
    # T-1 10:00 -> T-1 01:00 -> Date T-1. (Wrong)
    
    # We want T-1 10:00 to map to T.
    # So we want to push broad range forward.
    # If we add 15 hours?
    # T-1 10:00 + 15h = T 01:00 -> Date T. Correct.
    # T 08:59 + 15h = T 23:59 -> Date T. Correct.
    # T 09:01 + 15h = T+1 00:01 -> Date T+1. Correct (Too late for today's scan).
    
    # Apply +15h shift to UTC timestamp to determine Trade Date
    df['trade_date_ts'] = df['timestamp'] + timedelta(hours=15)
    df['trade_date'] = df['trade_date_ts'].dt.date
    
    # Filter by Score
    positive_news = df[df['positive_score'] > SENTIMENT_THRESHOLD]
    
    # Group by Trade Date and Symbol
    # We want symbols that have AT LEAST ONE piece of positive news in that window.
    # Or average?
    # Live script uses MEAN positive score.
    daily_stats = df.groupby(['trade_date', 'symbol'])['positive_score'].mean().reset_index()
    
    universe = daily_stats[daily_stats['positive_score'] > SENTIMENT_THRESHOLD].copy()
    
    print(f"Generated {len(universe)} candidate-days for universe.")
    
    # Format for Universe Parquet
    # [trade_date, symbol, sentiment_score]
    # Rename symbol -> ticker if standard
    universe = universe.rename(columns={'symbol': 'ticker', 'positive_score': 'sentiment_score'})
    universe['trade_date'] = pd.to_datetime(universe['trade_date']) # Standard format
    
    # Sort
    universe = universe.sort_values(['trade_date', 'ticker'])
    
    universe.to_parquet(OUTPUT_UNIVERSE_FILE)
    print(f"✅ Saved Sentiment Universe to {OUTPUT_UNIVERSE_FILE}")

if __name__ == "__main__":
    main()
