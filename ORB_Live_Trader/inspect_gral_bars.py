
import pandas as pd
from pathlib import Path
from datetime import datetime, time as dt_time
import os
import sys

# Setup
ORB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ORB_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(ORB_ROOT))

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from dotenv import load_dotenv

load_dotenv(ORB_ROOT / "config" / ".env")

def inspect_gral():
    print("==========================================")
    print("INSPECTING GRAL DATA: FRESH vs CACHED")
    print("==========================================")
    target_date = "2025-01-23"
    
    # 1. Load Cached Data (Used by Live Sim)
    # The live sim merges bars into data/bars/5min/GRAL.parquet
    cached_path = ORB_ROOT / "data" / "bars" / "5min" / "GRAL.parquet"
    if cached_path.exists():
        df_cached = pd.read_parquet(cached_path)
        # Filter for date
        if 'datetime' in df_cached.columns:
            df_cached['dt'] = pd.to_datetime(df_cached['datetime'])
        elif 'timestamp' in df_cached.columns:
            df_cached['dt'] = pd.to_datetime(df_cached['timestamp'])
        
        # Convert to ET
        # Assuming cached is stored as UTC or naive? Let's check.
        # usually pipeline persists UTC
        try:
            df_cached['dt_et'] = df_cached['dt'].dt.tz_convert('America/New_York')
        except:
             # If naive, assume it might be ET or UTC? pipeline uses UTC.
             df_cached['dt_et'] = df_cached['dt'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')

        day_mask = df_cached['dt_et'].dt.date.astype(str) == target_date
        df_day = df_cached[day_mask].copy()
        
        print(f"\n[CACHED] {cached_path.name}")
        print(df_day[['dt_et', 'open', 'high', 'low', 'close', 'volume']].head(10))
    else:
        print(f"\n[CACHED] File not found: {cached_path}")

    # 2. Fetch Fresh Data (Used by Backtest Verification)
    print("\n[FRESH] Fetching from Alpaca...")
    client = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"))
    req = StockBarsRequest(
        symbol_or_symbols="GRAL",
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=datetime.strptime(f"{target_date} 09:00:00", "%Y-%m-%d %H:%M:%S"),
        end=datetime.strptime(f"{target_date} 16:00:00", "%Y-%m-%d %H:%M:%S"),
        adjustment='raw'
    )
    bars = client.get_stock_bars(req).df
    if not bars.empty:
        bars = bars.reset_index()
        bars['dt_et'] = bars['timestamp'].dt.tz_convert('America/New_York')
        print(bars[['dt_et', 'open', 'high', 'low', 'close', 'volume']])
    else:
        print("No fresh data found.")

if __name__ == "__main__":
    inspect_gral()
