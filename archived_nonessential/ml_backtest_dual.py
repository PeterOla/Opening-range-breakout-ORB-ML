"""
Dual Model Backtest (Long/Short Specialized)
"""
import pandas as pd
import numpy as np
from pathlib import Path
import joblib
import json

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_PATH = BASE_DIR / "data" / "features" / "all_features.parquet"
MODELS_DIR = BASE_DIR / "models" / "saved_models"
RESULTS_DIR = BASE_DIR / "results"
CONFIG_PATH = BASE_DIR / "config" / "selected_features.json"

def load_artifacts():
    print("Loading dual model artifacts...")
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    features = config["final_selected_features"]
    
    artifacts = {}
    for side in ['long', 'short']:
        artifacts[side] = {
            'model': joblib.load(MODELS_DIR / f"{side}_model.pkl"),
            'imputer': joblib.load(MODELS_DIR / f"{side}_imputer.pkl"),
            'scaler': joblib.load(MODELS_DIR / f"{side}_scaler.pkl")
        }
    
    return artifacts, features

def load_test_data():
    print(f"Loading test data...")
    df = pd.read_parquet(DATA_PATH)
    df['date'] = pd.to_datetime(df['date'])
    
    # Filter for Test Set (2024-2025)
    test_mask = df['date'] >= pd.to_datetime("2024-01-01")
    test_df = df[test_mask].copy().reset_index(drop=True)
    
    # Infer Side
    test_df['price_change'] = test_df['exit_price'] - test_df['entry_price']
    conditions = [
        (test_df['net_pnl'] > 0) & (test_df['price_change'] > 0),
        (test_df['net_pnl'] < 0) & (test_df['price_change'] < 0),
        (test_df['net_pnl'] > 0) & (test_df['price_change'] < 0),
        (test_df['net_pnl'] < 0) & (test_df['price_change'] > 0)
    ]
    choices = ['long', 'long', 'short', 'short']
    test_df['side'] = np.select(conditions, choices, default='unknown')
    
    return test_df[test_df['side'] != 'unknown'].copy()

def predict_dual(df, artifacts, features):
    # Initialize prob column
    df['ml_prob'] = 0.0
    
    # Predict Longs
    long_mask = df['side'] == 'long'
    if long_mask.any():
        X_long = df.loc[long_mask, features]
        imp = artifacts['long']['imputer']
        scl = artifacts['long']['scaler']
        mod = artifacts['long']['model']
        
        X_imp = imp.transform(X_long)
        X_scl = scl.transform(X_imp)
        df.loc[long_mask, 'ml_prob'] = mod.predict_proba(X_scl)[:, 1]
        
    # Predict Shorts
    short_mask = df['side'] == 'short'
    if short_mask.any():
        X_short = df.loc[short_mask, features]
        imp = artifacts['short']['imputer']
        scl = artifacts['short']['scaler']
        mod = artifacts['short']['model']
        
        X_imp = imp.transform(X_short)
        X_scl = scl.transform(X_imp)
        df.loc[short_mask, 'ml_prob'] = mod.predict_proba(X_scl)[:, 1]
        
    return df

def calculate_metrics(trades, initial_equity=10000):
    if trades.empty:
        return {'total_trades': 0, 'win_rate': 0.0, 'profit_factor': 0.0, 'return_pct': 0.0, 'max_drawdown': 0.0}
        
    trades = trades.sort_values('entry_time')
    trades['cum_pnl'] = trades['net_pnl'].cumsum()
    trades['equity'] = initial_equity + trades['cum_pnl']
    
    total_trades = len(trades)
    winners = trades[trades['net_pnl'] > 0]
    losers = trades[trades['net_pnl'] <= 0]
    win_rate = len(winners) / total_trades
    
    gross_profit = winners['net_pnl'].sum()
    gross_loss = abs(losers['net_pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    final_equity = trades['equity'].iloc[-1]
    return_pct = (final_equity - initial_equity) / initial_equity
    
    trades['peak_equity'] = trades['equity'].cummax()
    trades['drawdown'] = (trades['equity'] - trades['peak_equity']) / trades['peak_equity']
    max_drawdown = trades['drawdown'].min()
    
    return {
        'total_trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'return_pct': return_pct,
        'max_drawdown': max_drawdown
    }

def main():
    artifacts, features = load_artifacts()
    test_df = load_test_data()
    
    # Generate Predictions
    test_df = predict_dual(test_df, artifacts, features)
    
    # Test Thresholds
    thresholds = [0.5, 0.55, 0.6, 0.65, 0.7]
    
    print("\n" + "="*80)
    print("DUAL MODEL BACKTEST RESULTS (2024-2025)")
    print("="*80)
    print(f"{'Threshold':<10} | {'Trades':<8} | {'Win Rate':<10} | {'Profit Factor':<14} | {'Return':<10} | {'DD':<10}")
    print("-" * 80)
    
    # Baseline
    base = calculate_metrics(test_df)
    print(f"{'Baseline':<10} | {base['total_trades']:<8} | {base['win_rate']:.2%}   | {base['profit_factor']:.2f}           | {base['return_pct']:.1%}     | {base['max_drawdown']:.1%}")
    
    for t in thresholds:
        test_df['ml_signal'] = (test_df['ml_prob'] >= t).astype(int)
        ml_trades = test_df[test_df['ml_signal'] == 1].copy()
        
        m = calculate_metrics(ml_trades)
        print(f"{t:<10.2f} | {m['total_trades']:<8} | {m['win_rate']:.2%}   | {m['profit_factor']:.2f}           | {m['return_pct']:.1%}     | {m['max_drawdown']:.1%}")
        
        if t == 0.6:
            ml_trades.to_csv(RESULTS_DIR / "dual_model_trades_0.6.csv", index=False)
            
            # Analyze Short Performance specifically
            shorts = ml_trades[ml_trades['side'] == 'short']
            longs = ml_trades[ml_trades['side'] == 'long']
            print(f"   > Longs: {len(longs)} (WR: {len(longs[longs['net_pnl']>0])/len(longs) if len(longs)>0 else 0:.1%})")
            print(f"   > Shorts: {len(shorts)} (WR: {len(shorts[shorts['net_pnl']>0])/len(shorts) if len(shorts)>0 else 0:.1%})")

if __name__ == "__main__":
    main()
