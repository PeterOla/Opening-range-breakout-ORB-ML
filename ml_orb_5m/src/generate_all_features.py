"""
Generate ALL features (Price Action, Volume, Volatility, Temporal) for all trades.
Optimized with preloading to avoid repeated I/O.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from tqdm import tqdm

# Import feature extractors
from ml_orb_5m.src.features.price_action import (
    calculate_or_metrics,
    calculate_gap_features,
    detect_candlestick_patterns,
    calculate_momentum_indicators,
    calculate_price_levels
)
from ml_orb_5m.src.features.volume_liquidity import (
    calculate_volume_metrics,
    calculate_liquidity_proxies
)
from ml_orb_5m.src.features.volatility import (
    calculate_volatility_metrics
)
from ml_orb_5m.src.features.temporal import (
    calculate_temporal_metrics
)
from ml_orb_5m.src.features.market_context import (
    calculate_market_context
)

# Paths
TRADES_PATH = Path(__file__).parent.parent.parent / "orb_5m" / "results" / "results_combined_top50" / "all_trades.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "features" / "all_features.parquet"
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "processed"
EXTERNAL_DATA_DIR = Path(__file__).parent.parent / "data" / "external"

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

def load_market_data(external_dir):
    """Load SPY, QQQ, VIX data"""
    spy_df = pd.DataFrame()
    qqq_df = pd.DataFrame()
    vix_df = pd.DataFrame()
    
    try:
        if (external_dir / "spy_daily.parquet").exists():
            spy_df = pd.read_parquet(external_dir / "spy_daily.parquet")
            if 'date' not in spy_df.columns: spy_df['date'] = pd.to_datetime(spy_df['date']).dt.date
            
        if (external_dir / "qqq_daily.parquet").exists():
            qqq_df = pd.read_parquet(external_dir / "qqq_daily.parquet")
            if 'date' not in qqq_df.columns: qqq_df['date'] = pd.to_datetime(qqq_df['date']).dt.date

        if (external_dir / "vix_daily.parquet").exists():
            vix_df = pd.read_parquet(external_dir / "vix_daily.parquet")
            if 'date' not in vix_df.columns: vix_df['date'] = pd.to_datetime(vix_df['date']).dt.date
            
        print(f"Loaded Market Data: SPY={len(spy_df)}, QQQ={len(qqq_df)}, VIX={len(vix_df)}")
    except Exception as e:
        print(f"Error loading market data: {e}")
        
    return spy_df, qqq_df, vix_df


def extract_all_features(symbol, date, bars_5m_dict, bars_daily_dict, spy_df, qqq_df, vix_df):
    """Extract ALL features using preloaded data"""
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
    
    # Get daily bars for historical context
    bars_daily_prev = pd.DataFrame()
    if symbol in bars_daily_dict:
        bars_daily = bars_daily_dict[symbol]
        bars_daily_prev = bars_daily[bars_daily['date'] < target_date].copy()
    
    # Initialize features dictionary
    features = {}
    
    # --- CATEGORY 1: PRICE ACTION ---
    # 1. Opening range metrics
    features.update(calculate_or_metrics(bars_today))
    
    # 2. Gap features
    features.update(calculate_gap_features(bars_today, prev_day_close))
    
    # 3. Candlestick patterns
    features.update(detect_candlestick_patterns(bars_today))
    
    # 4. Momentum indicators (OR bars only)
    or_bars = bars_today[
        (bars_today['timestamp'].dt.time >= pd.to_datetime("09:30").time()) &
        (bars_today['timestamp'].dt.time < pd.to_datetime("09:35").time())
    ].copy()
    features.update(calculate_momentum_indicators(or_bars))
    
    # 5. Price levels
    features.update(calculate_price_levels(bars_today, prev_day_high, prev_day_low))
    
    # --- CATEGORY 2: VOLUME & LIQUIDITY ---
    features.update(calculate_volume_metrics(bars_today, bars_daily_prev))
    features.update(calculate_liquidity_proxies(bars_today))
    
    # --- CATEGORY 3: VOLATILITY ---
    features.update(calculate_volatility_metrics(bars_today, bars_daily_prev))
    
    # --- CATEGORY 4: MARKET CONTEXT ---
    features.update(calculate_market_context(str(target_date), spy_df, qqq_df, vix_df))
    
    # --- CATEGORY 5: TEMPORAL ---
    features.update(calculate_temporal_metrics(str(target_date)))
    
    return features


def main():
    print("=" * 80)
    print("GENERATING ALL FEATURES (Price, Volume, Volatility, Market Context, Temporal)")
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
    
    # Load Market Data
    spy_df, qqq_df, vix_df = load_market_data(EXTERNAL_DATA_DIR)
    
    # Extract features for all trades
    print("\nExtracting features...")
    all_features = []
    errors = []
    
    for idx, row in tqdm(trades.iterrows(), total=len(trades), desc="Processing trades"):
        try:
            features = extract_all_features(
                row['symbol'], 
                row['date'], 
                bars_5m_dict, 
                bars_daily_dict,
                spy_df,
                qqq_df,
                vix_df
            )
            
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
    
    # Save to parquet
    print(f"\nSaving to: {OUTPUT_PATH}")
    df.to_parquet(OUTPUT_PATH, compression='snappy', index=False)
    print("Done!")


if __name__ == "__main__":
    main()
