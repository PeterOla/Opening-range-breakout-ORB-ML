import pandas as pd
import logging
from pathlib import Path
from tqdm import tqdm

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
SHARES_FILE = Path("data/raw/historical_shares.parquet")
DAILY_DIR = Path("data/processed/daily")

def main():
    if not SHARES_FILE.exists():
        logger.error(f"Shares file not found: {SHARES_FILE}")
        return

    logger.info("Loading historical shares data...")
    shares_df = pd.read_parquet(SHARES_FILE)
    shares_df['date'] = pd.to_datetime(shares_df['date'])
    shares_df = shares_df.sort_values('date')
    
    # Get all daily files
    daily_files = sorted(list(DAILY_DIR.glob("*.parquet")))
    logger.info(f"Found {len(daily_files)} daily files to enrich.")

    for file_path in tqdm(daily_files, desc="Enriching Daily Data"):
        try:
            # Parse date from filename (YYYY-MM-DD.parquet)
            date_str = file_path.stem
            current_date = pd.to_datetime(date_str)
            
            # Load daily data
            daily_df = pd.read_parquet(file_path)
            
            # 1. Filter shares reports that happened ON or BEFORE this trading day
            valid_reports = shares_df[shares_df['date'] <= current_date]
            
            # 2. Get the most recent report for each symbol
            # Sort by date and keep the last one for each symbol
            latest_shares = valid_reports.sort_values('date').drop_duplicates('symbol', keep='last')
            
            # 3. Merge into daily data
            # We use a left join to keep all daily rows, even if shares data is missing
            enriched_df = pd.merge(
                daily_df, 
                latest_shares[['symbol', 'shares_outstanding']], 
                on='symbol', 
                how='left'
            )
            
            # 4. Fill missing values (optional: fill with 0 or keep NaN)
            # enriched_df['shares_outstanding'] = enriched_df['shares_outstanding'].fillna(0).astype(int)
            
            # 5. Overwrite the file
            enriched_df.to_parquet(file_path)
            
        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {e}")

    logger.info("Enrichment complete!")

if __name__ == "__main__":
    main()
