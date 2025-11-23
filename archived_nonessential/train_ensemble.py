"""
Train Ensemble Model (Voting Classifier)
Uses the Top 25 features selected by RFE/SHAP.
Combines XGBoost and Logistic Regression.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import joblib
import json
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import VotingClassifier
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score, 
    accuracy_score, confusion_matrix
)
import xgboost as xgb

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_PATH = BASE_DIR / "data" / "features" / "all_features.parquet"
MODELS_DIR = BASE_DIR / "models" / "saved_models"
RESULTS_DIR = BASE_DIR / "results"
CONFIG_PATH = BASE_DIR / "config" / "selected_features.json"

# Ensure directories exist
MODELS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def load_config():
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    return config["final_selected_features"]

def load_and_split_data(selected_features):
    print(f"Loading data from {DATA_PATH}...")
    df = pd.read_parquet(DATA_PATH)
    df = df.sort_values('date').reset_index(drop=True)
    df['date'] = pd.to_datetime(df['date'])
    
    # Define split dates
    val_start_date = pd.to_datetime("2023-01-01")
    test_start_date = pd.to_datetime("2024-01-01")
    
    # Create masks
    train_mask = df['date'] < val_start_date
    val_mask = (df['date'] >= val_start_date) & (df['date'] < test_start_date)
    test_mask = df['date'] >= test_start_date
    
    # Split
    train_df = df[train_mask].copy()
    val_df = df[val_mask].copy()
    test_df = df[test_mask].copy()
    
    print(f"Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)}")
    
    return train_df, val_df, test_df

def prepare_features(train_df, val_df, test_df, selected_features):
    print(f"\nPreparing {len(selected_features)} selected features...")
    
    X_train = train_df[selected_features]
    y_train = train_df['target']
    
    X_val = val_df[selected_features]
    y_val = val_df['target']
    
    X_test = test_df[selected_features]
    y_test = test_df['target']
    
    # Imputation
    imputer = SimpleImputer(strategy='median')
    X_train_imp = pd.DataFrame(imputer.fit_transform(X_train), columns=selected_features)
    X_val_imp = pd.DataFrame(imputer.transform(X_val), columns=selected_features)
    X_test_imp = pd.DataFrame(imputer.transform(X_test), columns=selected_features)
    
    # Scaling (Critical for Logistic Regression)
    scaler = StandardScaler()
    X_train_scaled = pd.DataFrame(scaler.fit_transform(X_train_imp), columns=selected_features)
    X_val_scaled = pd.DataFrame(scaler.transform(X_val_imp), columns=selected_features)
    X_test_scaled = pd.DataFrame(scaler.transform(X_test_imp), columns=selected_features)
    
    # Save preprocessors
    joblib.dump(imputer, MODELS_DIR / "ensemble_imputer.pkl")
    joblib.dump(scaler, MODELS_DIR / "ensemble_scaler.pkl")
    
    return X_train_scaled, y_train, X_val_scaled, y_val, X_test_scaled, y_test

def evaluate_model(model, X, y, model_name, threshold=0.5):
    y_prob = model.predict_proba(X)[:, 1]
    y_pred = (y_prob >= threshold).astype(int)
    
    auc = roc_auc_score(y, y_prob)
    prec = precision_score(y, y_pred, zero_division=0)
    rec = recall_score(y, y_pred, zero_division=0)
    f1 = f1_score(y, y_pred, zero_division=0)
    
    print(f"\n--- {model_name} Performance (Val) ---")
    print(f"AUC:       {auc:.4f}")
    print(f"Precision: {prec:.4f} (Win Rate)")
    print(f"Recall:    {rec:.4f}")
    print(f"Trades:    {sum(y_pred)} (out of {len(y)})")
    
    return {'Model': model_name, 'AUC': auc, 'Precision': prec, 'Recall': rec, 'Trades': sum(y_pred)}

def train_ensemble(X_train, y_train, X_val, y_val):
    print("\nTraining Ensemble Model...")
    
    # 1. XGBoost (The heavy lifter)
    neg_pos_ratio = (len(y_train) - sum(y_train)) / sum(y_train)
    xgb_clf = xgb.XGBClassifier(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=4,
        scale_pos_weight=neg_pos_ratio,
        random_state=42,
        eval_metric='auc'
        # Removed early_stopping_rounds because VotingClassifier doesn't pass eval_set easily
    )
    
    # 2. Logistic Regression (The stabilizer)
    lr_clf = LogisticRegression(
        max_iter=1000, 
        class_weight='balanced', 
        C=0.1, 
        random_state=42
    )
    
    # 3. Voting Classifier
    # Soft voting averages the probabilities
    ensemble = VotingClassifier(
        estimators=[
            ('xgb', xgb_clf),
            ('lr', lr_clf)
        ],
        voting='soft',
        weights=[2, 1] # Give XGBoost 2x weight
    )
    
    # Note: VotingClassifier doesn't support eval_set directly for sub-estimators in fit()
    # So we fit normally. XGBoost early stopping won't work inside VotingClassifier easily
    # without custom wrappers, so we'll just fit with fixed n_estimators for simplicity
    # or pre-fit. Let's fit the ensemble directly.
    
    ensemble.fit(X_train, y_train)
    
    # Save
    joblib.dump(ensemble, MODELS_DIR / "ensemble_model.pkl")
    
    return ensemble

def main():
    # 1. Load Config
    selected_features = load_config()
    
    # 2. Load Data
    train_df, val_df, test_df = load_and_split_data(selected_features)
    
    # 3. Prepare
    X_train, y_train, X_val, y_val, X_test, y_test = prepare_features(train_df, val_df, test_df, selected_features)
    
    # 4. Train Ensemble
    ensemble = train_ensemble(X_train, y_train, X_val, y_val)
    
    # 5. Evaluate
    evaluate_model(ensemble, X_val, y_val, "Ensemble (XGB+LR)")
    
    # 6. Threshold Analysis
    print("\n--- Threshold Optimization ---")
    y_prob = ensemble.predict_proba(X_val)[:, 1]
    thresholds = [0.5, 0.55, 0.6, 0.65, 0.7]
    
    for t in thresholds:
        y_pred = (y_prob >= t).astype(int)
        prec = precision_score(y_val, y_pred, zero_division=0)
        n_trades = sum(y_pred)
        print(f"Threshold {t:.2f}: Win Rate = {prec:.2%} | Trades = {n_trades}")

if __name__ == "__main__":
    main()
