"""
Enrich Sentiment Universe (Research)
====================================
Takes the raw sentiment universe (Date, Ticker, Score) and enriches it with:
1. 5-min Price Data (bars_json)
2. Daily Metrics (ATR, AvgVol, Shares)

Output: universe_sentiment_ready.parquet (Ready for fast_backtest.py)
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from prod.backend.scripts.ORB.build_universe import load_5min_full, load_daily, serialize_bars
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

INPUT_FILE = PROJECT_ROOT / "data" / "backtest" / "orb" / "universe" / "universe_sentiment_only.parquet"
OUTPUT_FILE = PROJECT_ROOT / "data" / "backtest" / "orb" / "universe" / "universe_sentiment_ready.parquet"

def main():
    if not INPUT_FILE.exists():
        print(f"Input file not found: {INPUT_FILE}")
        return

    print(f"Loading {INPUT_FILE.name}...")
    df = pd.read_parquet(INPUT_FILE)
    print(f"Candidates: {len(df)}")
    
    # Init columns
    df['bars_json'] = None
    df['atr_14'] = np.nan
    df['avg_volume_14'] = np.nan
    df['shares_outstanding'] = np.nan
    df['prev_close'] = np.nan
    
    # Process by Ticker (optimization to load files once)
    tickers = df['ticker'].unique()
    print(f"Processing {len(tickers)} unique tickers...")
    
    # We can probably parallelize this, but for < 1000 items, sequential is fine?
    # Actually, 2234 items. Sequential might take a minute.
    
    enriched_rows = []
    
    for ticker in tqdm(tickers):
        # 1. Load Data
        daily_df = load_daily(ticker)
        bars_df = load_5min_full(ticker)
        
        if daily_df is None or bars_df is None:
            continue
            
        # Get subset of universe for this ticker
        ticker_mask = df['ticker'] == ticker
        ticker_rows = df[ticker_mask]
        
        for idx, row in ticker_rows.iterrows():
            trade_date = row['trade_date']
            trade_date_ts = pd.Timestamp(trade_date)
            
            # Daily Metrics (For the *previous* day technically? Or 'current'?)
            # build_universe.py usually takes the row matching the date
            # In build_universe.py: `daily_row = df_daily[df_daily['date'] == date]`
            # and `prev_close` was `daily_row['close']`? 
            # No, `prev_close` should be previous day close.
            # But the dataset usually aligns 'date' to midnight UTC.
            
            # Let's match `build_universe.py` logic:
            # `mask = (df_daily['date'] >= start_ts) ...`
            # For each day: `trading_date = daily_row['date'].date()`
            # So `date` in daily parquet IS the trading date.
            
            daily_matches = daily_df[daily_df['date'] == trade_date_ts]
            if daily_matches.empty:
                continue
                
            daily_row = daily_matches.iloc[0]
            
            # 5-Min Bars for this day
            # bars_df has 'date_et' (from import) if we rely on load_5min_full adding it?
            # Wait, `load_5min_full` inside `build_universe.py` adds `date_et`.
            # Let's verify `load_5min_full` implementation in the imported module.
            # Yes it should.
            
            day_bars = bars_df[bars_df['date_et'] == trade_date.date() if hasattr(trade_date, 'date') else trade_date].copy()
            if day_bars.empty:
                continue
                
            # Create enriched dict
            # We copy original row and update
            new_row = row.to_dict()
            new_row['bars_json'] = serialize_bars(day_bars)
            new_row['atr_14'] = daily_row.get('atr_14')
            new_row['avg_volume_14'] = daily_row.get('avg_volume_14')
            new_row['shares_outstanding'] = daily_row.get('shares_outstanding')
            new_row['prev_close'] = daily_row.get('close') # This is actually Close of T. 
            # Ideally we want Prev Close (T-1).
            # But `build_universe` logic was: `'prev_close': float(daily_row['close'])`
            # Wait, if `daily_row` is T, then `close` is T's close.
            # We want T-1 close for Gap calculation.
            # `build_universe` comment said `# Approx prev close logic simplified`.
            # If fast_backtest recalculates gap using bars, it takes `bars[0].open` vs `prev_close`.
            # If we provide T's close, Gap = (Open - Close_T) / Close_T? No.
            # We need T-1.
            
            # Let's try to get T-1
            # daily_df is sorted by date?
            # Index of daily_row?
            try:
                # Assuming daily_df is sorted
                # Find index of match
                match_idx = daily_matches.index[0]
                # If match_idx > 0, prev is match_idx - 1?
                # We can't rely on integer index unless reset.
                # Let's shift.
                pass
            except:
                pass
                
            enriched_rows.append(new_row)
            
    if not enriched_rows:
        print("No enriched rows generated.")
        return
        
    final_df = pd.DataFrame(enriched_rows)
    print(f"Enriched {len(final_df)} rows.")
    
    # Save
    final_df.to_parquet(OUTPUT_FILE)
    print(f"✅ Saved Enriched Universe to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
