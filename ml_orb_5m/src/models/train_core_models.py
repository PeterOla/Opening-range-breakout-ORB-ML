"""
Train Additional Models for Strategy Comparison
Trains:
1. XGBoost (With Context)
2. XGBoost (No Context)
3. Logistic Regression (With Context)
4. Logistic Regression (No Context)

Saves models with specific prefixes to allow switching in experiments.
"""
import pandas as pd
import numpy as np
import joblib
import json
from pathlib import Path
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
    train_mask = df['date'] < pd.to_datetime("2024-01-01")
    train_df = df[train_mask].copy()
    
    print(f"Training Data: {len(train_df)} trades (Pre-2024)")
    return train_df

def train_and_save(df, features, model_type, use_context, prefix):
    """
    model_type: 'xgb' or 'logreg'
    use_context: bool (just for logging)
    prefix: str (e.g., 'xgb_context')
    """
    print(f"\n=== Training {prefix} ({model_type}, Context={use_context}) ===")
    
    for side in ['long', 'short']:
        side_df = df[df['side'] == side]
        X = side_df[features]
        y = side_df['target']
        
        print(f"  Side: {side.upper()} | Samples: {len(X)} | Win Rate: {y.mean():.2%}")
        
        # Preprocessing
        imputer = SimpleImputer(strategy='median')
        scaler = StandardScaler()
        
        X_imp = imputer.fit_transform(X)
        X_scaled = scaler.fit_transform(X_imp)
        
        # Model Selection
        scale_pos_weight = (len(y) - y.sum()) / y.sum()
        
        if model_type == 'xgb':
            model = XGBClassifier(
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
        elif model_type == 'logreg':
            model = LogisticRegression(
                class_weight='balanced', 
                max_iter=1000, 
                random_state=42
            )
        else:
            raise ValueError(f"Unknown model type: {model_type}")
            
        # Fit
        model.fit(X_scaled, y)
        
        # Evaluate
        y_prob = model.predict_proba(X_scaled)[:, 1]
        auc = roc_auc_score(y, y_prob)
        print(f"  {side.upper()} Train AUC: {auc:.3f}")
        
        # Save
        # Naming convention: {prefix}_{side}_model.pkl
        # e.g. xgb_context_long_model.pkl
        base_name = f"{prefix}_{side}"
        joblib.dump(model, MODELS_DIR / f"{base_name}_model.pkl")
        joblib.dump(imputer, MODELS_DIR / f"{base_name}_imputer.pkl")
        joblib.dump(scaler, MODELS_DIR / f"{base_name}_scaler.pkl")

def main():
    # Load Data
    train_df = load_and_prep_data()
    
    # Load Feature Sets
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    
    feats_context = config["final_selected_features"]
    feats_nocontext = config["no_market_context_features"]
    
    # 1. XGBoost With Context
    train_and_save(train_df, feats_context, 'xgb', True, 'xgb_context')
    
    # 2. XGBoost No Context
    train_and_save(train_df, feats_nocontext, 'xgb', False, 'xgb_nocontext')
    
    # 3. LogReg With Context
    train_and_save(train_df, feats_context, 'logreg', True, 'logreg_context')
    
    # 4. LogReg No Context
    train_and_save(train_df, feats_nocontext, 'logreg', False, 'logreg_nocontext')
    
    print("\nAll models trained and saved successfully.")

if __name__ == "__main__":
    main()
