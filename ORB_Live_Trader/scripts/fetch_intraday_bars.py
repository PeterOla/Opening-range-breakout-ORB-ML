"""
Fetch 5-min intraday bars and calculate opening range metrics.
Retries 3x on failure per symbol, skips failed symbols and continues.

Run at 09:25 ET: python scripts/fetch_intraday_bars.py
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from typing import Optional, List
import pandas as pd
import time as time_module
import pytz

# Add parent backend to path
BACKEND_PATH = Path(__file__).parent.parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_PATH))

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
BARS_5MIN_DIR = DATA_DIR / "bars" / "5min"
SENTIMENT_DIR = DATA_DIR / "sentiment"
DAILY_DIR = DATA_DIR / "bars" / "daily"
LOG_DIR = Path(__file__).parent.parent / "logs" / "runs"

# Config
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
RETENTION_DAYS = 30

def log(message: str, level: str = "INFO"):
    """Terminal logger with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{level}] [FETCH_5MIN] {message}")
    sys.stdout.flush()

def get_today_candidates() -> List[str]:
    """Load today's sentiment candidates"""
    today = datetime.now().date()
    sentiment_path = SENTIMENT_DIR / f"daily_{today}.parquet"
    
    if not sentiment_path.exists():
        log(f"No sentiment file for {today}", level="ERROR")
        return []
    
    df = pd.read_parquet(sentiment_path)
    # Filter for today's trade_date
    today_df = df[df['trade_date'] == today]
    symbols = today_df['symbol'].unique().tolist()
    log(f"Loaded {len(symbols)} sentiment candidates for {today}")
    return symbols

def fetch_5min_bars_for_symbol(
    symbol: str,
    trade_date: datetime,
    max_retries: int = 3
) -> Optional[pd.DataFrame]:
    """Fetch 5-min bars for single symbol with retry"""
    
    client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
    et_tz = pytz.timezone("America/New_York")
    
    # Fetch pre-market + RTH (04:00-16:00 ET)
    start = et_tz.localize(datetime.combine(trade_date, dt_time(4, 0)))
    end = et_tz.localize(datetime.combine(trade_date, dt_time(16, 0)))
    
    for attempt in range(1, max_retries + 1):
        try:
            request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame.Minute,  # 1-min, then resample to 5-min
                start=start,
                end=end
            )
            
            bars = client.get_stock_bars(request)
            
            if bars.df.empty:
                log(f"{symbol}: No bars returned (attempt {attempt})", level="WARNING")
                if attempt < max_retries:
                    time_module.sleep(2 * 60)  # 2min backoff
                    continue
                return None
            
            df = bars.df.reset_index()
            df = df[df['symbol'] == symbol].copy()  # Safety filter
            
            # Resample 1-min to 5-min
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
            
            resampled = df.resample('5T').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            resampled = resampled.reset_index()
            resampled['symbol'] = symbol
            
            return resampled
            
        except Exception as e:
            log(f"{symbol}: Fetch failed (attempt {attempt}/{max_retries}): {e}", level="ERROR")
            
            if attempt < max_retries:
                time_module.sleep(2 * 60)  # 2min backoff
            else:
                return None
    
    return None

def calculate_opening_range(df: pd.DataFrame, daily_avg_volume: float) -> Optional[dict]:
    """Calculate OR metrics from FIRST 5-min bar at 09:30 ET (backtest-aligned)."""
    et_tz = pytz.timezone("America/New_York")

    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df['timestamp_et'] = df['timestamp'].dt.tz_convert(et_tz)
    df['time'] = df['timestamp_et'].dt.time

    or_start = dt_time(9, 30)
    or_end = dt_time(16, 0)

    # First try exact 09:30 bar
    or_row = df[df['time'] == or_start]

    if or_row.empty:
        # Fallback: first bar within regular trading hours
        rth = df[(df['time'] >= or_start) & (df['time'] <= or_end)].copy()
        if rth.empty:
            log("No regular-hours bars for OR calculation", level="WARNING")
            return None
        or_row = rth.iloc[0:1]

    r = or_row.iloc[0]
    or_open = float(r['open'])
    or_high = float(r['high'])
    or_low = float(r['low'])
    or_close = float(r['close'])
    or_volume = float(r['volume'])
    
    # RVOL calculation: (OR volume * 78) / avg_volume_14
    # 78 = 390 trading minutes / 5-min bars
    rvol = (or_volume * 78) / daily_avg_volume if daily_avg_volume > 0 else 0
    
    # Direction: 1 (bullish), -1 (bearish), 0 (flat)
    if or_close > or_open:
        direction = 1
    elif or_close < or_open:
        direction = -1
    else:
        direction = 0
    
    return {
        'or_open': or_open,
        'or_high': or_high,
        'or_low': or_low,
        'or_close': or_close,
        'or_volume': or_volume,
        'rvol': rvol,
        'direction': direction
    }

