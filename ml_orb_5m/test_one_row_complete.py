"""Test complete feature extraction for one row with full logging"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from ml_orb_5m.src.features.price_action import (
    calculate_or_metrics,
    calculate_gap_features,
    detect_candlestick_patterns,
    calculate_momentum_indicators,
    calculate_price_levels
)

# Paths
TRADES_PATH = Path(__file__).parent.parent / "orb_5m" / "results" / "results_combined_top20" / "all_trades.csv"
DATA_DIR = Path(__file__).parent.parent / "data" / "processed"

print("=" * 80)
print("TESTING ONE COMPLETE ROW")
print("=" * 80)

# Load trades
print(f"\n1. Loading trades from CSV...")
trades = pd.read_csv(TRADES_PATH, parse_dates=['date', 'entry_time', 'exit_time'])
print(f"   Total trades: {len(trades):,}")

# Filter nulls
null_symbols = trades['symbol'].isnull().sum()
if null_symbols > 0:
    print(f"   Warning: {null_symbols} null symbols found, filtering...")
    trades = trades[trades['symbol'].notna()].copy()
    print(f"   After filtering: {len(trades):,}")

# Get first row
print(f"\n2. Testing first trade:")
row = trades.iloc[0]
print(f"   Symbol: {row['symbol']}")
print(f"   Date: {row['date']}")
print(f"   Entry time: {row['entry_time']}")
print(f"   Entry price: {row['entry_price']}")
print(f"   Exit price: {row['exit_price']}")
print(f"   Shares: {row['shares']}")
print(f"   Net PnL: {row['net_pnl']}")

# Check all columns
print(f"\n3. All columns in trades CSV:")
for col in trades.columns:
    print(f"   - {col}")

# Load data files
symbol = row['symbol']
date = row['date']

print(f"\n4. Loading parquet files for {symbol}...")
path_5m = DATA_DIR / "5min" / f"{symbol}.parquet"
path_daily = DATA_DIR / "daily" / f"{symbol}.parquet"

print(f"   5min exists: {path_5m.exists()}")
print(f"   Daily exists: {path_daily.exists()}")

if path_5m.exists():
    df5m = pd.read_parquet(path_5m)
    print(f"   5min shape: {df5m.shape}")
    print(f"   5min columns: {df5m.columns.tolist()}")
    df5m['date'] = df5m['timestamp'].dt.date
    
    target_date = pd.to_datetime(date).date()
    print(f"\n5. Filtering to target date: {target_date}")
    bars_today = df5m[df5m['date'] == target_date].copy()
    print(f"   Bars on target date: {len(bars_today)}")
    
    if len(bars_today) > 0:
        print(f"   First bar: {bars_today.iloc[0]['timestamp']}")
        print(f"   Last bar: {bars_today.iloc[-1]['timestamp']}")

if path_daily.exists():
    df_daily = pd.read_parquet(path_daily)
    print(f"\n6. Daily data:")
    print(f"   Shape: {df_daily.shape}")
    print(f"   Columns: {df_daily.columns.tolist()}")

# Extract features
print(f"\n7. Extracting features using fast method...")

bars_5min_all = df5m
target_date = pd.to_datetime(date).date()
bars_today = bars_5min_all[bars_5min_all['date'] == target_date].copy()

if bars_today.empty:
    print("   ERROR: No bars for target date!")
else:
    # Get previous day data
    bars_prev = bars_5min_all[bars_5min_all['date'] < target_date].copy()
    prev_day_close = bars_prev.iloc[-1]['close'] if not bars_prev.empty else None
    prev_day_high = bars_prev.groupby('date')['high'].max().iloc[-1] if not bars_prev.empty else None
    prev_day_low = bars_prev.groupby('date')['low'].min().iloc[-1] if not bars_prev.empty else None
    
    print(f"   Previous day close: {prev_day_close}")
    print(f"   Previous day high: {prev_day_high}")
    print(f"   Previous day low: {prev_day_low}")
    
    # Calculate ATR
    df_daily['date'] = pd.to_datetime(df_daily['date']).dt.date
    bars_daily_prev = df_daily[df_daily['date'] < target_date]
    
    if len(bars_daily_prev) >= 14:
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
        print(f"   ATR(14): {atr_14:.4f}")
    else:
        atr_14 = None
        print(f"   ATR(14): Not enough data ({len(bars_daily_prev)} days)")
    
    # Extract all features
    features = {}
    
    print(f"\n8. Calculating feature categories...")
    
    # 1. OR metrics
    or_features = calculate_or_metrics(bars_today)
    print(f"   OR metrics: {len(or_features)} features")
    for k, v in list(or_features.items())[:3]:
        print(f"     - {k}: {v}")
    features.update(or_features)
    
    # 2. Gap features
    gap_features = calculate_gap_features(bars_today, prev_day_close)
    print(f"   Gap features: {len(gap_features)} features")
    features.update(gap_features)
    
    # 3. Candlestick patterns
    pattern_features = detect_candlestick_patterns(bars_today)
    print(f"   Pattern features: {len(pattern_features)} features")
    features.update(pattern_features)
    
    # 4. Momentum
    momentum_features = calculate_momentum_indicators(bars_today[:3])
    print(f"   Momentum features: {len(momentum_features)} features")
    features.update(momentum_features)
    
    # 5. Price levels
    level_features = calculate_price_levels(bars_today, prev_day_high, prev_day_low)
    print(f"   Level features: {len(level_features)} features")
    features.update(level_features)
    
    # 6. ATR normalized
    if atr_14 is not None and 'or_range_size' in features:
        features['or_range_vs_atr'] = features['or_range_size'] / atr_14
        features['atr_14'] = atr_14
        if 'overnight_gap' in features:
            features['gap_vs_atr'] = abs(features['overnight_gap']) / atr_14
        print(f"   ATR-normalized features: 3 features")
    
    print(f"\n9. Total features extracted: {len(features)}")
    
    # Add trade columns
    print(f"\n10. Adding trade metadata columns...")
    features['symbol'] = row['symbol']
    features['date'] = row['date']
    features['entry_time'] = row['entry_time']
    features['exit_time'] = row['exit_time']
    features['entry_price'] = row['entry_price']
    features['exit_price'] = row['exit_price']
    features['shares'] = row['shares']
    features['net_pnl'] = row['net_pnl']
    
    print(f"   All columns added successfully")
    
    # Create DataFrame
    print(f"\n11. Creating DataFrame...")
    df = pd.DataFrame([features])
    
    # Add target
    df['target'] = (df['net_pnl'] > 0).astype(int)
    
    print(f"   DataFrame shape: {df.shape}")
    print(f"   Target: {df['target'].values[0]} (winner={df['net_pnl'].values[0] > 0})")
    
    # Show feature columns
    feature_cols = [c for c in df.columns if c not in ['symbol', 'date', 'entry_time', 'exit_time',
                                                         'entry_price', 'exit_price', 'shares',
                                                         'net_pnl', 'target']]
    
    print(f"\n12. Feature columns ({len(feature_cols)}):")
    for col in feature_cols:
        print(f"   - {col}: {df[col].values[0]}")
    
    print(f"\n" + "=" * 80)
    print("SUCCESS! One row processed completely")
    print("=" * 80)
    print(f"\nReady to process all {len(trades):,} trades")
