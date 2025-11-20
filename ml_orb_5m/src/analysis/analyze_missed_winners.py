"""
Analyze Missed Winners and Bear Market Performance
"""
import pandas as pd
import numpy as np
import joblib
import json
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_PATH = BASE_DIR / "data" / "features" / "all_features.parquet"
MODELS_DIR = BASE_DIR / "models" / "saved_models"
CONFIG_PATH = BASE_DIR / "config" / "selected_features.json"
OUTPUT_DIR = BASE_DIR / "docs" / "images"

def load_artifacts():
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    features = config["final_selected_features"]
    model = joblib.load(MODELS_DIR / "ensemble_model.pkl")
    imputer = joblib.load(MODELS_DIR / "ensemble_imputer.pkl")
    scaler = joblib.load(MODELS_DIR / "ensemble_scaler.pkl")
    return model, imputer, scaler, features

def load_data():
    df = pd.read_parquet(DATA_PATH)
    df['date'] = pd.to_datetime(df['date'])
    # Test set only
    return df[df['date'] >= pd.to_datetime("2024-01-01")].copy().reset_index(drop=True)

def analyze_missed_winners():
    model, imputer, scaler, features = load_artifacts()
    df = load_data()
    
    # Prepare X
    X = df[features]
    X_imp = pd.DataFrame(imputer.transform(X), columns=features)
    X_scaled = pd.DataFrame(scaler.transform(X_imp), columns=features)
    
    # Predict
    probs = model.predict_proba(X_scaled)[:, 1]
    df['ml_prob'] = probs
    
    # Define Categories (Threshold 0.60)
    THRESHOLD = 0.60
    df['is_winner'] = df['net_pnl'] > 0
    df['ml_accept'] = df['ml_prob'] >= THRESHOLD
    
    # Categories
    captured_winners = df[df['is_winner'] & df['ml_accept']]
    missed_winners = df[df['is_winner'] & ~df['ml_accept']]
    avoided_losers = df[~df['is_winner'] & ~df['ml_accept']]
    bad_picks = df[~df['is_winner'] & df['ml_accept']]
    
    print(f"Total Trades: {len(df)}")
    print(f"Captured Winners: {len(captured_winners)} (Avg Prob: {captured_winners['ml_prob'].mean():.2f})")
    print(f"Missed Winners: {len(missed_winners)} (Avg Prob: {missed_winners['ml_prob'].mean():.2f})")
    print(f"Avoided Losers: {len(avoided_losers)}")
    print(f"Bad Picks: {len(bad_picks)}")
    
    # --- Analysis 1: Bear Market Performance ---
    print("\n--- Bear Market Analysis (SPY < SMA50) ---")
    # We need to reconstruct 'spy_above_sma50' if it's not in the dataframe directly (it is in features)
    # But wait, 'spy_above_sma50' is a feature, so it's in X_imp/df if we kept it.
    # Let's check if it's in the original df or features.
    
    if 'spy_above_sma50' in df.columns:
        bear_market = df[df['spy_above_sma50'] == 0]
    elif 'spy_above_sma50' in features:
        # It was scaled, so we can't easily check 0/1 from X_scaled, but we can check the original input if available
        # The parquet file should have it.
        bear_market = df[df['spy_above_sma50'] == 0]
    else:
        print("Warning: 'spy_above_sma50' not found in columns.")
        bear_market = pd.DataFrame()

    if not bear_market.empty:
        bear_winners = bear_market[bear_market['net_pnl'] > 0]
        bear_picks = bear_market[bear_market['ml_prob'] >= THRESHOLD]
        
        print(f"Total Bear Market Trades: {len(bear_market)}")
        print(f"Profitable Bear Trades Available: {len(bear_winners)} ({len(bear_winners)/len(bear_market):.1%})")
        print(f"Model Selected in Bear Market: {len(bear_picks)}")
        if len(bear_picks) > 0:
            bear_win_rate = len(bear_picks[bear_picks['net_pnl'] > 0]) / len(bear_picks)
            print(f"Model Win Rate in Bear Market: {bear_win_rate:.1%}")
        else:
            print("Model selected 0 trades in Bear Market.")
            
    # --- Analysis 2: Long vs Short ---
    print("\n--- Long vs Short Analysis ---")
    
    # Infer side
    # If PnL and Price Change have same sign -> Long
    # If PnL and Price Change have diff sign -> Short
    df['price_change'] = df['exit_price'] - df['entry_price']
    # Handle edge case where PnL is 0 or price_change is 0 (unlikely but possible)
    # We'll assume Long if ambiguous, or drop.
    
    # Vectorized side inference
    # sign(pnl) == sign(price_change) => Long
    # sign(pnl) != sign(price_change) => Short
    
    # We use numpy sign, but need to handle 0 carefully. 
    # Let's just use the logic: if (pnl > 0 and price_up) or (pnl < 0 and price_down) -> Long
    
    conditions = [
        (df['net_pnl'] > 0) & (df['price_change'] > 0),
        (df['net_pnl'] < 0) & (df['price_change'] < 0),
        (df['net_pnl'] > 0) & (df['price_change'] < 0),
        (df['net_pnl'] < 0) & (df['price_change'] > 0)
    ]
    choices = ['long', 'long', 'short', 'short']
    df['side'] = np.select(conditions, choices, default='unknown')
    
    if 'side' in df.columns:
        shorts = df[df['side'] == 'short']
        longs = df[df['side'] == 'long']
        
        print(f"Total Shorts: {len(shorts)} | Winners: {len(shorts[shorts['net_pnl']>0])} ({len(shorts[shorts['net_pnl']>0])/len(shorts):.1%})")
        print(f"Total Longs: {len(longs)} | Winners: {len(longs[longs['net_pnl']>0])} ({len(longs[longs['net_pnl']>0])/len(longs):.1%})")
        
        short_picks = shorts[shorts['ml_prob'] >= THRESHOLD]
        long_picks = longs[longs['ml_prob'] >= THRESHOLD]
        
        print(f"Model Selected Shorts: {len(short_picks)}")
        if len(short_picks) > 0:
             print(f"Short Win Rate: {len(short_picks[short_picks['net_pnl']>0])/len(short_picks):.1%}")
             
        print(f"Model Selected Longs: {len(long_picks)}")
        if len(long_picks) > 0:
             print(f"Long Win Rate: {len(long_picks[long_picks['net_pnl']>0])/len(long_picks):.1%}")
    else:
        print("Column 'side' not found for Long/Short analysis.")

    # --- Analysis 3: Probability Distribution of Missed Winners ---
    plt.figure(figsize=(10, 6))
    sns.histplot(missed_winners['ml_prob'], bins=50, color='orange', label='Missed Winners', alpha=0.6)
    sns.histplot(captured_winners['ml_prob'], bins=50, color='green', label='Captured Winners', alpha=0.6)
    plt.axvline(THRESHOLD, color='red', linestyle='--', label='Threshold (0.60)')
    plt.title('Probability Distribution of Winning Trades')
    plt.xlabel('ML Probability')
    plt.legend()
    plt.savefig(OUTPUT_DIR / "missed_winners_dist.png")
    print(f"\nSaved distribution plot to {OUTPUT_DIR / 'missed_winners_dist.png'}")

if __name__ == "__main__":
    analyze_missed_winners()
