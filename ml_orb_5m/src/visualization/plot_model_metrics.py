import pandas as pd
import numpy as np
import joblib
import json
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from sklearn.metrics import roc_curve, auc

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_PATH = BASE_DIR / "data" / "features" / "all_features.parquet"
MODELS_DIR = BASE_DIR / "models" / "saved_models"
CONFIG_PATH = BASE_DIR / "config" / "selected_features.json"
OUTPUT_DIR = BASE_DIR / "reports" / "figures"

# Ensure output dir
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_data_and_features():
    print("Loading data...")
    df = pd.read_parquet(DATA_PATH)
    df['date'] = pd.to_datetime(df['date'])
    
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    features = config["no_market_context_features"]
    
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
    df = df[df['side'] != 'unknown'].copy()
    df['target'] = (df['net_pnl'] > 0).astype(int)
    
    # Train set only for these plots (as per training script)
    train_mask = df['date'] < pd.to_datetime("2024-01-01")
    train_df = df[train_mask].copy()
    
    return train_df, features

def plot_roc_curve(model, X, y, side_name):
    y_prob = model.predict_proba(X)[:, 1]
    fpr, tpr, _ = roc_curve(y, y_prob)
    roc_auc = auc(fpr, tpr)
    
    plt.figure(figsize=(8, 6))
    plt.plot(fpr, tpr, color='darkorange', lw=2, label=f'ROC curve (area = {roc_auc:.2f})')
    plt.plot([0, 1], [0, 1], color='navy', lw=2, linestyle='--')
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.05])
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title(f'{side_name} Model ROC Curve (No Market Context)')
    plt.legend(loc="lower right")
    plt.grid(True)
    
    save_path = OUTPUT_DIR / f"roc_curve_{side_name.lower()}_no_context.png"
    plt.savefig(save_path)
    print(f"Saved ROC curve to {save_path}")
    plt.close()

def plot_feature_importance(model, features, side_name):
    # Extract XGBoost from VotingClassifier
    # Named 'xgb' in the ensemble
    xgb_model = model.named_estimators_['xgb']
    
    importances = xgb_model.feature_importances_
    indices = np.argsort(importances)[::-1]
    
    plt.figure(figsize=(10, 8))
    plt.title(f'{side_name} Feature Importances (No Market Context)')
    plt.barh(range(len(indices)), importances[indices], align='center')
    plt.yticks(range(len(indices)), [features[i] for i in indices])
    plt.xlabel('Relative Importance')
    plt.gca().invert_yaxis() # Highest importance at top
    plt.tight_layout()
    
    save_path = OUTPUT_DIR / f"feature_importance_{side_name.lower()}_no_context.png"
    plt.savefig(save_path)
    print(f"Saved Feature Importance to {save_path}")
    plt.close()

def main():
    df, features = load_data_and_features()
    
    for side in ['Long', 'Short']:
        print(f"Processing {side}...")
        side_df = df[df['side'] == side.lower()]
        X = side_df[features]
        y = side_df['target']
        
        # Load artifacts
        model_path = MODELS_DIR / f"{side.lower()}_model.pkl"
        imputer_path = MODELS_DIR / f"{side.lower()}_imputer.pkl"
        scaler_path = MODELS_DIR / f"{side.lower()}_scaler.pkl"
        
        if not model_path.exists():
            print(f"Model not found for {side}")
            continue
            
        model = joblib.load(model_path)
        imputer = joblib.load(imputer_path)
        scaler = joblib.load(scaler_path)
        
        # Transform data
        X_imp = imputer.transform(X)
        X_scaled = scaler.transform(X_imp)
        
        # Plot
        plot_roc_curve(model, X_scaled, y, side)
        plot_feature_importance(model, features, side)

if __name__ == "__main__":
    main()
