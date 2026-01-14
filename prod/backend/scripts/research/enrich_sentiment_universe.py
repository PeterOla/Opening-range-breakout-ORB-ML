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
    from prod.backend.scripts.ORB.build_universe import load_5min_full, load_daily, serialize_bars, extract_or
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

INPUT_SCORED_NEWS = PROJECT_ROOT / "data" / "research" / "news" / "news_micro_full_1y_scored.parquet"
OUTPUT_DIR = PROJECT_ROOT / "data" / "backtest" / "orb" / "universe" / "research_2021_sentiment"
THRESHOLDS = [0.60, 0.70, 0.80, 0.90, 0.95]

# Ensure directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def generate_base_universe(df_news, threshold):
    """Filter news > threshold and group by date/ticker to make a base universe list."""
    # Filter
    filtered = df_news[df_news['positive_score'] > threshold].copy()
    
    # Standardize Dates
    # If using 'timestamp' is UTC, convert to Eastern Date
    # Assuming 'trade_date' is just the date component of the news for now (Research simplification)
    # Ideally: News after 16:00 ET -> Next Trade Date.
    # For now: Just use date().
    if 'timestamp' in filtered.columns:
        filtered['timestamp'] = pd.to_datetime(filtered['timestamp'], utc=True)
        # Convert to Eastern Time approximately (UTC-5)
        filtered['trade_date'] = filtered['timestamp'].dt.tz_convert('America/New_York').dt.date
    
    # Deduplicate: If multiple news items for same ticker on same day, take MAX score
    # Group by [trade_date, symbol]
    # Rename 'symbol' to 'ticker' if needed
    if 'symbol' in filtered.columns:
        filtered = filtered.rename(columns={'symbol': 'ticker'})
    elif 'symbols' in filtered.columns:
        filtered = filtered.rename(columns={'symbols': 'ticker'}) # Handle plural if present

    universe = filtered.groupby(['trade_date', 'ticker'])['positive_score'].max().reset_index()
    return universe

def main():
    if not INPUT_SCORED_NEWS.exists():
        print(f"Input file not found: {INPUT_SCORED_NEWS}")
        return

    print(f"Loading Scored News: {INPUT_SCORED_NEWS.name}")
    df_raw = pd.read_parquet(INPUT_SCORED_NEWS)
    print(f"Loaded {len(df_raw)} news items.")
    
    # Loop through thresholds
    for thresh in THRESHOLDS:
        print(f"\n--- Generating Universe for Threshold > {thresh} ---")
        
        # 1. Generate Base List
        base_df = generate_base_universe(df_raw, thresh)
        print(f"Candidates: {len(base_df)}")
        
        # Init Enrichment Columns
        base_df['bars_json'] = None
        base_df['atr_14'] = np.nan
        base_df['avg_volume_14'] = np.nan
        base_df['shares_outstanding'] = np.nan
        base_df['prev_close'] = np.nan
        
        # Process by Ticker (optimization to load files once PER universe... 
        # actually smarter to load data once and loop thresholds, but let's keep it simple for legacy compatibility)
        tickers = base_df['ticker'].unique()
        print(f"Processing {len(tickers)} unique tickers...")
        
        enriched_rows = []
        
        for ticker in tqdm(tickers):
            # 1. Load Data
            daily_df = load_daily(ticker)
            bars_df = load_5min_full(ticker)
            
            if daily_df is None or bars_df is None:
                continue
                
            # Get subset of universe for this ticker
            ticker_mask = base_df['ticker'] == ticker
            ticker_rows = base_df[ticker_mask]
            
            for idx, row in ticker_rows.iterrows():
                trade_date = row['trade_date']
                
                # Ensure trade_date is date object
                if isinstance(trade_date, pd.Timestamp):
                    trade_date = trade_date.date()
                
                # Match Daily Data
                # Ensure date column is date object for comparison
                daily_df['date_obj'] = pd.to_datetime(daily_df['date']).dt.date
                daily_matches = daily_df[daily_df['date_obj'] == trade_date]
                
                if daily_matches.empty:
                    continue
                    
                daily_row = daily_matches.iloc[0]
                
                # Match Intraday Data
                # bars_df has 'date_et' from load_5min_full
                day_bars = bars_df[bars_df['date_et'] == trade_date].copy()
                if day_bars.empty:
                    continue
                
                # Extract OR Data
                or_data = extract_or(day_bars)
                if not or_data:
                    continue
                
                # Calculate Direction
                direction = 0
                if or_data['or_close'] > or_data['or_open']:
                    direction = 1
                elif or_data['or_close'] < or_data['or_open']:
                    direction = -1

                # Calculate RVOL (Relative Volume)
                # Formula: (OR_Volume * 78) / Avg_Vol_14
                # 78 = 390 trading minutes / 5 min bars
                rvol = 0.0
                avg_vol = daily_row.get('avg_volume_14', 0)
                if avg_vol and avg_vol > 0:
                    rvol = (or_data['or_volume'] * 78.0) / avg_vol
                
                # Enrich
                row_dict = row.to_dict()
                row_dict['bars_json'] = serialize_bars(day_bars)
                row_dict['atr_14'] = daily_row.get('atr_14', np.nan)
                row_dict['avg_volume_14'] = daily_row.get('avg_volume_14', np.nan)
                row_dict['shares_outstanding'] = daily_row.get('shares_outstanding', np.nan)
                
                # Add OR Columns & Metrics
                row_dict['or_open'] = or_data['or_open']
                row_dict['or_high'] = or_data['or_high']
                row_dict['or_low'] = or_data['or_low']
                row_dict['or_close'] = or_data['or_close']
                row_dict['or_volume'] = or_data['or_volume']
                row_dict['direction'] = direction
                row_dict['rvol'] = rvol # Adding RVOL
                
                # Note: 'prev_close' in our daily files is pre-calculated as T-1 close.
                # If not, we might be taking T's close.
                row_dict['prev_close'] = daily_row.get('prev_close', daily_row.get('close', np.nan)) 
                
                enriched_rows.append(row_dict)

        if not enriched_rows:
            print(f"Warning: No valid rows enriched for threshold {thresh}")
            continue

        result_df = pd.DataFrame(enriched_rows)
        
        # Add Rvol Rank (Daily Rank)
        # Group by trade_date and rank by RVOL descending
        result_df['rvol_rank'] = result_df.groupby('trade_date')['rvol'].rank(method='first', ascending=False)
        
        # Save
        filename = f"universe_sentiment_{str(thresh)}.parquet"
        out_path = OUTPUT_DIR / filename
        result_df.to_parquet(out_path)
        print(f"✅ Saved enriched universe: {out_path} ({len(result_df)} rows)")

if __name__ == "__main__":
    main()
