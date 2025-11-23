"""
ML-Enhanced Backtest (2024-2025)
Simulates trading using the trained Ensemble model to filter trades.
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path
import joblib
import json
import matplotlib.pyplot as plt

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_PATH = BASE_DIR / "data" / "features" / "all_features.parquet"
MODELS_DIR = BASE_DIR / "models" / "saved_models"
RESULTS_DIR = BASE_DIR / "results"
CONFIG_PATH = BASE_DIR / "config" / "selected_features.json"

# Ensure directories exist
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def load_artifacts():
    print("Loading model artifacts...")
    
    # Load config
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    features = config["final_selected_features"]
    
    # Load model
    model = joblib.load(MODELS_DIR / "ensemble_model.pkl")
    
    # Load preprocessors
    imputer = joblib.load(MODELS_DIR / "ensemble_imputer.pkl")
    scaler = joblib.load(MODELS_DIR / "ensemble_scaler.pkl")
    
    return model, imputer, scaler, features

def load_test_data():
    print(f"Loading test data from {DATA_PATH}...")
    df = pd.read_parquet(DATA_PATH)
    df['date'] = pd.to_datetime(df['date'])
    
    # Filter for Test Set (2024-2025)
    test_mask = df['date'] >= pd.to_datetime("2024-01-01")
    test_df = df[test_mask].copy().reset_index(drop=True)
    
    print(f"Test Data: {len(test_df)} trades (2024-2025)")
    return test_df

def run_ml_backtest(test_df, model, imputer, scaler, features, threshold=0.60):
    print(f"\nRunning ML Backtest (Threshold: {threshold})...")
    
    # Prepare features
    X = test_df[features]
    
    # Preprocess
    X_imp = pd.DataFrame(imputer.transform(X), columns=features)
    X_scaled = pd.DataFrame(scaler.transform(X_imp), columns=features)
    
    # Predict
    y_prob = model.predict_proba(X_scaled)[:, 1]
    
    # Filter trades
    test_df['ml_prob'] = y_prob
    
    # Infer side (same logic as analysis script)
    test_df['price_change'] = test_df['exit_price'] - test_df['entry_price']
    conditions = [
        (test_df['net_pnl'] > 0) & (test_df['price_change'] > 0),
        (test_df['net_pnl'] < 0) & (test_df['price_change'] < 0),
        (test_df['net_pnl'] > 0) & (test_df['price_change'] < 0),
        (test_df['net_pnl'] < 0) & (test_df['price_change'] > 0)
    ]
    choices = ['long', 'long', 'short', 'short']
    test_df['side'] = np.select(conditions, choices, default='unknown')

    # Apply Dynamic Thresholds
    # If threshold is a single float, use it for both.
    # If threshold is a dict {'long': 0.6, 'short': 0.5}, use specific.
    
    if isinstance(threshold, dict):
        long_thresh = threshold.get('long', 0.6)
        short_thresh = threshold.get('short', 0.6)
        print(f"Using Dynamic Thresholds: Long={long_thresh}, Short={short_thresh}")
        
        test_df['threshold'] = np.where(test_df['side'] == 'long', long_thresh, short_thresh)
        test_df['ml_signal'] = (test_df['ml_prob'] >= test_df['threshold']).astype(int)
    else:
        test_df['ml_signal'] = (test_df['ml_prob'] >= threshold).astype(int)
    
    # Select only trades where ML says "GO"
    ml_trades = test_df[test_df['ml_signal'] == 1].copy()
    
    print(f"Original Trades: {len(test_df)}")
    print(f"ML-Selected Trades: {len(ml_trades)} ({len(ml_trades)/len(test_df):.1%})")
    
    return ml_trades

def calculate_metrics(trades, initial_equity=10000):
    if trades.empty:
        return {
            'total_trades': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'total_pnl': 0.0,
            'final_equity': initial_equity,
            'return_pct': 0.0,
            'max_drawdown': 0.0
        }
        
    # Sort by entry time
    trades = trades.sort_values('entry_time')
    
    # Calculate cumulative PnL
    trades['cum_pnl'] = trades['net_pnl'].cumsum()
    trades['equity'] = initial_equity + trades['cum_pnl']
    
    # Metrics
    total_trades = len(trades)
    winners = trades[trades['net_pnl'] > 0]
    losers = trades[trades['net_pnl'] <= 0]
    
    win_rate = len(winners) / total_trades
    
    gross_profit = winners['net_pnl'].sum()
    gross_loss = abs(losers['net_pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    total_pnl = trades['net_pnl'].sum()
    final_equity = trades['equity'].iloc[-1]
    return_pct = (final_equity - initial_equity) / initial_equity
    
    # Drawdown
    trades['peak_equity'] = trades['equity'].cummax()
    trades['drawdown'] = (trades['equity'] - trades['peak_equity']) / trades['peak_equity']
    max_drawdown = trades['drawdown'].min()
    
    return {
        'total_trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_pnl': total_pnl,
        'final_equity': final_equity,
        'return_pct': return_pct,
        'max_drawdown': max_drawdown
    }

def main():
    # 1. Load Artifacts
    model, imputer, scaler, features = load_artifacts()
    
    # 2. Load Test Data
    test_df = load_test_data()
    
    # 3. Run Backtest with different thresholds
    # Test standard thresholds + Dynamic Regime thresholds
    scenarios = [
        0.5, 0.55, 0.6, 0.65,
        {'long': 0.60, 'short': 0.50},  # Relaxed Shorts
        {'long': 0.60, 'short': 0.45},  # Aggressive Shorts
        {'long': 0.65, 'short': 0.50}   # High Quality Longs, Relaxed Shorts
    ]
    
    results = []
    
    print("\n" + "="*80)
    print("ML-ENHANCED BACKTEST RESULTS (2024-2025)")
    print("="*80)
    print(f"{'Threshold':<25} | {'Trades':<8} | {'Win Rate':<10} | {'Profit Factor':<14} | {'Return':<10} | {'DD':<10}")
    print("-" * 100)
    
    # Baseline (No ML)
    base_metrics = calculate_metrics(test_df)
    print(f"{'Baseline':<25} | {base_metrics['total_trades']:<8} | {base_metrics['win_rate']:.2%}   | {base_metrics['profit_factor']:.2f}           | {base_metrics['return_pct']:.1%}     | {base_metrics['max_drawdown']:.1%}")
    
    for s in scenarios:
        ml_trades = run_ml_backtest(test_df, model, imputer, scaler, features, threshold=s)
        metrics = calculate_metrics(ml_trades)
        
        # Format label
        if isinstance(s, dict):
            label = f"L:{s['long']} S:{s['short']}"
        else:
            label = str(s)
            
        results.append({
            'threshold': label,
            **metrics
        })
        
        print(f"{label:<25} | {metrics['total_trades']:<8} | {metrics['win_rate']:.2%}   | {metrics['profit_factor']:.2f}           | {metrics['return_pct']:.1%}     | {metrics['max_drawdown']:.1%}")
        
        # Save trades for best scenario
        if label == "L:0.6 S:0.5":
             ml_trades.to_csv(RESULTS_DIR / "ml_enhanced_trades_dynamic.csv", index=False)

    # Save summary
    pd.DataFrame(results).to_csv(RESULTS_DIR / "ml_backtest_summary.csv", index=False)

if __name__ == "__main__":
    main()
