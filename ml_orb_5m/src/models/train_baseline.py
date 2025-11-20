"""
Train Baseline Models (Logistic Regression, LightGBM, XGBoost)
Splits data into Train (2021-2022), Validation (2023), and Test (2024-2025).
"""
import pandas as pd
import numpy as np
from pathlib import Path
import joblib
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score, 
    accuracy_score, confusion_matrix, roc_curve
)
import lightgbm as lgb
import xgboost as xgb

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_PATH = BASE_DIR / "data" / "features" / "all_features.parquet"
MODELS_DIR = BASE_DIR / "models" / "saved_models"
RESULTS_DIR = BASE_DIR / "results"

# Ensure directories exist
MODELS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def load_and_split_data():
    print(f"Loading data from {DATA_PATH}...")
    df = pd.read_parquet(DATA_PATH)
    
    # Sort by date to ensure proper time-series split
    df = df.sort_values('date').reset_index(drop=True)
    
    # Ensure date column is datetime
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
    
    print(f"Train set: {len(train_df)} rows ({train_df['date'].min()} to {train_df['date'].max()})")
    print(f"Val set:   {len(val_df)} rows ({val_df['date'].min()} to {val_df['date'].max()})")
    print(f"Test set:  {len(test_df)} rows ({test_df['date'].min()} to {test_df['date'].max()})")
    
    return train_df, val_df, test_df

def prepare_features(train_df, val_df, test_df):
    # Identify feature columns (exclude metadata and target)
    metadata_cols = [
        'symbol', 'date', 'entry_time', 'exit_time', 
        'entry_price', 'exit_price', 'shares', 'net_pnl', 'target'
    ]
    feature_cols = [c for c in train_df.columns if c not in metadata_cols]
    
    print(f"\nPreparing {len(feature_cols)} features...")
    
    X_train = train_df[feature_cols]
    y_train = train_df['target']
    
    X_val = val_df[feature_cols]
    y_val = val_df['target']
    
    X_test = test_df[feature_cols]
    y_test = test_df['target']
    
    # Imputation (replace NaNs with median)
    imputer = SimpleImputer(strategy='median')
    X_train_imp = pd.DataFrame(imputer.fit_transform(X_train), columns=feature_cols)
    X_val_imp = pd.DataFrame(imputer.transform(X_val), columns=feature_cols)
    X_test_imp = pd.DataFrame(imputer.transform(X_test), columns=feature_cols)
    
    # Scaling (StandardScaler) - important for Logistic Regression
    scaler = StandardScaler()
    X_train_scaled = pd.DataFrame(scaler.fit_transform(X_train_imp), columns=feature_cols)
    X_val_scaled = pd.DataFrame(scaler.transform(X_val_imp), columns=feature_cols)
    X_test_scaled = pd.DataFrame(scaler.transform(X_test_imp), columns=feature_cols)
    
    # Save preprocessors
    joblib.dump(imputer, MODELS_DIR / "imputer.pkl")
    joblib.dump(scaler, MODELS_DIR / "scaler.pkl")
    
    return X_train_scaled, y_train, X_val_scaled, y_val, X_test_scaled, y_test, feature_cols

def evaluate_model(model, X, y, model_name, threshold=0.5):
    # Predict probabilities
    if hasattr(model, "predict_proba"):
        y_prob = model.predict_proba(X)[:, 1]
    else:
        y_prob = model.predict(X)
        
    # Predict classes based on threshold
    y_pred = (y_prob >= threshold).astype(int)
    
    # Calculate metrics
    auc = roc_auc_score(y, y_prob)
    acc = accuracy_score(y, y_pred)
    prec = precision_score(y, y_pred, zero_division=0)
    rec = recall_score(y, y_pred, zero_division=0)
    f1 = f1_score(y, y_pred, zero_division=0)
    
    print(f"\n--- {model_name} Performance (Val) ---")
    print(f"AUC:       {auc:.4f}")
    print(f"Accuracy:  {acc:.4f}")
    print(f"Precision: {prec:.4f} (Win Rate of predicted trades)")
    print(f"Recall:    {rec:.4f}")
    print(f"F1 Score:  {f1:.4f}")
    print(f"Trades:    {sum(y_pred)} (out of {len(y)})")
    
    return {
        'Model': model_name,
        'AUC': auc,
        'Accuracy': acc,
        'Precision': prec,
        'Recall': rec,
        'F1': f1,
        'Trades': sum(y_pred)
    }

