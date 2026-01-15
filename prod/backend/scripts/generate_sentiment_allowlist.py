import asyncio
import sys
import json
from pathlib import Path
from datetime import date, datetime
import logging

# Set up logging to stdout
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# Add path to backend root
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from services.sentiment_scanner import scan_sentiment_candidates

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "sentiment"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

async def main():
    logger.info("🚀 Starting Daily Sentiment Generation...")
    
    try:
        # Run scan (Defaults to threshold 0.90)
        candidates = await scan_sentiment_candidates(threshold=0.90)
        
        # Save to file
        today = date.today()
        filename = f"allowlist_{today}.json"
        filepath = OUTPUT_DIR / filename
        
        output = {
            "date": str(today),
            "allowed": candidates,
            "threshold": 0.90,
            "generated_at": datetime.now().isoformat()
        }
        
        with open(filepath, "w") as f:
            json.dump(output, f, indent=2)
            
        logger.info(f"✅ Saved {len(candidates)} sentiment candidates to {filepath}")
        
    except Exception as e:
        logger.error(f"❌ Error generating sentiment allowlist: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
