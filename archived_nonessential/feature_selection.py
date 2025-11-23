"""
Feature Selection & Analysis
1. Correlation Analysis (remove redundant)
2. SHAP Analysis (interpretability)
3. Recursive Feature Elimination (RFE)
"""
import pandas as pd
import numpy as np
from pathlib import Path
import joblib
import matplotlib.pyplot as plt
import seaborn as sns
import shap
import xgboost as xgb
from sklearn.feature_selection import RFE
from sklearn.model_selection import TimeSeriesSplit

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_PATH = BASE_DIR / "data" / "features" / "all_features.parquet"
MODELS_DIR = BASE_DIR / "models" / "saved_models"
RESULTS_DIR = BASE_DIR / "results"
CONFIG_DIR = BASE_DIR / "config"

# Ensure directories exist
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def load_data():
    print(f"Loading data from {DATA_PATH}...")
    df = pd.read_parquet(DATA_PATH)
    df = df.sort_values('date').reset_index(drop=True)
    df['date'] = pd.to_datetime(df['date'])
    
    # Use Train + Val for feature selection (2021-2023)
    # Hold out Test (2024+) completely
    train_val_mask = df['date'] < pd.to_datetime("2024-01-01")
    df_train = df[train_val_mask].copy()
    
    metadata_cols = [
        'symbol', 'date', 'entry_time', 'exit_time', 
        'entry_price', 'exit_price', 'shares', 'net_pnl', 'target'
    ]
    feature_cols = [c for c in df.columns if c not in metadata_cols]
    
    X = df_train[feature_cols]
    y = df_train['target']
    
    # Fill NaNs
    X = X.fillna(X.median())
    
    print(f"Feature Selection Dataset: {len(X)} rows, {len(feature_cols)} features")
    return X, y, feature_cols

def correlation_analysis(X, threshold=0.95):
    print("\n--- Correlation Analysis ---")
    corr_matrix = X.corr().abs()
    
    # Select upper triangle of correlation matrix
    upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
    
    # Find features with correlation greater than threshold
    to_drop = [column for column in upper.columns if any(upper[column] > threshold)]
    
    print(f"Found {len(to_drop)} highly correlated features (> {threshold}):")
    print(to_drop)
    
    # Plot heatmap
    plt.figure(figsize=(12, 10))
    sns.heatmap(corr_matrix, cmap='coolwarm', vmax=1.0, vmin=0.0)
    plt.title("Feature Correlation Matrix")
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "correlation_heatmap.png")
    
    return to_drop

def shap_analysis(X, y, feature_cols):
    print("\n--- SHAP Analysis ---")
    
    # Train a quick XGBoost model for SHAP
    model = xgb.XGBClassifier(
        n_estimators=100, 
        max_depth=4, 
        learning_rate=0.1, 
        random_state=42,
        n_jobs=-1
    )
    model.fit(X, y)
    
    # Calculate SHAP values
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)
    
    # Summary Plot
    plt.figure(figsize=(10, 12))
    shap.summary_plot(shap_values, X, plot_type="bar", show=False, max_display=20)
    plt.title("SHAP Feature Importance")
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "shap_importance.png")
    plt.close()
    
    # Detailed Summary Plot (Dot plot)
    plt.figure(figsize=(10, 12))
    shap.summary_plot(shap_values, X, show=False, max_display=20)
    plt.title("SHAP Summary (Directionality)")
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "shap_summary.png")
    plt.close()
    
    # Get top features by mean absolute SHAP value
    mean_shap = np.abs(shap_values).mean(axis=0)
    shap_importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': mean_shap
    }).sort_values('importance', ascending=False)
    
    print("Top 10 Features by SHAP:")
    print(shap_importance.head(10))
    
    return shap_importance['feature'].tolist()

def recursive_feature_elimination(X, y, n_features_to_select=20):
    print(f"\n--- Recursive Feature Elimination (Target: {n_features_to_select}) ---")
    
    model = xgb.XGBClassifier(
        n_estimators=100, 
        max_depth=3, 
        learning_rate=0.1, 
        n_jobs=-1,
        random_state=42
    )
    
    rfe = RFE(estimator=model, n_features_to_select=n_features_to_select, step=1)
    rfe.fit(X, y)
    
    selected_features = X.columns[rfe.support_].tolist()
    
    print(f"Selected {len(selected_features)} features:")
    print(selected_features)
    
    return selected_features

def main():
    # 1. Load Data
    X, y, all_features = load_data()
    
    # 2. Correlation Analysis
    drop_corr = correlation_analysis(X)
    X_filtered = X.drop(columns=drop_corr)
    print(f"Remaining features after correlation filter: {len(X_filtered.columns)}")
    
    # 3. SHAP Analysis
    shap_ranked_features = shap_analysis(X_filtered, y, X_filtered.columns.tolist())
    
    # 4. RFE (Select Top 25)
    # We use the SHAP-ranked features to guide RFE or just run RFE on filtered set
    # Let's run RFE on the filtered set to get a robust subset
    final_features = recursive_feature_elimination(X_filtered, y, n_features_to_select=25)
    
    # 5. Save Selected Features
    import json
    feature_config = {
        "all_features": all_features,
        "dropped_correlation": drop_corr,
        "shap_ranking": shap_ranked_features,
        "final_selected_features": final_features
    }
    
    with open(CONFIG_DIR / "selected_features.json", "w") as f:
        json.dump(feature_config, f, indent=4)
        
    print(f"\nSaved feature configuration to {CONFIG_DIR / 'selected_features.json'}")

if __name__ == "__main__":
    main()
