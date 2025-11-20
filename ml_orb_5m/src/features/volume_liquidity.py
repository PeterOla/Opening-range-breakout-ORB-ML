"""
Category 2: Volume & Liquidity Features

Extract volume-based features to assess execution quality and breakout strength.
CRITICAL: All features must use data available BEFORE trade entry (typically 09:35+).
We strictly use Opening Range (09:30-09:35) or prior daily data.
"""
import pandas as pd
import numpy as np
from pathlib import Path

def calculate_volume_metrics(bars_5min, bars_daily_prev, or_start="09:30", or_end="09:35"):
    """
    Calculate volume metrics using OR bars and previous daily data.
    
    Args:
        bars_5min: DataFrame with 5-min bars for current day
        bars_daily_prev: DataFrame with daily bars PRIOR to current day
        or_start: Opening range start time
        or_end: Opening range end time
        
    Returns:
        dict of volume features
    """
    # Filter to opening range (09:30-09:35)
    or_bars = bars_5min[
        (bars_5min['timestamp'].dt.time >= pd.to_datetime(or_start).time()) &
        (bars_5min['timestamp'].dt.time < pd.to_datetime(or_end).time())
    ].copy()
    
    if or_bars.empty:
        return {}
    
    or_volume = or_bars['volume'].sum()
    
    features = {
        'or_volume': or_volume,
    }
    
    # Relative Volume (RVOL) vs 14-day average
    # We calculate average volume of the *entire day* from previous days as a proxy for liquidity
    # Note: True intraday RVOL requires intraday history which is heavy to load.
    # We will use daily average volume as the baseline.
    
    if not bars_daily_prev.empty and len(bars_daily_prev) >= 14:
        avg_daily_vol_14 = bars_daily_prev['volume'].tail(14).mean()
        
        # OR volume as % of average daily volume
        # High value means heavy early activity
        features['or_vol_vs_avg_daily'] = or_volume / (avg_daily_vol_14 + 1e-8)
        
        # Dollar volume estimate (Liquidity proxy)
        # Avg Daily Vol * Avg Close
        avg_price = bars_daily_prev['close'].tail(14).mean()
        features['avg_dollar_volume_14d'] = avg_daily_vol_14 * avg_price
    
    return features

def calculate_liquidity_proxies(bars_5min, or_start="09:30", or_end="09:35"):
    """
    Calculate liquidity proxies from intraday data.
    """
    or_bars = bars_5min[
        (bars_5min['timestamp'].dt.time >= pd.to_datetime(or_start).time()) &
        (bars_5min['timestamp'].dt.time < pd.to_datetime(or_end).time())
    ].copy()
    
    if or_bars.empty:
        return {}
    
    # Spread estimate (High - Low) / Close
    # Wider spread relative to price often implies lower liquidity
    avg_spread_pct = ((or_bars['high'] - or_bars['low']) / or_bars['close']).mean()
    
    # Volume per minute in OR
    vol_per_min = or_bars['volume'].sum() / 5.0
    
    features = {
        'or_spread_pct': avg_spread_pct,
        'or_vol_per_min': vol_per_min
    }
    
    return features

def extract_volume_features(symbol, date, data_dir="../../../data/processed"):
    """
    Master function to extract volume/liquidity features.
    """
    data_path = Path(data_dir)
    
    # Load 5-min bars
    bars_5min_path = data_path / "5min" / f"{symbol}.parquet"
    if not bars_5min_path.exists():
        return {}
    
    bars_5min_all = pd.read_parquet(bars_5min_path)
    # Ensure date column exists
    if 'date' not in bars_5min_all.columns:
        bars_5min_all['date'] = bars_5min_all['timestamp'].dt.date
        
    target_date = pd.to_datetime(date).date()
    bars_today = bars_5min_all[bars_5min_all['date'] == target_date].copy()
    
    if bars_today.empty:
        return {}
        
    # Load daily bars for historical averages
    bars_daily_path = data_path / "daily" / f"{symbol}.parquet"
    bars_daily_prev = pd.DataFrame()
    
    if bars_daily_path.exists():
        bars_daily = pd.read_parquet(bars_daily_path)
        if 'date' not in bars_daily.columns:
             bars_daily['date'] = pd.to_datetime(bars_daily['date']).dt.date
        
        bars_daily_prev = bars_daily[bars_daily['date'] < target_date]
    
    features = {}
    
    # 1. Volume Metrics
    vol_metrics = calculate_volume_metrics(bars_today, bars_daily_prev)
    features.update(vol_metrics)
    
    # 2. Liquidity Proxies
    liq_proxies = calculate_liquidity_proxies(bars_today)
    features.update(liq_proxies)
    
    return features
