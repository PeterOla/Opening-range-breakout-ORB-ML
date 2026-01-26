"""
Sync daily bars for micro-cap universe with ATR and volume calculations.
Fetches from Alpaca, retries 3x on failure, stores 30 days rolling window.

Run nightly at 18:00 ET: python scripts/sync_daily_data.py
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, date
import pandas as pd
import time
from typing import Optional, List

# Add parent backend to path for Alpaca client
BACKEND_PATH = Path(__file__).parent.parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_PATH))

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
DAILY_DIR = DATA_DIR / "bars" / "daily"
REFERENCE_DIR = DATA_DIR / "reference"
LOG_DIR = Path(__file__).parent.parent / "logs" / "runs"

# Config
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
RETENTION_DAYS = 30

def log(message: str, level: str = "INFO"):
    """Terminal logger with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{level}] [SYNC_DAILY] {message}")
    sys.stdout.flush()

def get_micro_universe() -> List[str]:
    """Load micro-cap symbol list from reference file"""
    universe_path = REFERENCE_DIR / "universe_micro_full.parquet"
    df = pd.read_parquet(universe_path)
    symbols = df['symbol'].unique().tolist()
    log(f"Loaded {len(symbols)} micro-cap symbols from universe")
    return symbols

def fetch_daily_bars_with_retry(
    symbols: List[str],
    start_date: date,
    end_date: date,
    max_retries: int = 3
) -> Optional[pd.DataFrame]:
    """Fetch daily bars from Alpaca with exponential backoff retry"""
    
    client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
    
    for attempt in range(1, max_retries + 1):
        try:
            log(f"Fetching daily bars for {len(symbols)} symbols (attempt {attempt}/{max_retries})")
            
            request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Day,
                start=start_date,
                end=end_date
            )
            
            bars = client.get_stock_bars(request)
            df = bars.df.reset_index()
            
            log(f"Fetched {len(df)} bars for {df['symbol'].nunique()} symbols")
            return df
            
        except Exception as e:
            log(f"Fetch failed (attempt {attempt}/{max_retries}): {e}", level="ERROR")
            
            if attempt < max_retries:
                backoff = 5 * 60 * (2 ** (attempt - 1))  # 5min, 10min, 20min
                log(f"Retrying in {backoff}s...")
                time.sleep(backoff)
            else:
                log("All retries exhausted", level="ERROR")
                return None
    
    return None

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculate ATR-14 for each symbol"""
    
    result_dfs = []
    
    for symbol, group in df.groupby('symbol'):
        group = group.sort_values('timestamp')
        
        # True Range calculation
        group['h_l'] = group['high'] - group['low']
        group['h_pc'] = abs(group['high'] - group['close'].shift(1))
        group['l_pc'] = abs(group['low'] - group['close'].shift(1))
        group['tr'] = group[['h_l', 'h_pc', 'l_pc']].max(axis=1)
        
        # ATR = exponential moving average of TR
        group['atr_14'] = group['tr'].ewm(span=period, adjust=False).mean()
        
        # Drop intermediate columns
        group = group.drop(columns=['h_l', 'h_pc', 'l_pc', 'tr'])
        
        result_dfs.append(group)
    
    return pd.concat(result_dfs, ignore_index=True)

def calculate_avg_volume(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculate 14-day average volume for each symbol"""
    
    result_dfs = []
    
    for symbol, group in df.groupby('symbol'):
        group = group.sort_values('timestamp')
        group['avg_volume_14'] = group['volume'].rolling(window=period).mean()
        result_dfs.append(group)
    
    return pd.concat(result_dfs, ignore_index=True)

def cleanup_old_files(retention_days: int = 30):
    """Delete daily bar files older than retention period"""
    
    cutoff_date = datetime.now().date() - timedelta(days=retention_days)
    deleted_count = 0
    
    for file in DAILY_DIR.glob("*.parquet"):
        try:
            # Extract date from filename (YYYY-MM-DD.parquet)
            file_date = datetime.strptime(file.stem, "%Y-%m-%d").date()
            
            if file_date < cutoff_date:
                file.unlink()
                deleted_count += 1
                
        except (ValueError, OSError) as e:
            log(f"Skipping file {file.name}: {e}", level="WARNING")
    
    if deleted_count > 0:
        log(f"Deleted {deleted_count} files older than {cutoff_date}")

def main():
    """Main sync pipeline"""
    
    # Setup
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now().date()
    log(f"Starting daily data sync for {today}")
    
    # Load universe
    symbols = get_micro_universe()
    
    # Fetch bars for last 30 days (need history for ATR/volume calculations)
    start_date = today - timedelta(days=45)  # Extra buffer for calculations
    end_date = today
    
    df = fetch_daily_bars_with_retry(symbols, start_date, end_date)
    
    if df is None:
        log("Failed to fetch daily bars after all retries - ABORTING", level="ERROR")
        sys.exit(1)
    
    # Calculate metrics
    log("Calculating ATR-14...")
    df = calculate_atr(df)
    
    log("Calculating avg_volume_14...")
    df = calculate_avg_volume(df)
    
    # Save today's data
    today_df = df[df['timestamp'].dt.date == today].copy()
    
    if len(today_df) == 0:
        log(f"No data for {today} - market might be closed", level="WARNING")
    else:
        output_path = DAILY_DIR / f"{today}.parquet"
        today_df.to_parquet(output_path, index=False)
        log(f"Saved {len(today_df)} bars to {output_path.name}")
    
    # Cleanup old files
    cleanup_old_files(RETENTION_DAYS)
    
    log("Daily data sync completed successfully")

if __name__ == "__main__":
    main()