def get_daily_metrics(symbol: str, trade_date: datetime.date) -> Optional[dict]:
    """Load ATR and avg_volume from daily bars"""
    
    daily_path = DAILY_DIR / f"{trade_date}.parquet"
    
    if not daily_path.exists():
        log(f"No daily bars for {trade_date}", level="WARNING")
        return None
    
    df = pd.read_parquet(daily_path)
    row = df[df['symbol'] == symbol]
    
    if len(row) == 0:
        return None
    
    return {
        'atr_14': row.iloc[0]['atr_14'],
        'avg_volume_14': row.iloc[0]['avg_volume_14']
    }

def cleanup_old_folders(retention_days: int = 30):
    """Delete 5min folders older than retention period"""
    
    cutoff_date = datetime.now().date() - timedelta(days=retention_days)
    deleted_count = 0
    
    for folder in BARS_5MIN_DIR.glob("*"):
        if not folder.is_dir():
            continue
        
        try:
            folder_date = datetime.strptime(folder.name, "%Y-%m-%d").date()
            
            if folder_date < cutoff_date:
                for file in folder.glob("*.parquet"):
                    file.unlink()
                folder.rmdir()
                deleted_count += 1
                
        except (ValueError, OSError) as e:
            log(f"Skipping folder {folder.name}: {e}", level="WARNING")
    
    if deleted_count > 0:
        log(f"Deleted {deleted_count} old folders")

def main():
    """Main pipeline"""
    
    # Setup
    BARS_5MIN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now().date()
    today_folder = BARS_5MIN_DIR / str(today)
    today_folder.mkdir(exist_ok=True)
    
    log(f"Starting 5-min bar fetch for {today}")
    
    # Load candidates
    symbols = get_today_candidates()
    
    if len(symbols) == 0:
        log("No candidates to fetch - exiting", level="WARNING")
        sys.exit(0)
    
    # Fetch bars for each symbol
    successful = 0
    failed = []
    
    for i, symbol in enumerate(symbols):
        log(f"Fetching {symbol} ({i+1}/{len(symbols)})")
        
        # Get daily metrics
        daily_metrics = get_daily_metrics(symbol, today)
        
        if daily_metrics is None:
            log(f"{symbol}: No daily metrics available - skipping", level="WARNING")
            failed.append(symbol)
            continue
        
        # Fetch 5-min bars
        df = fetch_5min_bars_for_symbol(symbol, today)
        
        if df is None:
            log(f"{symbol}: Failed to fetch bars after retries - skipping", level="ERROR")
            failed.append(symbol)
            continue
        
        # Calculate OR metrics
        or_metrics = calculate_opening_range(df, daily_metrics['avg_volume_14'])
        
        if or_metrics is None:
            log(f"{symbol}: OR calculation failed - skipping", level="WARNING")
            failed.append(symbol)
            continue
        
        # Add metrics to dataframe
        for key, value in or_metrics.items():
            df[key] = value
        
        df['atr_14'] = daily_metrics['atr_14']
        df['avg_volume_14'] = daily_metrics['avg_volume_14']
        
        # Save
        output_path = today_folder / f"{symbol}.parquet"
        df.to_parquet(output_path, index=False)
        
        successful += 1
        log(f"{symbol}: Saved {len(df)} bars with OR metrics")
        
        time_module.sleep(0.2)  # Rate limiting
    
    # Summary
    log(f"Fetch complete: {successful} successful, {len(failed)} failed")
    
    if failed:
        log(f"Failed symbols: {', '.join(failed)}", level="WARNING")
    
    # Cleanup
    cleanup_old_folders(RETENTION_DAYS)
    
    log("5-min bar fetch completed")

if __name__ == "__main__":
    main()
