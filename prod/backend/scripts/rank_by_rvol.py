import pandas as pd
from pathlib import Path
import sys

# Paths
base_dir = Path(r"c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)")
processed_dir = base_dir / "data" / "processed" / "daily"

# Symbols with sentiment > 0.90
high_sentiment_symbols = [
    "PEN", "SQNS", "RILY", "QMCO", "AIR", "LITM", "MATX", "BCTX", "HUBC", 
    "IVP", "CJMB", "TDY", "AMN", "WLDN", "CASY", "FDS", "BLD", "LSTR", 
    "ONTO", "MPWR", "ENLV", "HOTH", "VWAV", "ICHR", "IBP", "SITM"
]

results = []

print(f"{'Symbol':<6} | {'Date':<10} | {'Close':<8} | {'Volume':<10} | {'AvgVol(20)':<10} | {'RVOL'}")
print("-" * 75)

for symbol in high_sentiment_symbols:
    file_path = processed_dir / f"{symbol}.parquet"
    
    if not file_path.exists():
        continue
        
    try:
        df = pd.read_parquet(file_path)
        if df.empty:
            continue
            
        # Ensure sorted
        df = df.sort_values('date')
        
        # Get last row (Current/Most Recent Day)
        current = df.iloc[-1]
        
        # Calculate Rolling average volume (20 days) shifting strictly to use prior data
        # We want Avg Volume of the *previous* 20 days relative to the current day
        # So shift(1) then rolling(20)
        df['avg_vol_20'] = df['volume'].shift(1).rolling(window=20).mean()
        
        avg_vol = df['avg_vol_20'].iloc[-1]
        
        if pd.isna(avg_vol) or avg_vol == 0:
            rvol = 0.0
        else:
            rvol = current['volume'] / avg_vol
            
        results.append({
            'Symbol': symbol,
            'Date': current['date'].strftime('%Y-%m-%d'),
            'Close': current['close'],
            'Volume': int(current['volume']),
            'AvgVol(20)': int(avg_vol) if not pd.isna(avg_vol) else 0,
            'RVOL': rvol
        })
        
    except Exception as e:
        print(f"Error {symbol}: {e}")

# Sort by RVOL descending
results.sort(key=lambda x: x['RVOL'], reverse=True)

for r in results:
    print(f"{r['Symbol']:<6} | {r['Date']:<10} | {r['Close']:<8.2f} | {r['Volume']:<10} | {r['AvgVol(20)']:<10} | {r['RVOL']:.2f}")
