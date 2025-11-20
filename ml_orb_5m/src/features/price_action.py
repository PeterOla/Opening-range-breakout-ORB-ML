"""
Category 1: Price Action Features

Extract price-based features from opening range and intraday patterns.
"""
import pandas as pd
import numpy as np
from pathlib import Path


def calculate_or_metrics(bars_5min, or_start="09:30", or_end="09:35"):
    """
    Calculate opening range metrics from 5-min bars.
    
    Args:
        bars_5min: DataFrame with timestamp, open, high, low, close, volume
        or_start: Opening range start time (default 09:30)
        or_end: Opening range end time (default 09:35)
    
    Returns:
        dict of OR features
    """
    # Filter to opening range (9:30-9:35)
    or_bars = bars_5min[
        (bars_5min['timestamp'].dt.time >= pd.to_datetime(or_start).time()) &
        (bars_5min['timestamp'].dt.time < pd.to_datetime(or_end).time())
    ].copy()
    
    if or_bars.empty:
        return {}
    
    # Get first bar (opening range candle)
    first_bar = or_bars.iloc[0]
    
    features = {
        # Basic OR levels (already in trades CSV, but recalculate for validation)
        'or_open': first_bar['open'],
        'or_high': or_bars['high'].max(),
        'or_low': or_bars['low'].min(),
        'or_close': or_bars.iloc[-1]['close'],
        'or_volume': or_bars['volume'].sum(),
        
        # OR range metrics
        'or_range_size': or_bars['high'].max() - or_bars['low'].min(),
        'or_range_pct': (or_bars['high'].max() - or_bars['low'].min()) / or_bars['low'].min(),
        
        # First candle direction & strength
        'or_close_vs_open': (or_bars.iloc[-1]['close'] - first_bar['open']) / first_bar['open'],
        'or_body_size': abs(or_bars.iloc[-1]['close'] - first_bar['open']),
        'or_body_pct': abs(or_bars.iloc[-1]['close'] - first_bar['open']) / (or_bars['high'].max() - or_bars['low'].min() + 1e-8),
        
        # Shadows (wicks)
        'or_upper_shadow': or_bars['high'].max() - max(first_bar['open'], or_bars.iloc[-1]['close']),
        'or_lower_shadow': min(first_bar['open'], or_bars.iloc[-1]['close']) - or_bars['low'].min(),
        'or_upper_shadow_pct': (or_bars['high'].max() - max(first_bar['open'], or_bars.iloc[-1]['close'])) / (or_bars['high'].max() - or_bars['low'].min() + 1e-8),
        'or_lower_shadow_pct': (min(first_bar['open'], or_bars.iloc[-1]['close']) - or_bars['low'].min()) / (or_bars['high'].max() - or_bars['low'].min() + 1e-8),
    }
    
    return features


def calculate_gap_features(bars_5min, prev_day_close):
    """
    Calculate gap features (overnight gap from previous close).
    
    Args:
        bars_5min: DataFrame with 5-min bars for current day
        prev_day_close: Previous day's closing price
    
    Returns:
        dict of gap features
    """
    if bars_5min.empty or prev_day_close is None:
        return {}
    
    open_price = bars_5min.iloc[0]['open']
    
    gap = open_price - prev_day_close
    gap_pct = gap / prev_day_close
    
    # Check if gap filled within opening range
    or_bars = bars_5min.iloc[:1]  # First 5-min bar
    gap_filled = False
    if gap > 0:  # Gap up
        gap_filled = or_bars['low'].min() <= prev_day_close
    elif gap < 0:  # Gap down
        gap_filled = or_bars['high'].max() >= prev_day_close
    
    features = {
        'overnight_gap': gap,
        'gap_pct': gap_pct,
        'gap_direction': np.sign(gap),  # 1 (up), 0 (none), -1 (down)
        'gap_filled_by_or': int(gap_filled),
    }
    
    return features


def detect_candlestick_patterns(bars_5min):
    """
    Detect common candlestick patterns in opening range.
    
    Args:
        bars_5min: First bar(s) of the day
    
    Returns:
        dict of pattern flags
    """
    if bars_5min.empty:
        return {}
    
    first_bar = bars_5min.iloc[0]
    o, h, l, c = first_bar['open'], first_bar['high'], first_bar['low'], first_bar['close']
    
    body = abs(c - o)
    range_size = h - l
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l
    
    features = {
        # Doji: small body relative to range
        'is_doji': int(body < 0.001 * range_size) if range_size > 0 else 0,
        
        # Hammer: small body at top, long lower shadow
        'is_hammer': int(lower_shadow > 2 * body and upper_shadow < 0.1 * range_size) if range_size > 0 else 0,
        
        # Shooting star: small body at bottom, long upper shadow
        'is_shooting_star': int(upper_shadow > 2 * body and lower_shadow < 0.1 * range_size) if range_size > 0 else 0,
        
        # Marubozu: almost no shadows (strong directional move)
        'is_marubozu': int((upper_shadow + lower_shadow) < 0.1 * range_size) if range_size > 0 else 0,
    }
    
    return features


