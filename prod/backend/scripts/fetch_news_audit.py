import sys
import pandas as pd
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup Paths
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from services.sentiment_scanner import fetch_universe_news
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
        logger.info(f"Loaded {len(universe)} symbols.")
        
    except Exception as e:
        logger.error(f"Failed to load universe: {e}")
        return

    # 3. Fetch News
    logger.info(f"Fetching news from {start_dt} to {end_dt}...")
    news_map = fetch_universe_news(universe, start_dt=start_dt, end_dt=end_dt)
    
    # 4. Analyze Results
    total_headlines = sum(len(h) for h in news_map.values())
    symbols_with_news = len(news_map)
    
    logger.info("="*50)
    logger.info(f"RESULTS FOR WINDOW: {start_dt} - {end_dt}")
    logger.info(f"Total Headlines: {total_headlines}")
    logger.info(f"Symbols with News: {symbols_with_news}")
    logger.info("="*50)
    
    if symbols_with_news > 0:
        logger.info("Sample Headlines:")
        count = 0
        for sym, headlines in news_map.items():
            logger.info(f"  {sym}: {len(headlines)} headlines")
            for h in headlines[:2]:
                logger.info(f"    - {h}")
            count += 1
            if count >= 5: 
                break
                
        # Optional: Check if DUOL was in the universe and if it had news
        if "DUOL" in universe:
            duol_news = news_map.get("DUOL", [])
            logger.info("-" * 30)
            logger.info(f"DUOL Check: In Universe? YES. News Count: {len(duol_news)}")
            if duol_news:
                for h in duol_news:
                    logger.info(f"    - {h}")
        else:
            logger.info("-" * 30)
            logger.info("DUOL Check: NOT in micro-cap universe (Expected).")

if __name__ == "__main__":
    main()
