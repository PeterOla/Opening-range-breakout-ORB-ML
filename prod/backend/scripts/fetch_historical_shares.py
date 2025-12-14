import sys
import logging
from pathlib import Path
import pandas as pd

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

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services.sec_shares import SecSharesClient

# Constants
PROJECT_ROOT = BACKEND_DIR.parent.parent
OUTPUT_FILE = PROJECT_ROOT / "data" / "raw" / "historical_shares.parquet"


def fetch_shares_for_symbols(symbols: list) -> pd.DataFrame:
    """
    Fetch shares outstanding for a list of symbols from SEC Company Facts (free).
    
    Args:
        symbols: List of ticker symbols to fetch
    
    Returns:
        DataFrame with columns: symbol, date, shares_outstanding
    """
    if not symbols:
        return pd.DataFrame(columns=["symbol", "date", "shares_outstanding"])

    client = SecSharesClient()
    # Logging/progress here is intentionally light: SEC has no strict 5/min cap,
    # but we still use polite sleeps inside the client.
    logger.info(f"Fetching SEC shares for {len(symbols)} symbols...")
    df = client.fetch_shares_for_symbols(symbols)
    if df.empty:
        logger.warning("No shares data returned from SEC")
        return pd.DataFrame(columns=["symbol", "date", "shares_outstanding"])

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    return df

def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger.error(
        "This script is designed to be called by the pipeline via fetch_shares_for_symbols(). "
        "If you want a full backfill, use scripts/DataPipeline/shares_sync.py (it persists to historical_shares.parquet)."
    )

if __name__ == "__main__":
    main()
