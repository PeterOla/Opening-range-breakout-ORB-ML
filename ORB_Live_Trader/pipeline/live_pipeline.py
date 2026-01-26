"""
Live Data Pipeline Module
=========================
Handles the end-to-end data ingestion for the ORB strategy:
1. Fetch News (Alpaca)
2. Score Sentiment (FinBERT)
3. Apply Attribution (Rolling 24H)
4. Filter Candidates

Callable by main.py for both Live and Verification modes.
"""
import os
import sys
import pandas as pd
import pytz
import torch
import time as time_module
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from typing import List, Optional

from alpaca.data.historical.news import NewsClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import NewsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from transformers import BertTokenizer, BertForSequenceClassification

# -----------------------------------------------------------------------------
# Configuration & Paths
# -----------------------------------------------------------------------------

# Folders
ORB_ROOT = Path(__file__).resolve().parents[1]
data_dir = ORB_ROOT / "data"
news_dir = data_dir / "news"
sentiment_dir = data_dir / "sentiment"
reference_dir = data_dir / "reference"
bars_root = data_dir / "bars"
daily_bot_dir = bars_root / "daily"
min5_bot_dir = bars_root / "5min"

# Create dirs if missing
news_dir.mkdir(parents=True, exist_ok=True)
sentiment_dir.mkdir(parents=True, exist_ok=True)
reference_dir.mkdir(parents=True, exist_ok=True)
daily_bot_dir.mkdir(parents=True, exist_ok=True)
min5_bot_dir.mkdir(parents=True, exist_ok=True)

def persist_incremental_bars(df: pd.DataFrame, master_path: Path, timestamp_col: str = 'timestamp'):
    """
    Merges new bars into an existing master file for a symbol in the bot's data store.
    """
    if df.empty: return
    
    # Ensure current df has the expected timestamp col
    if timestamp_col not in df.columns:
        # Try to find a substitute (e.g. 'date' vs 'timestamp')
        alts = ['timestamp', 'date', 'datetime']
        found = False
        for a in alts:
            if a in df.columns:
                df = df.rename(columns={a: timestamp_col})
                found = True
                break
        if not found:
            log(f"Warning: No timestamp column found in incoming df for {master_path.name}")
            return

    if master_path.exists():
        try:
            existing_df = pd.read_parquet(master_path)
            # Schema Alignment: Ensure existing also uses the requested timestamp_col
            alts = ['timestamp', 'date', 'datetime']
            for a in alts:
                if a in existing_df.columns and a != timestamp_col:
                    existing_df = existing_df.rename(columns={a: timestamp_col})
            
            combined = pd.concat([existing_df, df]).drop_duplicates(subset=[timestamp_col])
            combined = combined.sort_values(timestamp_col)
            combined.to_parquet(master_path, index=False)
        except Exception as e:
            log(f"Warning: Failed to merge into {master_path.name}: {e}. Overwriting.")
            df.to_parquet(master_path, index=False)
    else:
        df.to_parquet(master_path, index=False)

# Load environment variables
from dotenv import load_dotenv
env_path = ORB_ROOT / "config" / ".env"
load_dotenv(env_path)

ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
SENTIMENT_THRESHOLD = 0.90
BATCH_SIZE = 32

def log(msg: str):
    print(f"[PIPELINE] {msg}", flush=True)

# -----------------------------------------------------------------------------
# 1. Universe Loading
# -----------------------------------------------------------------------------

def get_micro_universe() -> List[str]:
    """Load universe definition. For verified simulation, we use the full list."""
    # Try local reference first
    ref_path = reference_dir / "universe_micro_full.parquet"
    if ref_path.exists():
        df = pd.read_parquet(ref_path)
        return df['symbol'].unique().tolist()
    
    # Fallback to backtest data location if available (dev environment)
    backtest_universe = root_dir.parent / "data" / "backtest" / "orb" / "universe" / "universe_micro_full.parquet"
    if backtest_universe.exists():
        df = pd.read_parquet(backtest_universe)
        return df['symbol'].unique().tolist()
        
    log("WARNING: Universe file not found. Using hardcoded sample for safety.")
    return ['AN', 'GTLS', 'CUB', 'IMXI', 'TAOP', 'WKHS', 'UONE', 'ALF', 'CMTL', 'VVPR']