def train_logistic_regression(X_train, y_train, X_val, y_val):
    print("\nTraining Logistic Regression...")
    model = LogisticRegression(max_iter=1000, class_weight='balanced', random_state=42)
    model.fit(X_train, y_train)
    
    # Save model
    joblib.dump(model, MODELS_DIR / "logistic_regression.pkl")
    
    return model

def train_lightgbm(X_train, y_train, X_val, y_val):
    print("\nTraining LightGBM...")
    
    # LightGBM handles class imbalance via scale_pos_weight
    # Ratio of negative to positive samples
    neg_pos_ratio = (len(y_train) - sum(y_train)) / sum(y_train)
    
    model = lgb.LGBMClassifier(
        n_estimators=1000,
        learning_rate=0.05,
        max_depth=5,
        num_leaves=31,
        scale_pos_weight=neg_pos_ratio,
        random_state=42,
        verbose=-1
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        eval_metric='auc',
        callbacks=[lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(100)]
    )
    
    # Save model
    joblib.dump(model, MODELS_DIR / "lightgbm.pkl")
    
    return model

def train_xgboost(X_train, y_train, X_val, y_val):
    print("\nTraining XGBoost...")
    
    neg_pos_ratio = (len(y_train) - sum(y_train)) / sum(y_train)
    
    model = xgb.XGBClassifier(
        n_estimators=1000,
        learning_rate=0.05,
        max_depth=5,
        scale_pos_weight=neg_pos_ratio,
        random_state=42,
        eval_metric='auc',
        early_stopping_rounds=50
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=100
    )
    
    # Save model
    joblib.dump(model, MODELS_DIR / "xgboost.pkl")
    
    return model

def plot_feature_importance(model, feature_cols, model_name):
    if hasattr(model, 'feature_importances_'):
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1]
        
        top_n = 20
        plt.figure(figsize=(10, 8))
        plt.title(f"Top {top_n} Features - {model_name}")
        plt.barh(range(top_n), importances[indices[:top_n]], align="center")
        plt.yticks(range(top_n), [feature_cols[i] for i in indices[:top_n]])
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig(RESULTS_DIR / f"feature_importance_{model_name.lower()}.png")
        print(f"Saved feature importance plot to results/feature_importance_{model_name.lower()}.png")

def main():
    # 1. Load and Split
    train_df, val_df, test_df = load_and_split_data()
    
    # 2. Prepare Features
    X_train, y_train, X_val, y_val, X_test, y_test, feature_cols = prepare_features(train_df, val_df, test_df)
    
    results = []
    
    # 3. Train Logistic Regression
    lr_model = train_logistic_regression(X_train, y_train, X_val, y_val)
    results.append(evaluate_model(lr_model, X_val, y_val, "LogisticRegression"))
    
    # 4. Train LightGBM
    lgb_model = train_lightgbm(X_train, y_train, X_val, y_val)
    results.append(evaluate_model(lgb_model, X_val, y_val, "LightGBM"))
    plot_feature_importance(lgb_model, feature_cols, "LightGBM")
    
    # 5. Train XGBoost
    xgb_model = train_xgboost(X_train, y_train, X_val, y_val)
    results.append(evaluate_model(xgb_model, X_val, y_val, "XGBoost"))
    plot_feature_importance(xgb_model, feature_cols, "XGBoost")
    
    # 6. Save Results
    results_df = pd.DataFrame(results)
    print("\n=== FINAL RESULTS (Validation Set) ===")
    print(results_df)
    results_df.to_csv(RESULTS_DIR / "baseline_model_comparison.csv", index=False)

if __name__ == "__main__":
    main()
