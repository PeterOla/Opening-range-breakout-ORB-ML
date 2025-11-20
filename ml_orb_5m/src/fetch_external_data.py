"""
Fetch external market data for ML features.

Downloads SPY, QQQ, VIX daily data from Polygon.io for market context.
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from polygon import RESTClient
from dotenv import load_dotenv

# Load API key
load_dotenv(Path(__file__).parent.parent.parent / ".env")
API_KEY = os.getenv("POLYGON_API_KEY")

if not API_KEY:
    raise ValueError("POLYGON_API_KEY not found in .env file")

client = RESTClient(API_KEY)

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "external"
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

# Symbols to fetch
SYMBOLS = ["SPY", "QQQ", "VIX"]
START_DATE = "2021-01-01"
END_DATE = "2025-12-31"

def fetch_daily_bars(symbol, start_date, end_date):
    """Fetch daily bars for a symbol."""
    print(f"Fetching {symbol} from {start_date} to {end_date}...")
    
    bars = []
    for bar in client.list_aggs(
        ticker=symbol,
        multiplier=1,
        timespan="day",
        from_=start_date,
        to=end_date,
        limit=50000
    ):
        bars.append({
            "symbol": symbol,
            "date": datetime.fromtimestamp(bar.timestamp / 1000).date(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        })
    
    df = pd.DataFrame(bars)
    print(f"  Retrieved {len(df)} bars")
    return df

def main():
    print("=" * 80)
    print("FETCHING EXTERNAL MARKET DATA")
    print("=" * 80)
    print()
    
    all_data = {}
    
    for symbol in SYMBOLS:
        df = fetch_daily_bars(symbol, START_DATE, END_DATE)
        
        if not df.empty:
            # Save to parquet
            output_path = OUTPUT_DIR / f"{symbol.lower()}_daily.parquet"
            df.to_parquet(output_path, index=False)
            print(f"  Saved to {output_path}")
            
            all_data[symbol] = df
        
        print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for symbol, df in all_data.items():
        print(f"{symbol}: {len(df)} days ({df['date'].min()} to {df['date'].max()})")
    
    print()
    print("External data fetch complete!")

if __name__ == "__main__":
    main()
