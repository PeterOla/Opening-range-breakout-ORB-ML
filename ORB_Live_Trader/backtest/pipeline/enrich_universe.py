"""
Enrich Sentiment Universe (Backtest Pipeline)
=============================================
Takes the raw sentiment universe and enriches it with:
1. 5-min Price Data (bars_json)
2. Daily Metrics (ATR, AvgVol, Shares)

Output: ORB_Live_Trader/backtest/data/backtest/orb/universe/research_2021_sentiment_ROLLING24H/universe_sentiment_0.9.parquet
"""

import sys
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm
from datetime import time, datetime, timedelta
import json

# Paths
PIPELINE_DIR = Path(__file__).parent
BACKTEST_DIR = PIPELINE_DIR.parent
DATA_DIR = BACKTEST_DIR / "data"
INPUT_SCORED_NEWS = DATA_DIR / "news" / "news_micro_full_1y_scored.parquet"

# Sibling path for main data (assuming original structure available or mapped)
# We need 5min and daily processed data. 
# Assuming they reside in PROJECT_ROOT/data/processed (as per original script)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAIN_DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR_5MIN = MAIN_DATA_DIR / "processed" / "5min"
DATA_DIR_DAILY = MAIN_DATA_DIR / "processed" / "daily"
UNIVERSE_ROOT = DATA_DIR / "universe" # Local output

THRESHOLDS = [0.60, 0.70, 0.80, 0.90, 0.95]

# -----------------------------------------------------------------------------
# Helpers (Ported/Inlined to be self-contained)
# -----------------------------------------------------------------------------

OR_START = time(9, 30)
OR_END = time(16, 0)

def load_daily(symbol: str):
    p = DATA_DIR_DAILY / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        if 'date' not in df.columns or df.empty:
            return None
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
        return df
    except Exception:
        return None

def load_5min_full(symbol: str):
    p = DATA_DIR_5MIN / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        if df.empty or 'datetime' not in df.columns:
            return None
        df['datetime'] = pd.to_datetime(df['datetime'])
        df['date_et'] = df['datetime'].dt.date
        df['time'] = df['datetime'].dt.time
        return df
    except Exception:
        return None

def extract_or(bars: pd.DataFrame):
    or_row = bars[bars['time'] == OR_START]
    if not or_row.empty:
        r = or_row.iloc[0]
        return {
            'or_open': float(r['open']),
            'or_high': float(r['high']),
            'or_low': float(r['low']),
            'or_close': float(r['close']),
            'or_volume': float(r['volume']),
        }
    
    rth_mask = (bars['time'] >= OR_START) & (bars['time'] <= OR_END)
    rth_bars = bars[rth_mask].sort_values('datetime')
    if rth_bars.empty:
        return None
    
    r = rth_bars.iloc[0]
    return {
        'or_open': float(r['open']),
        'or_high': float(r['high']),
        'or_low': float(r['low']),
        'or_close': float(r['close']),
        'or_volume': float(r['volume']),
    }

