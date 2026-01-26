import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, time as dt_time

# Setup Paths
ORB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ORB_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(ORB_ROOT))

from ORB_Live_Trader.backtest.fast_backtest import run_strategy

def verify_2025_01_23():
    print("==================================================")
    print("BACKTEST VERIFICATION: 2025-01-23")
    print("==================================================")
    
    # 1. Locate the exact daily universe file used by Live
    # Live uses: data/sentiment/daily_2025-01-23.parquet
    target_date = "2025-01-23"
    universe_path = ORB_ROOT / "data" / "sentiment" / f"daily_{target_date}.parquet"
    
    if not universe_path.exists():
        print(f"CRITICAL: Live Universe file not found at {universe_path}")
        print("Please run the live verification first to generate it!")
        return

    print(f"Using Universe: {universe_path.name}")
    
    # 2. Enrich with Technicals (Backtest needs ATR/Vol)
    # The 'daily_2025-01-23.parquet' only has Sentiment.
    # We must fetch/calc technicals.
    
    df_universe = pd.read_parquet(universe_path)
    print(f"  Raw Symbols: {len(df_universe)}")
    
    # We can reuse live_pipeline functions if we import them, but let's keep it self-contained for speed/simplicity
    # using the same logic: Fetch stats from Alpaca
    from ORB_Live_Trader.pipeline.live_pipeline import fetch_technical_metrics, fetch_opening_bars
    
    # Convert 'timestamp' to date object
    # FORCE trade_date to target_date because we loaded the daily file for THIS date
    # This prevents any timezone/timestamp mismatch issues (e.g. 2026 run date vs 2025 trade date)
    target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    df_universe['trade_date'] = target_dt
    symbols = df_universe['symbol'].unique().tolist()
    
    # Chunking to avoid massive requests
    print("  Fetching Technicals (ATR/Vol) from Alpaca...")
    tech_df = pd.DataFrame()
    chunk_size = 100
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        try:
             # fetch_technical_metrics handles daily bars download & calc
             stats = fetch_technical_metrics(chunk, target_dt) 
             if not stats.empty:
                 tech_df = pd.concat([tech_df, stats])
        except Exception as e:
            print(f"Warn: Chunk {i} failed: {e}")
            
    if tech_df.empty:
        print("CRITICAL: Failed to fetch technicals. Cannot run backtest.")
        return

    # Merge
    # tech_df has [symbol, atr_14, avg_volume_14]
    # We also need 'rvol'. live_pipeline calculates it as:
    # rvol = (current_vol / avg_volume_14). But at 09:30? No, usually end of day or pre-market volume?
    # Actually, live_pipeline.py: generate_initial_pool -> 
    # "rvol" is Relative Volume of the *gap* or *pre-market*? 
    # Let's check live_pipeline.py logic... 
    # Wait, the backtest engine expects 'rvol' in the input.
    # In live trading, we likely sort by 'rvol' calculated from the 5-min OR candle vs 5-min Avg?
    # fast_backtest.py line 281 sums rvol.
    
    # LET'S SIMPLIFY: The user wants to verify 2025-01-23.
    # The live log showed: 
    # "Selection Complete. Monitoring Top 5 RVOL Green Candles."
    # Watchlist: ['GRAL', 'AMAL', 'MPWR', 'SLAB', 'SYNA']
    # So we just need to force the backtest to trade THESE 5 symbols.
    
    target_symbols = ['GRAL', 'AMAL', 'MPWR', 'SLAB', 'SYNA']
    print(f"  Forcing Universe to Match Live Watchlist: {target_symbols}")
    
    # Filter universe to just these 5
    df_universe = df_universe[df_universe['symbol'].isin(target_symbols)].copy()
    
    # Merge ATR/Vol
    df_universe = df_universe.merge(tech_df, on='symbol', how='inner')
    
    # DEDUP: Sentiment file has multiple rows per symbol (headlines). We need 1 row per symbol.
    df_universe = df_universe.drop_duplicates(subset=['symbol']).copy()
    
    # Fake RVOL to preserve sort order (GRAL first, etc)
    # Live Log Order: GRAL, AMAL, MPWR, SLAB, SYNA
    # We assign descending RVOL manually
    sorter = {sym: i for i, sym in enumerate(target_symbols)}
    df_universe['rank'] = df_universe['symbol'].map(sorter)
    df_universe['rvol'] = 100 - df_universe['rank'] # High to low
    
    # Needed columns for backtest: 'atr_14', 'avg_volume_14', 'direction', 'rvol', 'or_high', 'or_low', 'bars_json'
    # 'direction': 1 (Long). 
    df_universe['direction'] = 1
    
    # Now valid 5-min Bars (Open, High, Low, Close, Volume) for the day
    # fast_backtest needs 'bars_json' which is the FULL DAY 5-min bars.
    # We must fetch full day 5-min bars for these 5 symbols.
    
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    import os
    
    print("  Fetching Full Day 5-min Bars for Simulation...")
    # Fetch full day - USE TIMEZONE AWARE DATES TO AVOID UTC CONFUSION
    import pytz
    ny_tz = pytz.timezone("America/New_York")
    
    # 09:30 ET
    start_dt_et = ny_tz.localize(datetime.strptime(f"{target_date} 09:30:00", "%Y-%m-%d %H:%M:%S"))
    end_dt_et = ny_tz.localize(datetime.strptime(f"{target_date} 15:55:00", "%Y-%m-%d %H:%M:%S"))
    
    client = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"))
    req = StockBarsRequest(
        symbol_or_symbols=target_symbols,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start_dt_et,
        end=end_dt_et,
        adjustment='raw'
    )
    bars = client.get_stock_bars(req).df
    bars = bars.reset_index() #(symbol, timestamp) -> cols
    
    # Format per symbol
    bars_json_map = {}
    or_high_map = {}
    or_low_map = {}
    
    for sym in target_symbols:
        sym_bars = bars[bars['symbol'] == sym].copy()
        if sym_bars.empty: 
            continue
        
        # Helper to get ET time from timestamp (which is UTC aware)
        sym_bars['dt_et'] = sym_bars['timestamp'].dt.tz_convert(ny_tz)
        
        # Filter for >= 09:30 ET just to be safe
        sym_bars = sym_bars[sym_bars['dt_et'] >= start_dt_et].copy()
        if sym_bars.empty: continue
        
        # Calculate OR High/Low (First 5 min bar - Should be 09:30:00)
        first_bar = sym_bars.iloc[0]
        
        # VALIDATE it is 09:30
        if first_bar['dt_et'].time() != dt_time(9, 30):
            print(f"WARN: First bar for {sym} is {first_bar['dt_et'].time()}, not 09:30! Skipping.")
            continue
        
        or_high_map[sym] = first_bar['high']
        or_low_map[sym] = first_bar['low']
        
        # Convert to serialized records for backtest
        # structure: datetime, open, high, low, close, volume
        # timestamp is tz-aware, convert to naive? fast_backtest handles deserialization
        # Let's clean it up
        sym_bars.rename(columns={'timestamp': 'datetime'}, inplace=True)
        records = sym_bars[['datetime', 'open', 'high', 'low', 'close', 'volume']].to_dict('records')
        
        # Serialize to JSON string because fast_backtest.py expects string for dict-records
        # OR list-of-lists for compact. String is safer here.
        import json
        # We need to serialize datetime objects to string first
        def date_handler(obj):
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return obj
            
        bars_json_map[sym] = json.dumps(records, default=date_handler)

    df_universe['bars_json'] = df_universe['symbol'].map(bars_json_map)
    df_universe['or_high'] = df_universe['symbol'].map(or_high_map)
    df_universe['or_low'] = df_universe['symbol'].map(or_low_map)
    
    # Filter out any that failed fetching
    df_universe = df_universe.dropna(subset=['bars_json'])
    
    # Save a temporary enriched universe to pass to run_strategy
    temp_uni_path = ORB_ROOT / "data" / "sentiment" / f"verified_{target_date}.parquet"
    df_universe.to_parquet(temp_uni_path)
    universe_path = temp_uni_path

    # 3. Run Backtest
    run_strategy(
        universe_path=universe_path,
        min_atr=0.0, # Live filters already applied in daily parquet
        min_volume=0, # Live filters already applied
        top_n=5,
        side_filter='long',
        run_name="verify_2025_01_23",
        compound=True,
        stop_atr_scale=0.05, # Strategy 1
        start_date=target_date,
        end_date=target_date,
        leverage=1.0, # BP = 1000 * 1 = 1000
        initial_capital=1000.00, # Matches Buying Power Override
        entry_cutoff=None, # Live system keeps orders open all day
        risk_scale=1.0
    )
    
    # 3. Load Results to Sum PNL
    results_path = ORB_ROOT / "backtest" / "data" / "runs" / "compound" / "verify_2025_01_23" / "simulated_trades.parquet"
    if results_path.exists():
        df = pd.read_parquet(results_path)
        total_pnl = df['dollar_pnl'].sum()
        print("\n==================================================")
        print(f"BACKTEST TOTAL PNL: ${total_pnl:.2f}")
        print("==================================================")
        print(df[['ticker', 'side', 'dollar_pnl', 'exit_reason']])
    else:
        print("No trades generated.")

if __name__ == "__main__":
    verify_2025_01_23()
