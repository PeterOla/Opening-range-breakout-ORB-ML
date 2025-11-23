"""
Generate charts for Dual Model Analysis
"""
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

def get_xgb_importance(model):
    # Extract XGBoost from VotingClassifier
    xgb_model = None
    for name, est in model.named_estimators_.items():
        if 'xgb' in name.lower():
            xgb_model = est
            break
    if xgb_model:
        return xgb_model.feature_importances_
    return None

def plot_feature_comparison(features):
    print("Generating Feature Importance Comparison...")
    
    # Load models
    long_model = joblib.load(MODELS_DIR / "long_model.pkl")
    short_model = joblib.load(MODELS_DIR / "short_model.pkl")
    
    long_imp = get_xgb_importance(long_model)
    short_imp = get_xgb_importance(short_model)
    
    if long_imp is None or short_imp is None:
        print("Could not extract feature importances.")
        return

    # Create DataFrame
    df = pd.DataFrame({
        'Feature': features,
        'Long_Importance': long_imp,
        'Short_Importance': short_imp
    })
    
    # Calculate difference to find most divergent features
    df['Diff'] = abs(df['Long_Importance'] - df['Short_Importance'])
    df = df.sort_values('Diff', ascending=False).head(15)
    
    # Melt for plotting
    df_melt = df.melt(id_vars='Feature', value_vars=['Long_Importance', 'Short_Importance'], var_name='Model', value_name='Importance')
    
    plt.figure(figsize=(12, 8))
    sns.barplot(x='Importance', y='Feature', hue='Model', data=df_melt, palette={'Long_Importance': 'green', 'Short_Importance': 'red'})
    plt.title('Feature Importance Divergence: Long vs Short Models', fontsize=16)
    plt.xlabel('Relative Importance', fontsize=12)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "dual_model_features.png")
    print(f"Saved feature comparison to {OUTPUT_DIR / 'dual_model_features.png'}")

def plot_performance_comparison():
    print("Generating Performance Comparison...")
    
    # Data from previous runs
    data = {
        'Strategy': ['Baseline', 'Single Model (0.6)', 'Dual Model (0.6)'],
        'Win Rate': [15.6, 28.9, 29.5],
        'Profit Factor': [1.82, 2.48, 2.67],
        'Max Drawdown': [-5.1, -2.4, -1.8]
    }
    df = pd.DataFrame(data)
    
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    
    # Win Rate
    sns.barplot(x='Strategy', y='Win Rate', data=df, ax=axes[0], palette='Blues')
    axes[0].set_title('Win Rate (%)', fontsize=14)
    axes[0].set_ylim(0, 35)
    for i, v in enumerate(df['Win Rate']):
        axes[0].text(i, v + 0.5, f"{v}%", ha='center', fontweight='bold')
        
    # Profit Factor
    sns.barplot(x='Strategy', y='Profit Factor', data=df, ax=axes[1], palette='Greens')
    axes[1].set_title('Profit Factor', fontsize=14)
    axes[1].set_ylim(0, 3.0)
    for i, v in enumerate(df['Profit Factor']):
        axes[1].text(i, v + 0.05, f"{v}", ha='center', fontweight='bold')

    # Drawdown (Inverted for visual comparison)
    df['DD_Positive'] = df['Max Drawdown'].abs()
    sns.barplot(x='Strategy', y='DD_Positive', data=df, ax=axes[2], palette='Reds')
    axes[2].set_title('Max Drawdown (Lower is Better)', fontsize=14)
    axes[2].set_ylabel('Drawdown %')
    for i, v in enumerate(df['Max Drawdown']):
        axes[2].text(i, abs(v) + 0.1, f"{v}%", ha='center', fontweight='bold')
        
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "performance_comparison.png")
    print(f"Saved performance comparison to {OUTPUT_DIR / 'performance_comparison.png'}")

def main():
    # Load feature names
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    features = config["final_selected_features"]
    
    plot_feature_comparison(features)
    plot_performance_comparison()

if __name__ == "__main__":
    main()