def serialize_bars(bars: pd.DataFrame) -> str:
    bars_clean = bars[['datetime', 'open', 'high', 'low', 'close', 'volume']].copy()
    bars_clean['datetime'] = bars_clean['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return bars_clean.to_json(orient='records')

# -----------------------------------------------------------------------------
# Core Logic
# -----------------------------------------------------------------------------

def generate_base_universe(df_news, threshold, mode='rolling_24h'):
    filtered = df_news[df_news['positive_score'] > threshold].copy()
    
    if 'timestamp' in filtered.columns:
        filtered['timestamp'] = pd.to_datetime(filtered['timestamp'], utc=True)
        filtered['timestamp_et'] = filtered['timestamp'].dt.tz_convert('America/New_York')
        filtered['news_date'] = filtered['timestamp_et'].dt.date
        filtered['news_time'] = filtered['timestamp_et'].dt.time
    
    if mode == 'rolling_24h':
        market_open = time(9, 30)
        def assign_trade_date(row):
            if row['news_time'] < market_open:
                return row['news_date']
            else:
                return (pd.to_datetime(row['news_date']) + pd.tseries.offsets.BDay(1)).date()
        filtered['trade_date'] = filtered.apply(assign_trade_date, axis=1)
    
    elif mode == 'premarket':
        market_open = time(9, 30)
        def assign_trade_date(row):
            if row['news_time'] < market_open:
                return row['news_date']
            else:
                return (pd.to_datetime(row['news_date']) + pd.tseries.offsets.BDay(1)).date()
        filtered['trade_date'] = filtered.apply(assign_trade_date, axis=1)
    else:
        raise ValueError(f"Unknown mode: {mode}")
    
    if 'symbol' in filtered.columns:
        filtered = filtered.rename(columns={'symbol': 'ticker'})
    
    # Deduplicate: Max score per day/ticker
    universe = filtered.groupby(['trade_date', 'ticker'])['positive_score'].max().reset_index()
    return universe

def main():
    parser = argparse.ArgumentParser(description="Enrich sentiment universe")
    parser.add_argument('--mode', type=str, default='rolling_24h', choices=['rolling_24h', 'premarket'])
    args = parser.parse_args()
    
    if not INPUT_SCORED_NEWS.exists():
        print(f"Input file not found: {INPUT_SCORED_NEWS}")
        return

    # Folder specific to mode
    if args.mode == 'rolling_24h':
        OUTPUT_DIR = UNIVERSE_ROOT / "research_2021_sentiment_ROLLING24H"
    else:
        OUTPUT_DIR = UNIVERSE_ROOT / "research_2021_sentiment_PREMARKET"
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading Scored News: {INPUT_SCORED_NEWS.name}")
    df_raw = pd.read_parquet(INPUT_SCORED_NEWS)
    print(f"Loaded {len(df_raw)} news items.")
    
    for thresh in THRESHOLDS:
        print(f"\n--- Generating Universe for Threshold > {thresh} (Mode: {args.mode}) ---")
        
        base_df = generate_base_universe(df_raw, thresh, mode=args.mode)
        print(f"Candidates: {len(base_df)}")
        
        base_df['bars_json'] = None
        base_df['atr_14'] = np.nan
        base_df['avg_volume_14'] = np.nan
        base_df['shares_outstanding'] = np.nan
        base_df['prev_close'] = np.nan
        
        tickers = base_df['ticker'].unique()
        print(f"Processing {len(tickers)} unique tickers...")
        
        enriched_rows = []
        
        for ticker in tqdm(tickers):
            daily_df = load_daily(ticker)
            bars_df = load_5min_full(ticker)
            
            if daily_df is None or bars_df is None:
                continue
                
            ticker_mask = base_df['ticker'] == ticker
            ticker_rows = base_df[ticker_mask]
            
            for idx, row in ticker_rows.iterrows():
                trade_date = row['trade_date']
                if isinstance(trade_date, pd.Timestamp):
                    trade_date = trade_date.date()
                
                daily_df['date_obj'] = pd.to_datetime(daily_df['date']).dt.date
                daily_matches = daily_df[daily_df['date_obj'] == trade_date]
                
                if daily_matches.empty:
                    continue
                daily_row = daily_matches.iloc[0]
                
                day_bars = bars_df[bars_df['date_et'] == trade_date].copy()
                if day_bars.empty:
                    continue
                
                or_data = extract_or(day_bars)
                if not or_data:
                    continue
                
                direction = 0
                if or_data['or_close'] > or_data['or_open']:
                    direction = 1
                elif or_data['or_close'] < or_data['or_open']:
                    direction = -1

                rvol = 0.0
                avg_vol = daily_row.get('avg_volume_14', 0)
                if avg_vol and avg_vol > 0:
                    rvol = (or_data['or_volume'] * 78.0) / avg_vol
                
                row_dict = row.to_dict()
                row_dict['bars_json'] = serialize_bars(day_bars)
                row_dict['atr_14'] = daily_row.get('atr_14', np.nan)
                row_dict['avg_volume_14'] = daily_row.get('avg_volume_14', np.nan)
                row_dict['shares_outstanding'] = daily_row.get('shares_outstanding', np.nan)
                
                row_dict['or_open'] = or_data['or_open']
                row_dict['or_high'] = or_data['or_high']
                row_dict['or_low'] = or_data['or_low']
                row_dict['or_close'] = or_data['or_close']
                row_dict['or_volume'] = or_data['or_volume']
                row_dict['direction'] = direction
                row_dict['rvol'] = rvol
                row_dict['prev_close'] = daily_row.get('prev_close', daily_row.get('close', np.nan)) 
                
                enriched_rows.append(row_dict)

        if not enriched_rows:
            print(f"Warning: No valid rows enriched for threshold {thresh}")
            continue

        result_df = pd.DataFrame(enriched_rows)
        result_df['rvol_rank'] = result_df.groupby('trade_date')['rvol'].rank(method='first', ascending=False)
        
        filename = f"universe_sentiment_{str(thresh)}.parquet"
        out_path = OUTPUT_DIR / filename
        result_df.to_parquet(out_path)
        print(f"✅ Saved enriched universe: {out_path} ({len(result_df)} rows)")

if __name__ == "__main__":
    main()
