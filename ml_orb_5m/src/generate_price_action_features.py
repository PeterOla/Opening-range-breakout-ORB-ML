"""
Generate price action features for all trades and save to disk.

Loads 24k trades from orb_5m results, extracts price action features for each,
and saves to parquet for ML training.
"""
import sys
from pathlib import Path
import pandas as pd
from tqdm import tqdm

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from features.price_action import extract_price_action_features

# Paths
TRADES_PATH = Path(__file__).parent.parent.parent / "orb_5m" / "results" / "results_combined_top20" / "all_trades.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "features" / "price_action_features.parquet"
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "processed"

def main():
    print("=" * 80)
    print("GENERATING PRICE ACTION FEATURES")
    print("=" * 80)
    print()
    
    # Load trades
    print(f"\nLoading trades from: {TRADES_PATH}")
    trades = pd.read_csv(TRADES_PATH, parse_dates=['date', 'entry_time', 'exit_time'])
    
    # Filter out trades with null symbols
    null_symbols = trades['symbol'].isnull().sum()
    if null_symbols > 0:
        print(f"Warning: Found {null_symbols} trades with null symbols, filtering them out...")
        trades = trades[trades['symbol'].notna()].copy()
    
    print(f"Loaded {len(trades):,} trades")
    print()
    
    # Extract features for each trade
    print("Extracting features...")
    all_features = []
    errors = []
    
    for idx, row in tqdm(trades.iterrows(), total=len(trades), desc="Processing trades"):
        try:
            # Extract features
            features = extract_price_action_features(
                symbol=row['symbol'],
                date=row['date'],
                data_dir=str(DATA_DIR)
            )
            
            if features:
                # Add trade identifiers
                features['symbol'] = row['symbol']
                features['date'] = row['date']
                features['entry_time'] = row['entry_time']
            else:
                errors.append((row['symbol'], row['date'], "No features returned"))
                
                # Add target label
                features['target'] = 1 if row['net_pnl'] > 0 else 0
                features['net_pnl'] = row['net_pnl']
                
                # Add existing trade features for reference
                features['direction'] = row['direction']
                features['rvol_rank'] = row['rvol_rank']
                features['or_rvol_14'] = row['or_rvol_14']
                
                all_features.append(features)
        
        except Exception as e:
            errors.append({
                'symbol': row['symbol'],
                'date': row['date'],
                'error': str(e)
            })
    
    print()
    print(f"Successfully extracted features for {len(all_features):,} trades")
    print(f"Errors: {len(errors)}")
    
    # Always show sample errors if any exist
    if errors:
        print("\nSample errors (first 20):")
        for err in errors[:20]:
            if isinstance(err, tuple):
                print(f"  {err[0]} {err[1]}: {err[2]}")
            else:
                print(f"  {err['symbol']} {err['date']}: {err['error']}")
    
    if len(all_features) == 0:
        print("\n❌ No features extracted! Check errors above.")
        return
    
    # Convert to DataFrame
    print("\nConverting to DataFrame...")
    df = pd.DataFrame(all_features)
    
    # Summary stats
    print("\nFeature summary:")
    print(f"  Rows: {len(df):,}")
    print(f"  Columns: {len(df.columns)}")
    if 'target' in df.columns:
        print(f"  Winners: {df['target'].sum():,} ({df['target'].mean()*100:.2f}%)")
    print(f"  Losers: {(~df['target'].astype(bool)).sum():,} ({(1-df['target'].mean())*100:.2f}%)")
    
    print("\nFeature columns:")
    feature_cols = [c for c in df.columns if c not in ['symbol', 'date', 'entry_time', 'target', 'net_pnl', 'direction', 'rvol_rank', 'or_rvol_14']]
    for col in sorted(feature_cols):
        print(f"  - {col}")
    
    # Save to parquet
    print(f"\nSaving to: {OUTPUT_PATH}")
    OUTPUT_PATH.parent.mkdir(exist_ok=True, parents=True)
    df.to_parquet(OUTPUT_PATH, index=False)
    
    print()
    print("=" * 80)
    print("PRICE ACTION FEATURES SAVED!")
    print("=" * 80)
    print(f"File: {OUTPUT_PATH}")
    print(f"Size: {OUTPUT_PATH.stat().st_size / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    main()
