"""
Test Sentiment Scanner Live integration.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# Setup logging
logging.basicConfig(level=logging.INFO)

from services.scanner import scan_universe
from services.sentiment_scanner import get_micro_cap_universe
from db.database import SessionLocal
from db.models import Ticker

# Mock settings if needed (Alpaca keys should be in .env)
from core.config import settings

async def main():
    print("=== Dry Run: Sentiment Scanner Integration ===")
    
    # 1. Check DB Stats
    try:
        db = SessionLocal()
        count = db.query(Ticker).filter(Ticker.float < 50_000_000).count()
        print(f"DB Micro-cap Count: {count}")
        db.close()
        
        if count == 0:
            print("WARNING: DB is empty. Real scan would fail.")
    except Exception as e:
        print(f"WARNING: DB Connection failed ({e}). Proceeding to test fallback mechanism inside scanner.")
    
    # 2. Run Scan
    # We set strict thresholds to avoid huge output, but loose enough to catch something if markets were open
    # Since market is closed now, 'snapshots' will return last close.
    # News will filter last 24h.
    
    print("\n--- Running scan_universe(use_sentiment=True) ---")
    results = await scan_universe(
        min_price=1.0, 
        max_price=50.0,
        min_avg_volume=100_000, 
        min_atr=0.1, # Relaxed for test
        top_n=5,
        sentiment_threshold=0.90
    )
    
    print(f"\nScan Results: {len(results)}")
    for r in results:
        print(r)

if __name__ == "__main__":
    # Check if keys are present
    if not settings.ALPACA_API_KEY:
        print("Error: ALPACA_API_KEY not found in .env")
        sys.exit(1)
        
    asyncio.run(main())
