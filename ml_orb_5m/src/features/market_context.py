"""
Category 4: Market Context Features

Extract broad market context (SPY, QQQ, VIX) to assess regime.
CRITICAL: Use only data available before trade time.
Since we use daily bars for indices, we primarily use PREVIOUS DAY's data
or TODAY's OPEN (if available and reliable).
"""
import pandas as pd
import numpy as np
from pathlib import Path

def calculate_market_context(date, spy_df, qqq_df, vix_df):
    """
    Calculate market context features for a specific date.
    
    Args:
        date: Target trade date (str or datetime)
        spy_df: DataFrame of SPY daily data
        qqq_df: DataFrame of QQQ daily data
        vix_df: DataFrame of VIX daily data
        
    Returns:
        dict: Market context features
    """
    target_date = pd.to_datetime(date).date()
    features = {}
    
    # Helper to get previous day row
    def get_prev_day(df, current_date):
        prev_data = df[df['date'] < current_date]
        if prev_data.empty:
            return None
        return prev_data.iloc[-1]
    
    # Helper to get trend and SMA
    def get_trend_sma(df, current_date, prefix):
        prev_data = df[df['date'] < current_date].copy()
        if prev_data.empty:
            return {}
            
        last_row = prev_data.iloc[-1]
        prev_close = last_row['close']
        
        res = {}
        
        # 5-day Trend
        if len(prev_data) >= 6:
            close_5d = prev_data.iloc[-6]['close']
            res[f'{prefix}_trend_5d'] = (prev_close - close_5d) / close_5d
            
        # SMAs
        if len(prev_data) >= 50:
            sma_20 = prev_data['close'].tail(20).mean()
            sma_50 = prev_data['close'].tail(50).mean()
            
            res[f'{prefix}_above_sma20'] = 1 if prev_close > sma_20 else 0
            res[f'{prefix}_above_sma50'] = 1 if prev_close > sma_50 else 0
            res[f'{prefix}_dist_sma20'] = (prev_close - sma_20) / sma_20
            
        # Gap (Today Open vs Prev Close)
        # We need today's row for Open
        today_data = df[df['date'] == current_date]
        if not today_data.empty:
            today_open = today_data.iloc[0]['open']
            res[f'{prefix}_gap_pct'] = (today_open - prev_close) / prev_close
            
        return res

    # SPY Features
    if not spy_df.empty:
        features.update(get_trend_sma(spy_df, target_date, 'spy'))
        
    # QQQ Features
    if not qqq_df.empty:
        features.update(get_trend_sma(qqq_df, target_date, 'qqq'))
        
    # VIX Features
    if not vix_df.empty:
        vix_prev = get_prev_day(vix_df, target_date)
        if vix_prev is not None:
            vix_close = vix_prev['close']
            features['vix_level'] = vix_close
            
            # VIX Regime
            if vix_close < 15:
                features['vix_regime'] = 0 # Low
            elif vix_close < 25:
                features['vix_regime'] = 1 # Normal
            else:
                features['vix_regime'] = 2 # High
                
            # VIX Change (vs 5 days ago)
            prev_data = vix_df[vix_df['date'] < target_date]
            if len(prev_data) >= 6:
                vix_5d = prev_data.iloc[-6]['close']
                features['vix_change_5d'] = (vix_close - vix_5d) / vix_5d

    return features

def extract_market_context(date, data_dir="../../../data/external"):
    """
    Wrapper to load data and extract features.
    """
    data_path = Path(data_dir)
    
    # Load external data
    spy_df = pd.DataFrame()
    qqq_df = pd.DataFrame()
    vix_df = pd.DataFrame()
    
    if (data_path / "spy_daily.parquet").exists():
        spy_df = pd.read_parquet(data_path / "spy_daily.parquet")
        if 'date' not in spy_df.columns: spy_df['date'] = pd.to_datetime(spy_df['date']).dt.date
        
    if (data_path / "qqq_daily.parquet").exists():
        qqq_df = pd.read_parquet(data_path / "qqq_daily.parquet")
        if 'date' not in qqq_df.columns: qqq_df['date'] = pd.to_datetime(qqq_df['date']).dt.date

    if (data_path / "vix_daily.parquet").exists():
        vix_df = pd.read_parquet(data_path / "vix_daily.parquet")
        if 'date' not in vix_df.columns: vix_df['date'] = pd.to_datetime(vix_df['date']).dt.date
        
    return calculate_market_context(date, spy_df, qqq_df, vix_df)