# -----------------------------------------------------------------------------
# 2. News Fetching
# -----------------------------------------------------------------------------

def fetch_fresh_news(symbols: List[str], target_date: datetime.date) -> Optional[pd.DataFrame]:
    """
    Fetch news for the Rolling 24H Window:
    Start: 09:30 ET on Previous Business Day
    End:   09:30 ET on Target Date
    """
    if not ALPACA_KEY or not ALPACA_SECRET:
        log("ERROR: Alpaca Credentials missing")
        return None

    client = NewsClient(ALPACA_KEY, ALPACA_SECRET)
    
    et_tz = pytz.timezone("America/New_York")
    
    # Determine window
    # Simple logic: Previous Day = Target - 1 (Need BDay logic for Mondays, but simple -1 works for most checks or we assume input is correct)
    # For strict Rolling 24H:
    target_dt = datetime.combine(target_date, dt_time(9, 30))
    target_0930 = et_tz.localize(target_dt)
    
    # 24 hours prior (approx business day)
    prev_0930 = target_0930 - timedelta(days=1)
    if target_date.weekday() == 0: # If Monday, look back to Friday? 
        # Strategy says "Rolling 24H". 
        # Actually backtest used simple 24h clock usually, but let's stick to 24-48h to be safe.
        # Fetching 72h for Monday ensures we catch Friday news.
        prev_0930 = target_0930 - timedelta(days=3)
        
    start_utc = prev_0930.astimezone(pytz.UTC)
    end_utc = target_0930.astimezone(pytz.UTC)
    
    log(f"Fetching news from {start_utc} to {end_utc} for {len(symbols)} symbols...")
    
    all_items = []
    chunk_size = 50
    
    def _extract_items(response):
        if isinstance(response, list):
            return response
        if hasattr(response, "news"):
            return response.news
        if hasattr(response, "data"):
             return response.data.get("news", []) if isinstance(response.data, dict) else response.data
        return []

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        symbols_str = ",".join(chunk)
        
        # Time-based pagination
        current_end = end_utc
        while True:
            try:
                req = NewsRequest(
                    symbols=symbols_str,
                    start=start_utc,
                    end=current_end,
                    limit=50,
                    sort="DESC"
                )
                res = client.get_news(req)
                items = _extract_items(res)
                
                if not items:
                    break
                    
                all_items.extend(items)
                
                # Use oldest timestamp in batch to set next current_end
                timestamps = [pd.to_datetime(n.created_at, utc=True) for n in items]
                oldest_time = min(timestamps)
                
                # If we got fewer than limit, or we've reached start_utc, we are done with this chunk
                if len(items) < 50 or oldest_time <= start_utc:
                    break
                    
                # Subtract 1 microsecond to avoid duplicates at the boundary
                current_end = oldest_time - timedelta(microseconds=1)
                
            except Exception as e:
                log(f"Error fetching chunk {i}: {e}")
                break
                
        time_module.sleep(0.1)
            
    if not all_items:
        log("No news found.")
        return None
        
    # Parse
    rows = []
    for item in all_items:
        # Alpaca news object
        # item.symbols is list
        # Filter again to be sure
        related = [s for s in item.symbols if s in symbols]
        for s in related:
            rows.append({
                'symbol': s,
                'timestamp': item.created_at,
                'headline': item.headline,
                'summary': item.summary,
                'url': item.url
            })
            
    df = pd.DataFrame(rows)
    if df.empty:
        return None
        
    log(f"Fetched {len(df)} raw news items")
    return df

# -----------------------------------------------------------------------------
# 3. Sentiment Scoring
# -----------------------------------------------------------------------------

