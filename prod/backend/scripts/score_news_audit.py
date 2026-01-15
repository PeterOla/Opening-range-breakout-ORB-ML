import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import logging
import torch

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Setup Paths
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from services.sentiment_scanner import fetch_universe_news, load_sentiment_model
from services.universe import load_universe_from_parquet

def main():
    # 1. Define Paths and Time
    ET = ZoneInfo("America/New_York")
    
    # Target Window: 2026-01-14 09:30:00 to 2026-01-15 09:30:00 ET
    start_dt = datetime(2026, 1, 14, 9, 30, 0, tzinfo=ET)
    end_dt = datetime(2026, 1, 15, 9, 30, 0, tzinfo=ET)
    
    universe_path = BASE_DIR.parent / "data" / "backtest" / "orb" / "universe" / "universe_micro_full.parquet"
    
    # 2. Load Universe
    logger.info(f"Loading universe from {universe_path}...")
    try:
        if not universe_path.exists():
            logger.error(f"Universe file not found: {universe_path}")
            return
        universe = load_universe_from_parquet(universe_path)
    except Exception as e:
        logger.error(f"Failed to load universe: {e}")
        return

    # 3. Fetch News
    logger.info(f"Fetching news from {start_dt} to {end_dt}...")
    news_map = fetch_universe_news(universe, start_dt=start_dt, end_dt=end_dt)
    
    if not news_map:
        logger.info("No news found in this window.")
        return

    # 4. Score News
    logger.info("Loading FinBERT model...")
    pipeline = load_sentiment_model()
    
    logger.info("\n📊 HIGH CONVICTION NEWS (> 0.90 POSITIVE)")
    logger.info("-" * 100)
    logger.info(f"{'Symbol':<8} | {'Score':<6} | {'Headline'}")
    logger.info("-" * 100)
    
    count = 0
    # Collect all unique headlines to batch score if possible, or just loop
    # Looping per symbol/headline for simple printing
    for sym, headlines in news_map.items():
        unique_headlines = list(set(headlines))
        
        try:
            results = pipeline(unique_headlines)
            # results: [{'label': 'positive', 'score': 0.99}, ...]
            
            for i, res in enumerate(results):
                if res['label'] == 'positive' and res['score'] >= 0.90:
                    headline = unique_headlines[i]
                    # Truncate headline if too long
                    display_headline = (headline[:85] + '...') if len(headline) > 85 else headline
                    logger.info(f"{sym:<8} | {res['score']:.4f} | {display_headline}")
                    count += 1
                    
        except Exception as e:
            logger.error(f"Error scoring {sym}: {e}")

    logger.info("-" * 100)
    logger.info(f"Found {count} high conviction headlines.")

if __name__ == "__main__":
    main()
