import torch
import pandas as pd
import numpy as np
from pathlib import Path
import sys
from torch.utils.data import DataLoader
from sklearn.calibration import calibration_curve
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ml_orb_5m.src.models.lstm_model import ORBLSTM
from ml_orb_5m.src.data.lstm_dataset import ORBSequenceDataset

def calibration_analysis(trades_file: str, model_path: str, output_dir: str):
    """
    Comprehensive model evaluation including:
    - Calibration curves
    - Expected Value per confidence bucket
    - Lift vs baseline
    - Log loss
    - Reliability diagram data
    """
    print(f"--- CALIBRATION ANALYSIS: {Path(model_path).name} ---")
    
    # 1. Load Data & Model
    print("Loading Dataset...")
    dataset = ORBSequenceDataset(trades_file)
    
    # Use TEST SET ONLY (last 15% after proper 70/15/15 split)
    train_size = int(len(dataset) * 0.70)
    val_size = int(len(dataset) * 0.15)
    
    test_dataset = torch.utils.data.Subset(dataset, range(train_size + val_size, len(dataset)))
    loader = DataLoader(test_dataset, batch_size=128, shuffle=False)
    
    print(f"Test Set Size: {len(test_dataset)} samples")
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = ORBLSTM(input_dim=10, hidden_dim=128, num_layers=3, output_dim=1).to(device)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    
    # 2. Get Predictions
    all_probs = []
    all_labels = []
    
    print("Running Inference...")
    with torch.no_grad():
        for X_batch, y_batch in loader:
            X_batch = X_batch.to(device)
            outputs = model(X_batch)
            probs = torch.sigmoid(outputs).cpu().numpy().flatten()
            all_probs.extend(probs)
            all_labels.extend(y_batch.numpy())
            
    all_probs = np.array(all_probs)
    all_labels = np.array(all_labels)
    
    # 3. Load corresponding trade PnL for Expected Value
    print("Loading trade outcomes...")
    df = pd.read_csv(trades_file)
    
    # Map to test set indices
    if hasattr(dataset, 'indices'):
        test_indices = [dataset.indices[i] for i in test_dataset.indices]
        df_test = df.iloc[test_indices].copy()
        df_test['lstm_prob'] = all_probs
        df_test['lstm_label'] = all_labels
    else:
        print("Warning: Cannot map to PnL. Using binary labels only.")
        df_test = pd.DataFrame({
            'lstm_prob': all_probs,
            'lstm_label': all_labels,
            'net_pnl': np.where(all_labels == 1, 1, -1)  # Placeholder
        })
    
    # 4. Calculate Metrics
    results = {}
    
    # Baseline Win Rate
    baseline_win_rate = all_labels.mean()
    results['baseline_win_rate'] = baseline_win_rate
    
    # Log Loss (Lower is better)
    results['log_loss'] = log_loss(all_labels, all_probs)
    
    # Brier Score (Lower is better)
    results['brier_score'] = brier_score_loss(all_labels, all_probs)
    
    # AUC
    try:
        results['auc'] = roc_auc_score(all_labels, all_probs)
    except:
        results['auc'] = np.nan
    
    # 5. Calibration Curve
    print("\nCalculating Calibration Curve...")
    prob_true, prob_pred = calibration_curve(all_labels, all_probs, n_bins=10, strategy='quantile')
    
    calibration_df = pd.DataFrame({
        'predicted_prob': prob_pred,
        'actual_win_rate': prob_true,
        'calibration_error': np.abs(prob_true - prob_pred)
    })
    
    # Expected Calibration Error (ECE)
    results['ece'] = calibration_df['calibration_error'].mean()
    
    # 6. Confidence Bucket Analysis
    print("Analyzing by confidence bucket...")
    df_test['prob_bucket'] = pd.cut(df_test['lstm_prob'], bins=[0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0], 
                                     labels=['<30%', '30-40%', '40-50%', '50-60%', '60-70%', '>70%'])
    
    bucket_analysis = df_test.groupby('prob_bucket').agg({
        'lstm_label': ['count', 'mean'],
        'net_pnl': ['mean', 'sum']
    }).round(4)
    
    bucket_analysis.columns = ['Count', 'Win_Rate', 'Avg_PnL', 'Total_PnL']
    bucket_analysis['EV_per_Trade'] = bucket_analysis['Total_PnL'] / bucket_analysis['Count']
    bucket_analysis['Lift_vs_Base'] = bucket_analysis['Win_Rate'] / baseline_win_rate
    
    # 7. Print Summary
    print("\n" + "="*80)
    print("CALIBRATION & PERFORMANCE METRICS")
    print("="*80)
    print(f"Baseline Win Rate:       {baseline_win_rate:.2%}")
    print(f"Log Loss:                {results['log_loss']:.4f}")
    print(f"Brier Score:             {results['brier_score']:.4f}")
    print(f"AUC:                     {results['auc']:.4f}")
    print(f"Expected Calib Error:    {results['ece']:.4f}")
    print("\n" + "="*80)
    print("CALIBRATION CURVE")
    print("="*80)
    print(calibration_df.to_string(index=False))
    print("\n" + "="*80)
    print("CONFIDENCE BUCKET ANALYSIS")
    print("="*80)
    print(bucket_analysis.to_string())
    print("="*80)
    
    # 8. Save Results
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Save metrics
    pd.DataFrame([results]).to_csv(output_path / "calibration_metrics.csv", index=False)
    calibration_df.to_csv(output_path / "calibration_curve.csv", index=False)
    bucket_analysis.to_csv(output_path / "confidence_buckets.csv")
    
    print(f"\nResults saved to {output_path}")
    
    return results, calibration_df, bucket_analysis

if __name__ == "__main__":
    trades_file = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top50" / "all_trades.csv"
    model_path = PROJECT_ROOT / "ml_orb_5m" / "models" / "saved_models" / "lstm_results_combined_top50_best.pth"
    output_dir = PROJECT_ROOT / "ml_orb_5m" / "results" / "calibration_analysis"
    
    calibration_analysis(str(trades_file), str(model_path), str(output_dir))