def score_news(df: pd.DataFrame) -> pd.DataFrame:
    log("Loading FinBERT for scoring...")
    tokenizer = BertTokenizer.from_pretrained("ProsusAI/finbert")
    model = BertForSequenceClassification.from_pretrained("ProsusAI/finbert")
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    
    headlines = df['headline'].unique().tolist()
    log(f"Scoring {len(headlines)} unique headlines...")
    
    score_map = {}
    
    with torch.no_grad():
        for i in range(0, len(headlines), BATCH_SIZE):
            batch = headlines[i:i+BATCH_SIZE]
            inputs = tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt").to(device)
            outputs = model(**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
            # Extract positive score (index 0 for ProsusAI/finbert)
            pos_scores = probs[:, 0].cpu().numpy()
            
            for h, s in zip(batch, pos_scores):
                score_map[h] = float(s)
                
    df['positive_score'] = df['headline'].map(score_map)
    return df

# -----------------------------------------------------------------------------
# 4. Filter & Attribute
# -----------------------------------------------------------------------------

def process_candidates(df: pd.DataFrame, target_date: datetime.date) -> pd.DataFrame:
    """
    Filter for > 0.90 sentiment.
    Attribtue to target_date (already implicit by fetch window, but verify).
    Aggregate max score per symbol.
    """
    # Filter
    high_conviction = df[df['positive_score'] > SENTIMENT_THRESHOLD].copy()
    
    if high_conviction.empty:
        return pd.DataFrame()
        
    # Aggregate
    agg = high_conviction.groupby('symbol').agg({
        'positive_score': 'max',
        'headline': 'first',
        'timestamp': 'first'
    }).reset_index()
    
    # Add metadata
    agg['trade_date'] = target_date
    
    # Placeholder for Enriched Data (ATR, RvOL)
    # In a full live/verify pipeline, we would fetch price history here to calculate ATR/RVOL.
    # For now, we assume if it has news, it's a candidate, and the broker/sim execution 
    # will handle the technical filters (or we rely on the universe having them).
    # Since main.py expects ATR/OR_HIGH etc, we need to add them or main.py must calculate them.
    # *CRITICAL UPDATE*: main.py verify logic currently *loads* local enriched files which have these pre-calced.
    # If we want "Fresh", we must calculate ATR/RVol from fresh bars too.
    # To keep this feasible: We will return the *Sentiment Candidates*.
    # main.py execution loop will calculate OR levels dynamically from the stream/sim-stream.
    # But ATR/AvgVol are needed for Filtering (ATR > 0.5).
    # We will fetch Daily bars for these candidates to fill that data.
    return agg

def fetch_opening_bars(symbols: List[str], target_date: datetime.date) -> pd.DataFrame:
    """
    Fetch the Opening Range bar (09:30-09:35) for a list of symbols from Alpaca.
    Returns a DataFrame with [symbol, open, high, low, close, volume]
    """
    if not ALPACA_KEY or not ALPACA_SECRET:
        log("ERROR: Alpaca Credentials missing")
        return pd.DataFrame()

    client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
    
    et_tz = pytz.timezone("America/New_York")
    # Fetch from 09:30 to 09:36 to ensure we catch the full 5-min candle
    start_dt = et_tz.localize(datetime.combine(target_date, dt_time(9, 30)))
    end_dt   = et_tz.localize(datetime.combine(target_date, dt_time(9, 36)))
    
    log(f"Fetching 5-min OR bars for {len(symbols)} symbols...")
    
    request_params = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start_dt,
        end=end_dt,
        adjustment='raw'
    )
    
    try:
        bars = client.get_stock_bars(request_params)
        df = bars.df
        if df.empty:
            return pd.DataFrame()
            
        # The index is (symbol, timestamp). We want the bar that starts at 09:30.
        df = df.reset_index()
        # Filter for the 09:30 bar specifically
        df['time'] = df['timestamp'].dt.tz_convert('America/New_York').dt.time
        or_df = df[df['time'] == dt_time(9, 30)].copy()
        
        return or_df
    except Exception as e:
        log(f"ERROR fetching bars: {e}")
        return pd.DataFrame()

