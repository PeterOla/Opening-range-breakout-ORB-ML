import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from core.config import settings

def main():
    print(f"Initializing Alpaca Client...")
    client = StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_API_SECRET
    )

    high_sentiment_symbols = [
        "PEN", "SQNS", "RILY", "QMCO", "AIR", "LITM", "MATX", "BCTX", "HUBC", 
        "IVP", "CJMB", "TDY", "AMN", "WLDN", "CASY", "FDS", "BLD", "LSTR", 
        "ONTO", "MPWR", "ENLV", "HOTH", "VWAV", "ICHR", "IBP", "SITM"
    ]

    # Time window: Last 35 days to ensure we have enough for 20-day Average
    # End date: Now (to capture today's data if available/open)
    end_dt = datetime.now(ZoneInfo("America/New_York"))
    start_dt = end_dt - timedelta(days=40)

    print(f"Fetching daily bars from {start_dt.date()} to {end_dt.date()}...")
    
    req = StockBarsRequest(
        symbol_or_symbols=high_sentiment_symbols,
        timeframe=TimeFrame.Day,
        start=start_dt,
        end=end_dt,
        adjustment='all'
    )

    try:
        bars = client.get_stock_bars(req)
        df_all = bars.df
    except Exception as e:
        print(f"Error fetching data: {e}")
        return

    if df_all.empty:
        print("No data returned.")
        return

    # Process per symbol
    results = []
    
    # Reset index to make symbol a column if multi-index
    df_all = df_all.reset_index()
    
    unique_symbols = df_all['symbol'].unique()

    for sym in unique_symbols:
        df_sym = df_all[df_all['symbol'] == sym].sort_values('timestamp').copy()
        
        if len(df_sym) < 20:
            print(f"Skipping {sym}: insufficient history ({len(df_sym)} days)")
            continue
            
        # Calculate 20-day Avg Volume (shifted)
        # We want the Avg Vol of the *prior* 20 days to compare against current
        df_sym['avg_vol_20'] = df_sym['volume'].shift(1).rolling(window=20).mean()
        
        # Get the latest available bar
        latest = df_sym.iloc[-1]
        
        # Check date of latest bar
        latest_date = latest['timestamp'].date()
        
        # RVOL
        avg_vol = latest['avg_vol_20']
        if pd.isna(avg_vol) or avg_vol == 0:
            rvol = 0
        else:
            rvol = latest['volume'] / avg_vol
            
        results.append({
            'Symbol': sym,
            'Date': latest_date,
            'Close': latest['close'],
            'Volume': int(latest['volume']),
            'AvgVol(20)': int(avg_vol) if pd.notna(avg_vol) else 0,
            'RVOL': rvol
        })

    # Sort
    results.sort(key=lambda x: x['RVOL'], reverse=True)

    print(f"\n{'Symbol':<6} | {'Date':<10} | {'Close':<8} | {'Volume':<12} | {'AvgVol(20)':<10} | {'RVOL'}")
    print("-" * 75)
    for r in results:
        print(f"{r['Symbol']:<6} | {r['Date']} | {r['Close']:<8.2f} | {r['Volume']:<12} | {r['AvgVol(20)']:<10} | {r['RVOL']:.2f}")

if __name__ == "__main__":
    main()