def calculate_momentum_indicators(bars_5min, period=14):
    """
    Calculate early-session momentum indicators.
    
    Args:
        bars_5min: First few bars of the session
        period: Lookback period for indicators
    
    Returns:
        dict of momentum features
    """
    if len(bars_5min) < 2:
        return {}
    
    # Rate of change (first 5 min)
    roc_5min = (bars_5min.iloc[0]['close'] - bars_5min.iloc[0]['open']) / bars_5min.iloc[0]['open']
    
    # Simple RSI approximation (if we have enough bars)
    if len(bars_5min) >= period:
        closes = bars_5min['close'].values
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        else:
            rsi = 100
    else:
        rsi = 50  # Neutral default
    
    features = {
        'roc_5min': roc_5min,
        'rsi_5min': rsi,
    }
    
    return features


def calculate_price_levels(bars_5min, prev_day_high, prev_day_low):
    """
    Calculate distance to key price levels.
    
    Args:
        bars_5min: Current day's bars
        prev_day_high: Previous day's high
        prev_day_low: Previous day's low
    
    Returns:
        dict of price level features
    """
    if bars_5min.empty:
        return {}
    
    current_price = bars_5min.iloc[0]['close']
    
    features = {}
    
    if prev_day_high is not None:
        features['distance_to_prev_high'] = (current_price - prev_day_high) / prev_day_high
    
    if prev_day_low is not None:
        features['distance_to_prev_low'] = (current_price - prev_day_low) / prev_day_low
    
    return features


def extract_price_action_features(symbol, date, data_dir="../../../data/processed"):
    """
    Master function to extract all price action features for a given symbol/date.
    
    Args:
        symbol: Stock ticker
        date: Trading date (YYYY-MM-DD or datetime)
        data_dir: Path to data directory
    
    Returns:
        dict of all price action features
    """
    data_path = Path(data_dir)
    
    # Load 5-min bars for the symbol
    bars_5min_path = data_path / "5min" / f"{symbol}.parquet"
    if not bars_5min_path.exists():
        return {}
    
    bars_5min_all = pd.read_parquet(bars_5min_path)
    # Timestamp is already timezone-aware datetime
    bars_5min_all['date'] = bars_5min_all['timestamp'].dt.date
    
    # Filter to specific date
    target_date = pd.to_datetime(date).date()
    bars_today = bars_5min_all[bars_5min_all['date'] == target_date].copy()
    
    if bars_today.empty:
        return {}
    
    # Get previous day's data for gap calculation
    bars_prev = bars_5min_all[bars_5min_all['date'] < target_date].copy()
    prev_day_close = bars_prev.iloc[-1]['close'] if not bars_prev.empty else None
    prev_day_high = bars_prev.groupby('date')['high'].max().iloc[-1] if not bars_prev.empty else None
    prev_day_low = bars_prev.groupby('date')['low'].min().iloc[-1] if not bars_prev.empty else None
    
    # Load daily bars for ATR
    bars_daily_path = data_path / "daily" / f"{symbol}.parquet"
    atr_14 = None
    if bars_daily_path.exists():
        bars_daily = pd.read_parquet(bars_daily_path)
        # Daily files use 'date' column, convert to date type
        bars_daily['date'] = pd.to_datetime(bars_daily['date']).dt.date
        bars_daily_prev = bars_daily[bars_daily['date'] < target_date]
        
        if len(bars_daily_prev) >= 14:
            # Calculate ATR
            bars_daily_prev = bars_daily_prev.tail(14).copy()
            bars_daily_prev['tr'] = bars_daily_prev.apply(
                lambda row: max(
                    row['high'] - row['low'],
                    abs(row['high'] - row['close']),
                    abs(row['low'] - row['close'])
                ),
                axis=1
            )
            atr_14 = bars_daily_prev['tr'].mean()
    
    # Extract features from different categories
    features = {}
    
    # 1. Opening range metrics
    or_features = calculate_or_metrics(bars_today)
    features.update(or_features)
    
    # 2. Gap features
    gap_features = calculate_gap_features(bars_today, prev_day_close)
    features.update(gap_features)
    
    # 3. Candlestick patterns
    pattern_features = detect_candlestick_patterns(bars_today)
    features.update(pattern_features)
    
    # 4. Momentum indicators - USE ONLY OR BARS TO AVOID LOOKAHEAD
    # Filter to opening range only (09:30-09:35)
    or_bars = bars_today[
        (bars_today['timestamp'].dt.time >= pd.to_datetime("09:30").time()) &
        (bars_today['timestamp'].dt.time < pd.to_datetime("09:35").time())
    ].copy()
    momentum_features = calculate_momentum_indicators(or_bars)
    features.update(momentum_features)
    
    # 5. Price levels
    level_features = calculate_price_levels(bars_today, prev_day_high, prev_day_low)
    features.update(level_features)
    
    # 6. Add ATR-normalized features
    if atr_14 is not None and 'or_range_size' in features:
        features['or_range_vs_atr'] = features['or_range_size'] / atr_14
        features['atr_14'] = atr_14
        
        if 'overnight_gap' in features:
            features['gap_vs_atr'] = abs(features['overnight_gap']) / atr_14
    
    return features


if __name__ == "__main__":
    # Test on a sample trade
    print("Testing price action feature extraction...")
    
    # Example: AAME on 2021-02-05
    features = extract_price_action_features("AAME", "2021-02-05")
    
    print("\nExtracted features:")
    for key, value in sorted(features.items()):
        print(f"  {key}: {value:.6f}" if isinstance(value, float) else f"  {key}: {value}")
