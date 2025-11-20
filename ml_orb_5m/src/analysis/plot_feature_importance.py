import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import joblib
import json
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
MODELS_DIR = BASE_DIR / "models" / "saved_models"
CONFIG_PATH = BASE_DIR / "config" / "selected_features.json"
OUTPUT_DIR = BASE_DIR / "docs" / "images"

def main():
    # Load config for feature names
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    features = config["final_selected_features"]
    
    # Load model
    print("Loading model...")
    ensemble = joblib.load(MODELS_DIR / "ensemble_model.pkl")
    
    # Extract XGBoost model from VotingClassifier
    # The estimators are stored in 'estimators_' attribute as a list of (name, estimator)
    # or directly accessible via named_estimators_ if available (scikit-learn version dependent)
    
    xgb_model = None
    for name, model in ensemble.named_estimators_.items():
        if 'xgb' in name.lower():
            xgb_model = model
            break
            
    if xgb_model is None:
        print("Could not find XGBoost model in ensemble.")
        return

    # Get feature importances
    importances = xgb_model.feature_importances_
    
    # Create DataFrame
    feat_imp = pd.DataFrame({
        'Feature': features,
        'Importance': importances
    }).sort_values('Importance', ascending=False)
    
    print("\nTop 10 Features:")
    print(feat_imp.head(10))
    
    # Plot
    plt.figure(figsize=(12, 8))
    sns.barplot(x='Importance', y='Feature', data=feat_imp.head(15), palette='viridis')
    plt.title('Top 15 Features Driving the ORB ML Model', fontsize=16)
    plt.xlabel('Relative Importance (XGBoost Gain)', fontsize=12)
    plt.ylabel('Feature', fontsize=12)
    plt.tight_layout()
    
    # Save
    output_path = OUTPUT_DIR / "feature_importance.png"
    plt.savefig(output_path, dpi=300)
    print(f"\nFeature importance plot saved to: {output_path}")

if __name__ == "__main__":
    main()