def fetch_technical_metrics(symbols: List[str], target_date: datetime.date) -> pd.DataFrame:
    """
    Fetch daily bars for the last 30 days to calculate ATR_14 and AvgVolume_14.
    Returns DataFrame with [symbol, atr_14, avg_volume_14]
    """
    if not symbols:
        return pd.DataFrame()
        
    if not ALPACA_KEY or not ALPACA_SECRET:
        log("ERROR: Alpaca Credentials missing for technical fetch")
        return pd.DataFrame()

    client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
    
    # We need at least 14 trading days. 30 calendar days is plenty.
    start_dt = target_date - timedelta(days=35) # Buffer for holidays
    end_dt   = target_date - timedelta(days=1)  # Up to yesterday
    
    log(f"Fetching historical daily bars for {len(symbols)} candidates...")
    
    request_params = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start_dt,
        end=end_dt,
        adjustment='split' # Splits are important for ATR/Volume
    )
    
    try:
        bars = client.get_stock_bars(request_params)
        df = bars.df.reset_index()
        if df.empty:
            return pd.DataFrame()
            
        # PERSIST FRESH DAILY BARS FOR AUDIT
        # Aligning with User Request: Single file per ticker in bot's data store
        for symbol, group in df.groupby('symbol'):
            master_file = daily_bot_dir / f"{symbol}.parquet"
            # Alpaca daily bars use 'timestamp'
            persist_incremental_bars(group, master_file, timestamp_col='timestamp')
            
        results = []
        for symbol, group in df.groupby('symbol'):
            group = group.sort_values('timestamp')
            if len(group) < 14:
                log(f"Warning: {symbol} has only {len(group)} daily bars. Metrics might be inaccurate.")
            
            # ATR-14
            high = group['high']
            low = group['low']
            close = group['close'].shift(1)
            tr1 = high - low
            tr2 = (high - close).abs()
            tr3 = (low - close).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr_14 = tr.rolling(window=14).mean().iloc[-1]
            
            # AvgVolume-14
            avg_vol_14 = group['volume'].rolling(window=14).mean().iloc[-1]
            
            results.append({
                'symbol': symbol,
                'atr_14': float(atr_14) if not pd.isna(atr_14) else 0.0,
                'avg_volume_14': float(avg_vol_14) if not pd.isna(avg_vol_14) else 0.0
            })
            
        return pd.DataFrame(results)
    except Exception as e:
        log(f"ERROR fetching technical bars: {e}")
        return pd.DataFrame()

def run_pipeline(target_date: datetime.date) -> pd.DataFrame:
    """
    Orchestrates the pipeline for a specific date.
    Returns dataframe of qualified candidates [symbol, trade_date, positive_score, headline, atr_14, avg_volume_14]
    """
    log(f"Running Live Pipeline for {target_date}")
    
    # 1. Load Universe
    symbols = get_micro_universe()
    
    # 2. Fetch News (Fresh)
    news_df = fetch_fresh_news(symbols, target_date)
    if news_df is None:
        log("No news found for window.")
        return pd.DataFrame()
    
    # PERSIST RAW NEWS
    news_file = news_dir / f"news_{target_date}.parquet"
    news_df.to_parquet(news_file)
    log(f"Raw news persisted to {news_file}")
        
    # 3. Score (Fresh)
    scored_df = score_news(news_df)
    
    # 4. Filter Candidates based on Sentiment
    candidates = process_candidates(scored_df, target_date)
    if candidates.empty:
        return candidates
        
    # 5. FETCH FRESH TECHNICALS (ATR/VOLUME)
    # This addresses the user request to ensure metrics are accurate.
    tech_metrics = fetch_technical_metrics(candidates['symbol'].tolist(), target_date)
    
    if not tech_metrics.empty:
        # Merge metrics into candidates
        candidates = pd.merge(candidates, tech_metrics, on='symbol', how='left')
        # Fill nans for those that failed fetch
        candidates['atr_14'] = candidates['atr_14'].fillna(0.0)
        candidates['avg_volume_14'] = candidates['avg_volume_14'].fillna(0.0)
    else:
        candidates['atr_14'] = 0.0
        candidates['avg_volume_14'] = 0.0

    # PERSIST ENRICHED CANDIDATES (Researcher Standard)
    # This ensures main.py has the ATR/Vol it needs
    sentiment_file = sentiment_dir / f"daily_{target_date}.parquet"
    candidates.to_parquet(sentiment_file)
    log(f"Enriched sentiment persisted to {sentiment_file}")

    log(f"Pipeline finished. Found {len(candidates)} candidates with fresh technicals.")
    return candidates
