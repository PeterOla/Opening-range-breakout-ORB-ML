"""
Category 3: Volatility Features

Extract volatility-based features to assess breakout validity and risk.
CRITICAL: All features must use data available BEFORE trade entry.
"""
import pandas as pd
import numpy as np
from pathlib import Path

def calculate_volatility_metrics(bars_5min, bars_daily_prev, or_start="09:30", or_end="09:35"):
    """
    Calculate volatility metrics.
    """
    # Filter to opening range
    or_bars = bars_5min[
        (bars_5min['timestamp'].dt.time >= pd.to_datetime(or_start).time()) &
        (bars_5min['timestamp'].dt.time < pd.to_datetime(or_end).time())
    ].copy()
    
    if or_bars.empty:
        return {}
    
    features = {}
    
    # 1. ATR (Daily) - Already in price_action, but useful to have access here if needed
    # We will calculate ATR Ratio: Intraday Range / Daily ATR
    
    atr_14 = None
    if not bars_daily_prev.empty and len(bars_daily_prev) >= 14:
        # Calculate True Range for daily bars
        df = bars_daily_prev.tail(15).copy() # Need 15 to get 14 diffs if using close-close, but TR uses H-L
        # Standard TR calculation
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        atr_14 = df['tr'].tail(14).mean()
        
        features['atr_14_daily'] = atr_14
        
        # Intraday Range vs ATR
        # How "stretched" is the opening range compared to normal daily volatility?
        or_range = or_bars['high'].max() - or_bars['low'].min()
        features['or_range_vs_daily_atr'] = or_range / (atr_14 + 1e-8)
        
        # Volatility Trend (ATR 5d vs ATR 20d)
        if len(bars_daily_prev) >= 20:
            atr_5 = df['tr'].tail(5).mean()
            atr_20 = df['tr'].tail(20).mean()
            features['volatility_trend_5d_20d'] = atr_5 / (atr_20 + 1e-8)

    # 2. Intraday Volatility (Parkinson's Number estimate on OR)
    # Estimate vol from High-Low range
    # V = sqrt(1 / (4 * ln(2))) * ln(High / Low)
    # We'll just use ln(High/Low) as a proxy for range volatility
    high = or_bars['high'].max()
    low = or_bars['low'].min()
    if low > 0:
        features['or_log_range_vol'] = np.log(high / low)
        
    return features

def extract_volatility_features(symbol, date, data_dir="../../../data/processed"):
    """
    Master function to extract volatility features.
    """
    data_path = Path(data_dir)
    
    # Load 5-min bars
    bars_5min_path = data_path / "5min" / f"{symbol}.parquet"
    if not bars_5min_path.exists():
        return {}
    
    bars_5min_all = pd.read_parquet(bars_5min_path)
    if 'date' not in bars_5min_all.columns:
        bars_5min_all['date'] = bars_5min_all['timestamp'].dt.date
        
    target_date = pd.to_datetime(date).date()
    bars_today = bars_5min_all[bars_5min_all['date'] == target_date].copy()
    
    if bars_today.empty:
        return {}
        
    # Load daily bars
    bars_daily_path = data_path / "daily" / f"{symbol}.parquet"
    bars_daily_prev = pd.DataFrame()
    
    if bars_daily_path.exists():
        bars_daily = pd.read_parquet(bars_daily_path)
        if 'date' not in bars_daily.columns:
             bars_daily['date'] = pd.to_datetime(bars_daily['date']).dt.date
        
        bars_daily_prev = bars_daily[bars_daily['date'] < target_date]
    
    features = {}
    
    vol_metrics = calculate_volatility_metrics(bars_today, bars_daily_prev)
    features.update(vol_metrics)
    
    return features
