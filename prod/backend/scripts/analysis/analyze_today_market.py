"""
Analyze Today's Market for ORB Setups (Retrospective).
Detailed inspection of Sentiment -> Technicals pipeline.
"""
import asyncio
import logging
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, time, timedelta

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from services.sentiment_scanner import get_micro_cap_universe, fetch_universe_news, load_sentiment_model
from services.scanner import fetch_daily_bars, fetch_5min_bars, get_opening_range, compute_rvol
from db.database import SessionLocal
from core.config import settings

# Force full output
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

async def main():
    print(f"=== Market Analysis for {datetime.now().date()} ===")
    
    # 1. Pipeline: Sentiment
    print("\n--- STEP 1: Sentiment Scanning ---")
    
    # A. Get Universe
    limit = 50_000_000
    print(f"Fetching Micro-cap universe (Float < {limit})...")
    # specific fallback import if needed, assuming service handles it
    symbols = get_micro_cap_universe(limit)
    print(f"Universe Size: {len(symbols)}")
    
    if not symbols:
        print("CRITICAL: Universe is empty.")
        return

    # B. Fetch News
    print(f"Fetching news (24h lookback) via Alpaca...")
    news_map = fetch_universe_news(symbols, lookback_hours=24)
    print(f"Symbols with news: {len(news_map)}")
    
    # C. Score
    print("Loading finbert...")
    classifier = load_sentiment_model()
    
    candidates_sentiment = []
    
    print("Scoring headlines...")
    for sym, headlines in news_map.items():
        if not headlines:
            continue
            
        # Score specifically
        results = classifier(headlines)
        # simplistic aggregation: max positive score
        max_pos = 0.0
        best_hl = ""
        
        for i, res in enumerate(results):
            if res['label'] == 'positive':
                if res['score'] > max_pos:
                    max_pos = res['score']
                    best_hl = headlines[i]
        
        if max_pos > 0.90:
            candidates_sentiment.append({
                "symbol": sym,
                "sentiment": max_pos,
                "headline": best_hl[:50] + "..."
            })
            
    print(f"Found {len(candidates_sentiment)} symbols with Sentiment > 0.90")
    if candidates_sentiment:
        df_sent = pd.DataFrame(candidates_sentiment)
        print(df_sent.sort_values("sentiment", ascending=False).head(10))
    else:
        print("No sentiment candidates found. Stopping.")
        return

    # 2. Pipeline: Technicals
    print("\n--- STEP 2: Technical Analysis ---")
    sent_symbols = [x["symbol"] for x in candidates_sentiment]
    
    # A. Snapshot/Daily (check Price, Vol, ATR)
    # We'll rely on fetch_daily_bars for ATR and volume
    print("Fetching daily bars (1 year) for ATR calculation...")
    daily_bars = await fetch_daily_bars(sent_symbols)
    
    valid_technical = []
    
    for sym in sent_symbols:
        bars = daily_bars.get(sym)
        # Check if empty (works for dict result or None)
        if bars is None:
             continue
        # If DataFrame, check empty
        if hasattr(bars, 'empty') and bars.empty:
             continue
        if len(bars) < 14:
             continue
            
        # Simple ATR(14) - taking last complete day
        # dataframe assumed
        df = pd.DataFrame(bars) # Ensure it's a DF if fetch_daily_bars returns list/dicts
        if hasattr(df, 'to_pandas'): df = df.to_pandas()
        
        # Calculate TR
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        tr = pd.concat([high-low, (high-close).abs(), (low-close).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        
        last_bar = df.iloc[-1]
        price = last_bar['close']
        
        # Check filters
        if not (1.0 <= price <= 50.0):
             print(f"Reject {sym}: Price ${price} out of range")
             continue
             
        # Vol check (Avg 20)
        avg_vol = df['volume'].tail(20).mean()
        if avg_vol < 100_000:
             print(f"Reject {sym}: AvgVol {int(avg_vol)} < 100k")
             continue
             
        valid_technical.append(sym)
        
    print(f"Passed Price/Vol Filters: {len(valid_technical)} symbols")
    
    if not valid_technical:
        return

    # B. Intraday (RVOL)
    print("Fetching 5min bars for today...")
    # target_date = datetime.now().date()
    # We want morning data. 
    bars_5min = await fetch_5min_bars(valid_technical, lookback_days=1)
    
    analysis_results = []
    
    for sym in valid_technical:
        df_5 = bars_5min.get(sym)
        if df_5 is None or df_5.empty:
            print(f"{sym}: No intraday data")
            continue
            
        # Get Opening Range
        or_data = get_opening_range(df_5)
        if not or_data:
            print(f"{sym}: Could not calc Opening Range")
            continue
            
        # Calc RVOL
        # Need average volume for the 9:30-10:00 candle? 
        # scanner.py: compute_rvol(or_data["or_volume"], daily_bars.get(sym), ...
        
        # Re-calc ATR roughly for Stop check
        atr = 0.5 # placeholder
        d_bars = daily_bars.get(sym)
        # convert to df if needed
        df_d = pd.DataFrame(d_bars)
        
        high = df_d['high']
        low = df_d['low']
        close = df_d['close'].shift(1)
        tr = pd.concat([high-low, (high-close).abs(), (low-close).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        vol_period = 20 # default
        
        # Manual RVOL Logic from scanner.py
        # rvol = or_volume / (avg_daily_volume / 78 * 3) # rough estimate usually used?
        # Actually use the real function
        rvol = compute_rvol(or_data["or_volume"], d_bars, vol_period)
        
        row = {
            "Symbol": sym,
            "Price": or_data["or_high"],
            "ATR": round(atr, 2),
            "RVOL": round(rvol, 2) if rvol else 0.0,
            "Direction": "LONG" if or_data["or_direction"] == 1 else "SHORT" if or_data["or_direction"] == -1 else "DOJI",
            "OR Vol": or_data["or_volume"],
            "Stop (10% ATR)": round(atr * 0.10, 2),
            "Outcome": "CHECK"
        }
        analysis_results.append(row)
        
    print("\n--- DETAILED CANDIDATE ANALYSIS ---")
    if analysis_results:
        df_res = pd.DataFrame(analysis_results)
        print(df_res.sort_values("RVOL", ascending=False))
        
        print("\n--- EVALUATION ---")
        print("Requirements for trade:")
        print("1. Sentiment > 0.90 (Passed)")
        print("2. RVOL >= 1.0")
        print("3. Direction == LONG")
        print("4. Price $1 - $50")
        
        # Highlight tradeable
        tradeable = df_res[
            (df_res["RVOL"] >= 1.0) & 
            (df_res["Direction"] == "LONG")
        ]
        print(f"\nPotential Trades (If active at 9:36 AM): {len(tradeable)}")
        if not tradeable.empty:
            print(tradeable)
    else:
        print("No candidates survived technical checks.")

if __name__ == "__main__":
    asyncio.run(main())
