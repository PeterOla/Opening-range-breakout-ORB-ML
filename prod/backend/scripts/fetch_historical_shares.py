import os
import sys
import time
import requests
import pandas as pd
import logging
from pathlib import Path
from datetime import datetime
from sqlalchemy import text

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from db.database import engine
from core.config import Settings

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("shares_sync.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent.parent
OUTPUT_FILE = PROJECT_ROOT / "data" / "raw" / "historical_shares.parquet"
SLEEP_SECONDS = 12  # 5 calls per minute for free tier
BATCH_SIZE = 100

def get_tickers():
    """Fetch all active tickers from the database."""
    with engine.connect() as conn:
        query = text("SELECT symbol FROM tickers WHERE active = true ORDER BY symbol")
        result = conn.execute(query).fetchall()
        return [row[0] for row in result]

def fetch_balance_sheet(symbol, api_key):
    """Fetch quarterly balance sheet data from Alpha Vantage."""
    url = f"https://www.alphavantage.co/query?function=BALANCE_SHEET&symbol={symbol}&apikey={api_key}"
    try:
        response = requests.get(url)
        data = response.json()
        
        if "quarterlyReports" not in data:
            if "Note" in data:
                logger.warning(f"Rate limit hit for {symbol}: {data['Note']}")
            return None
            
        records = []
        for report in data["quarterlyReports"]:
            date = report.get("fiscalDateEnding")
            shares = report.get("commonStockSharesOutstanding")
            
            if date and shares and shares != "None":
                records.append({
                    "symbol": symbol,
                    "date": date,
                    "shares_outstanding": int(shares)
                })
        return records
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return None

def main():
    settings = Settings()
    api_key = settings.ALPHAVANTAGE_API_KEY
    
    if not api_key:
        logger.error("ALPHAVANTAGE_API_KEY not found in environment variables.")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    tickers = get_tickers()
    logger.info(f"Found {len(tickers)} tickers to process.")
    
    all_records = []
    
    # Check if partial file exists to resume
    if OUTPUT_FILE.exists():
        existing_df = pd.read_parquet(OUTPUT_FILE)
        processed_symbols = set(existing_df['symbol'].unique())
        all_records = existing_df.to_dict('records')
        tickers = [t for t in tickers if t not in processed_symbols]
        logger.info(f"Resuming... {len(processed_symbols)} already done, {len(tickers)} remaining.")

    for i, symbol in enumerate(tickers):
        logger.info(f"[{i+1}/{len(tickers)}] Fetching shares for {symbol}...")
        
        records = fetch_balance_sheet(symbol, api_key)
        
        if records:
            all_records.extend(records)
            logger.info(f"  -> Found {len(records)} quarterly records.")
        else:
            logger.warning(f"  -> No data found for {symbol}")

        # Save checkpoint every 10 tickers
        if (i + 1) % 10 == 0:
            df = pd.DataFrame(all_records)
            # Ensure date is datetime
            df['date'] = pd.to_datetime(df['date'])
            df.to_parquet(OUTPUT_FILE)
            logger.info(f"Checkpoint saved: {len(df)} total records.")

        time.sleep(SLEEP_SECONDS)

    # Final save
    if all_records:
        df = pd.DataFrame(all_records)
        df['date'] = pd.to_datetime(df['date'])
        df.sort_values(['symbol', 'date'], inplace=True)
        df.to_parquet(OUTPUT_FILE)
        logger.info(f"Completed! Saved {len(df)} records to {OUTPUT_FILE}")
    else:
        logger.warning("No records fetched.")

if __name__ == "__main__":
    main()
