"""Show candidates that did not enter."""
import asyncio
import pandas as pd
from datetime import datetime, date, time
from zoneinfo import ZoneInfo
from services.historical_scanner import get_historical_top20
from services.universe import fetch_5min_bars

ET = ZoneInfo("America/New_York")

async def test():
    target = date(2025, 11, 21)
    result = await get_historical_top20('2025-11-21', top_n=20)
    
    # Get the non-entries
    non_entries = [c for c in result['candidates'] if not c.get('entered', False)]
    symbols = [c['symbol'] for c in non_entries]
    
    # Fetch their 5-min bars to get day high/low
    target_dt = datetime.combine(target, time(0, 0), tzinfo=ET)
    bars = await fetch_5min_bars(symbols, lookback_days=3, target_date=target_dt)
    
    print("Candidates that did NOT enter:")
    print("-" * 80)
    
    for c in non_entries:
        sym = c['symbol']
        direction = "LONG" if c['direction'] == 1 else "SHORT"
        
        # Get day high/low from bars
        if sym in bars:
            df = bars[sym].copy()
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            if df['timestamp'].dt.tz is None:
                df['timestamp'] = df['timestamp'].dt.tz_localize('UTC').dt.tz_convert(ET)
            else:
                df['timestamp'] = df['timestamp'].dt.tz_convert(ET)
            df['date'] = df['timestamp'].dt.date
            
            # Filter to target date, after 9:35
            day_bars = df[(df['date'] == target) & (df['timestamp'].dt.time > time(9, 35))]
            
            if not day_bars.empty:
                day_high = day_bars['high'].max()
                day_low = day_bars['low'].min()
            else:
                day_high = day_low = "N/A"
        else:
            day_high = day_low = "N/A"
        
        print(f"#{c['rank']} {sym} ({direction})")
        print(f"   Entry Level: ${c['entry_price']:.2f}")
        print(f"   OR High: ${c['or_high']:.2f}, OR Low: ${c['or_low']:.2f}")
        print(f"   Day High: ${day_high:.2f}, Day Low: ${day_low:.2f}")
        
        # Explain why no entry
        if c['direction'] == 1:  # LONG
            print(f"   Gap to entry: ${c['entry_price'] - day_high:.2f} (needed to reach ${c['entry_price']:.2f})")
        else:  # SHORT
            print(f"   Gap to entry: ${day_low - c['entry_price']:.2f} (needed to reach ${c['entry_price']:.2f})")
        print()

if __name__ == "__main__":
    asyncio.run(test())
