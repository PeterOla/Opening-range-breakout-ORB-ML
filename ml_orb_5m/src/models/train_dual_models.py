"""
Train Dual Models (Long vs Short)
Separates training data into Long and Short trades to create specialized models.
"""
import pandas as pd
import numpy as np
import joblib
import json
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.ensemble import VotingClassifier
from xgboost import XGBClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, precision_score

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_PATH = BASE_DIR / "data" / "features" / "all_features.parquet"
MODELS_DIR = BASE_DIR / "models" / "saved_models"
CONFIG_PATH = BASE_DIR / "config" / "selected_features.json"

# Ensure output dir
MODELS_DIR.mkdir(parents=True, exist_ok=True)

def load_and_prep_data():
    print("Loading data...")
    df = pd.read_parquet(DATA_PATH)
    df['date'] = pd.to_datetime(df['date'])
    
    # Load features
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    features = config["final_selected_features"]
    # features = config["no_market_context_features"]
    
    # Infer Side
    df['price_change'] = df['exit_price'] - df['entry_price']
    conditions = [
        (df['net_pnl'] > 0) & (df['price_change'] > 0),
        (df['net_pnl'] < 0) & (df['price_change'] < 0),
        (df['net_pnl'] > 0) & (df['price_change'] < 0),
        (df['net_pnl'] < 0) & (df['price_change'] > 0)
    ]
    choices = ['long', 'long', 'short', 'short']
    df['side'] = np.select(conditions, choices, default='unknown')
    
    # Filter unknown
    df = df[df['side'] != 'unknown'].copy()
    
    # Target
    df['target'] = (df['net_pnl'] > 0).astype(int)
    
    # Split by Date (Train < 2024, Test >= 2024)
    # We only train on Train set
    train_mask = df['date'] < pd.to_datetime("2024-01-01")
    train_df = df[train_mask].copy()
    
    print(f"Training Data: {len(train_df)} trades (Pre-2024)")
    return train_df, features

def train_model(df, features, side_name):
    print(f"\n--- Training {side_name} Model ---")
    print(f"Samples: {len(df)}")
    print(f"Win Rate: {df['target'].mean():.2%}")
    
    X = df[features]
    y = df['target']
    
    # Preprocessing
    imputer = SimpleImputer(strategy='median')
    scaler = StandardScaler()
    
    X_imp = imputer.fit_transform(X)
    X_scaled = scaler.fit_transform(X_imp)
    
    # Models
    scale_pos_weight = (len(y) - y.sum()) / y.sum()
    
    xgb = XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        n_jobs=-1,
        eval_metric='logloss'
    )
    
    lr = LogisticRegression(class_weight='balanced', max_iter=1000, random_state=42)
    
    ensemble = VotingClassifier(
        estimators=[('xgb', xgb), ('lr', lr)],
        voting='soft'
    )
    
    # Fit
    ensemble.fit(X_scaled, y)
    
    # Evaluate on Train (Sanity Check)
    y_pred = ensemble.predict(X_scaled)
    y_prob = ensemble.predict_proba(X_scaled)[:, 1]
    
    auc = roc_auc_score(y, y_prob)
    prec = precision_score(y, y_pred)
    
    print(f"{side_name} Train AUC: {auc:.3f}")
    print(f"{side_name} Train Precision: {prec:.3f}")
    
    # Save
    joblib.dump(ensemble, MODELS_DIR / f"{side_name.lower()}_model.pkl")
    joblib.dump(imputer, MODELS_DIR / f"{side_name.lower()}_imputer.pkl")
    joblib.dump(scaler, MODELS_DIR / f"{side_name.lower()}_scaler.pkl")
    print(f"Saved {side_name} artifacts.")

def main():
    train_df, features = load_and_prep_data()
    
    # Split Long/Short
    long_df = train_df[train_df['side'] == 'long']
    short_df = train_df[train_df['side'] == 'short']
    
    # Train
    train_model(long_df, features, "Long")
    train_model(short_df, features, "Short")

if __name__ == "__main__":
    main()
