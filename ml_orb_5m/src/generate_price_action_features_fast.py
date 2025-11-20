"""
Generate price action features for all trades (OPTIMIZED VERSION)
Preloads all parquet files to avoid repeated I/O
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
from tqdm import tqdm
from ml_orb_5m.src.features.price_action import (
    calculate_or_metrics,
    calculate_gap_features,
    detect_candlestick_patterns,
    calculate_momentum_indicators,
    calculate_price_levels
)

# Paths
TRADES_PATH = Path(__file__).parent.parent.parent / "orb_5m" / "results" / "results_combined_top20" / "all_trades.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "features" / "price_action_features.parquet"
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "processed"

# Ensure output directory exists
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def preload_data(symbols, data_dir):
    """Preload all parquet files into memory"""
    bars_5m_dict = {}
    bars_daily_dict = {}
    
    print(f"\nPreloading data for {len(symbols)} symbols...")
    for symbol in tqdm(symbols, desc="Loading parquet files"):
        # Load 5min bars
        path_5m = data_dir / "5min" / f"{symbol}.parquet"
        if path_5m.exists():
            df5m = pd.read_parquet(path_5m)
            df5m['date'] = df5m['timestamp'].dt.date
            bars_5m_dict[symbol] = df5m
        
        # Load daily bars
        path_daily = data_dir / "daily" / f"{symbol}.parquet"
        if path_daily.exists():
            df_daily = pd.read_parquet(path_daily)
            df_daily['date'] = pd.to_datetime(df_daily['date']).dt.date
            bars_daily_dict[symbol] = df_daily
    
    print(f"Loaded 5min data for {len(bars_5m_dict)} symbols")
    print(f"Loaded daily data for {len(bars_daily_dict)} symbols")
    
    return bars_5m_dict, bars_daily_dict


def extract_features_fast(symbol, date, bars_5m_dict, bars_daily_dict):
    """Extract features using preloaded data"""
    # Get data from preloaded dicts
    if symbol not in bars_5m_dict:
        return {}
    
    bars_5min_all = bars_5m_dict[symbol]
    
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
    
    # Calculate ATR from daily bars
    atr_14 = None
    if symbol in bars_daily_dict:
        bars_daily = bars_daily_dict[symbol]
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


def main():
    print("=" * 80)
    print("GENERATING PRICE ACTION FEATURES (OPTIMIZED)")
    print("=" * 80)
    
    # Load trades
    print(f"\nLoading trades from: {TRADES_PATH}")
    trades = pd.read_csv(TRADES_PATH, parse_dates=['date', 'entry_time', 'exit_time'])
    
    # Filter out trades with null symbols
    null_symbols = trades['symbol'].isnull().sum()
    if null_symbols > 0:
        print(f"Warning: Found {null_symbols} trades with null symbols, filtering them out...")
        trades = trades[trades['symbol'].notna()].copy()
    
    print(f"Loaded {len(trades):,} trades")
    
    # Get unique symbols
    unique_symbols = trades['symbol'].unique()
    
    # Preload all data
    bars_5m_dict, bars_daily_dict = preload_data(unique_symbols, DATA_DIR)
    
    # Extract features for all trades
    print("\nExtracting features...")
    all_features = []
    errors = []
    
    for idx, row in tqdm(trades.iterrows(), total=len(trades), desc="Processing trades"):
        try:
            features = extract_features_fast(row['symbol'], row['date'], bars_5m_dict, bars_daily_dict)
            
            if features:
                # Add trade identifiers and original columns
                features['symbol'] = row['symbol']
                features['date'] = row['date']
                features['entry_time'] = row['entry_time']
                features['exit_time'] = row['exit_time']
                features['entry_price'] = row['entry_price']
                features['exit_price'] = row['exit_price']
                features['shares'] = row['shares']
                features['net_pnl'] = row['net_pnl']
                
                all_features.append(features)
            else:
                errors.append((row['symbol'], row['date'], "No features returned"))
                
        except Exception as e:
            errors.append((row['symbol'], row['date'], str(e)))
    
    print(f"\nSuccessfully extracted features for {len(all_features):,} trades")
    print(f"Errors: {len(errors):,}")
    
    # Show first 20 errors if any
    if errors:
        print("\nFirst 20 errors:")
        for error in errors[:20]:
            if isinstance(error, tuple) and len(error) == 3:
                symbol, date, msg = error
                print(f"  {symbol} on {date}: {msg}")
            elif isinstance(error, dict):
                print(f"  {error.get('symbol', 'Unknown')} on {error.get('date', 'Unknown')}: {error.get('error', 'Unknown error')}")
            else:
                print(f"  {error}")
    
    # Early return if no features extracted
    if len(all_features) == 0:
        print("\nNo features extracted. Check errors above.")
        return
    
    # Convert to DataFrame
    print("\nConverting to DataFrame...")
    df = pd.DataFrame(all_features)
    
    # Add target label
    if 'target' in df.columns:
        print("Target column already exists")
    else:
        df['target'] = (df['net_pnl'] > 0).astype(int)
    
    # Summary
    print(f"\nFeature summary:")
    print(f"  Rows: {len(df):,}")
    print(f"  Columns: {len(df.columns):,}")
    print(f"  Winners: {df['target'].sum():,} ({df['target'].mean()*100:.2f}%)")
    
    # Show sample features
    feature_cols = [c for c in df.columns if c not in ['symbol', 'date', 'entry_time', 'exit_time', 
                                                         'entry_price', 'exit_price', 'shares', 
                                                         'net_pnl', 'target']]
    print(f"\nFeature columns ({len(feature_cols)}):")
    print(f"  {', '.join(feature_cols)}")
    
    print(f"\nDate range: {df['date'].min()} to {df['date'].max()}")
    
    # Save to parquet
    print(f"\nSaving to: {OUTPUT_PATH}")
    df.to_parquet(OUTPUT_PATH, compression='snappy', index=False)
    print("Done!")


if __name__ == "__main__":
    main()
