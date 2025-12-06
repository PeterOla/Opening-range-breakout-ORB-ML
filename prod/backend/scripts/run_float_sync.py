import sys
import os
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from db.database import SessionLocal
from services.ticker_float_sync import sync_float_for_tickers
from db.models import Ticker

def main():
    db = SessionLocal()
    try:
        logging.info("Checking for tickers needing float sync...")
        # Get all tickers
        all_tickers = db.query(Ticker).all()
        logging.info(f"Total tickers in DB: {len(all_tickers)}")
        
        # Count missing float
        missing = [t.symbol for t in all_tickers if t.float is None]
        logging.info(f"Tickers missing float: {len(missing)}")
        
        if missing:
            logging.info(f"Starting sync for {len(missing)} tickers...")
            sync_float_for_tickers(db, symbols=missing)
        else:
            logging.info("All tickers have float data.")
            
    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
