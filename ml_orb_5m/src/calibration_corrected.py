import torch
import pandas as pd
import numpy as np
from pathlib import Path
import sys
from torch.utils.data import DataLoader
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ml_orb_5m.src.models.lstm_model import ORBLSTM
from ml_orb_5m.src.data.lstm_dataset import ORBSequenceDataset

def monotonicity_check(scores, labels, time_buckets, bucket_labels):
    """
    Check if higher scores consistently lead to higher win rates across time.
    This is the pre-requisite for calibration.
    """
    print("\n" + "="*80)
    print("MONOTONICITY CHECK ACROSS TIME BUCKETS")
    print("="*80)
    
    results = []
    
    for bucket_id, bucket_name in zip(np.unique(time_buckets), bucket_labels):
        mask = time_buckets == bucket_id
        bucket_scores = scores[mask]
        bucket_labels_data = labels[mask]
        
        # Split into deciles
        deciles = pd.qcut(bucket_scores, q=10, labels=False, duplicates='drop')
        
        decile_wr = []
        for d in range(10):
            if np.sum(deciles == d) > 0:
                wr = bucket_labels_data[deciles == d].mean()
                decile_wr.append(wr)
            else:
                decile_wr.append(np.nan)
        
        # Check monotonicity: Spearman correlation
        valid_idx = ~np.isnan(decile_wr)
        if valid_idx.sum() > 3:
            from scipy.stats import spearmanr
            corr, pval = spearmanr(np.arange(10)[valid_idx], np.array(decile_wr)[valid_idx])
            
            results.append({
                'Period': bucket_name,
                'Samples': mask.sum(),
                'Spearman': corr,
                'P-value': pval,
                'Monotonic': corr > 0.5 and pval < 0.05,
                'Decile_WR': decile_wr
            })
        
    results_df = pd.DataFrame(results)
    
    print("\nMonotonicity Statistics:")
    print(results_df[['Period', 'Samples', 'Spearman', 'P-value', 'Monotonic']].to_string(index=False))
    
    # Overall verdict
    if results_df['Monotonic'].mean() >= 0.75:
        print("\n✓ PASS: Ranking is stable across time (>=75% periods monotonic)")
        print("  → Calibration is JUSTIFIED")
        return True, results_df
    else:
        print("\n✗ FAIL: Ranking is unstable across time (<75% periods monotonic)")
        print("  → Calibration will NOT help. Use as ranking engine only.")
        return False, results_df

def percentile_analysis(scores, labels, pnl, time_info):
    """
    Analyze performance by percentile bands (distribution-agnostic).
    """
    print("\n" + "="*80)
    print("PERCENTILE BAND ANALYSIS")
    print("="*80)
    
    df = pd.DataFrame({
        'score': scores,
        'label': labels,
        'pnl': pnl,
        'year': time_info
    })
    
    # Define percentile bands
    df['percentile'] = pd.qcut(df['score'], q=10, labels=[f'P{i*10}-{(i+1)*10}' for i in range(10)], duplicates='drop')
    
    # Overall statistics
    overall = df.groupby('percentile').agg({
        'label': ['count', 'mean'],
        'pnl': ['mean', 'sum']
    }).round(4)
    
    overall.columns = ['Count', 'Win_Rate', 'Avg_PnL', 'Total_PnL']
    overall['EV_per_Trade'] = overall['Total_PnL'] / overall['Count']
    
    baseline_wr = df['label'].mean()
    overall['Lift'] = overall['Win_Rate'] / baseline_wr
    
    print("\nOverall Performance by Percentile Band:")
    print(overall.to_string())
    
    # Stability check: Does top band maintain edge over time?
    df['is_top20'] = df['score'] >= df['score'].quantile(0.80)
    
    temporal_stability = df.groupby(['year', 'is_top20'])['label'].mean().unstack()
    if temporal_stability.shape[1] == 2:
        temporal_stability.columns = ['Bottom_80%', 'Top_20%']
        temporal_stability['Lift'] = temporal_stability['Top_20%'] / temporal_stability['Bottom_80%']
        
        print("\nTemporal Stability of Top 20%:")
        print(temporal_stability.to_string())
        
        # Bootstrap on lift
        lifts = temporal_stability['Lift'].dropna()
        if len(lifts) >= 3:
            print(f"\nLift Statistics (Top 20%):")
            print(f"  Mean: {lifts.mean():.3f}")
            print(f"  Std:  {lifts.std():.3f}")
            print(f"  Min:  {lifts.min():.3f}")
            print(f"  Max:  {lifts.max():.3f}")
            
            if lifts.min() > 1.0:
                print("  ✓ Lift is consistently positive across all periods")
            else:
                print("  ✗ WARNING: Lift is not stable (some periods < 1.0)")
    
    return overall, temporal_stability if temporal_stability.shape[1] == 2 else None

def calibration_pipeline(trades_file: str, model_path: str, output_dir: str):
    """
    Correct calibration workflow:
    1. Check monotonicity across time
    2. If pass, apply Isotonic calibration
    3. Test percentile bands (not fixed thresholds)
    4. Validate on separate window
    """
    print("="*80)
    print("CALIBRATION PIPELINE (CORRECTED WORKFLOW)")
    print("="*80)
    
    # 1. Load Dataset
    print("\nLoading Dataset...")
    dataset = ORBSequenceDataset(trades_file)
    
    # Split: 60% train / 20% val / 20% test
    # Val is for calibration fitting
    # Test is for final reporting
    train_size = int(len(dataset) * 0.60)
    val_size = int(len(dataset) * 0.20)
    
    train_dataset = torch.utils.data.Subset(dataset, range(0, train_size))
    val_dataset = torch.utils.data.Subset(dataset, range(train_size, train_size + val_size))
    test_dataset = torch.utils.data.Subset(dataset, range(train_size + val_size, len(dataset)))
    
    print(f"Split: Train={len(train_dataset)}, Val={len(val_dataset)}, Test={len(test_dataset)}")
    
    # 2. Load Model & Get Predictions
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = ORBLSTM(input_dim=10, hidden_dim=128, num_layers=3, output_dim=1).to(device)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    
    def get_predictions(subset):
        loader = DataLoader(subset, batch_size=256, shuffle=False)
        probs, labels = [], []
        
        with torch.no_grad():
            for X, y in loader:
                X = X.to(device)
                out = model(X)
                probs.extend(torch.sigmoid(out).cpu().numpy().flatten())
                labels.extend(y.numpy())
        
        return np.array(probs), np.array(labels)
    
    print("\nRunning inference...")
    val_scores, val_labels = get_predictions(val_dataset)
    test_scores, test_labels = get_predictions(test_dataset)
    
    # 3. Load Trade Metadata
    df = pd.read_csv(trades_file)
    
    if hasattr(dataset, 'indices'):
        val_indices = [dataset.indices[i] for i in val_dataset.indices]
        test_indices = [dataset.indices[i] for i in test_dataset.indices]
        
        df_val = df.iloc[val_indices].copy()
        df_test = df.iloc[test_indices].copy()
        
        df_val['entry_time'] = pd.to_datetime(df_val['entry_time'])
        df_test['entry_time'] = pd.to_datetime(df_test['entry_time'])
        
        val_pnl = df_val['net_pnl'].values
        test_pnl = df_test['net_pnl'].values
        
        val_time = df_val['entry_time'].dt.to_period('Q').astype(str).values
        test_time = df_test['entry_time'].dt.year.values
    else:
        print("WARNING: Cannot map to trade metadata. Using synthetic data.")
        val_pnl = np.where(val_labels == 1, 10, -10)
        test_pnl = np.where(test_labels == 1, 10, -10)
        val_time = np.repeat(['Q1', 'Q2', 'Q3', 'Q4'], len(val_labels) // 4 + 1)[:len(val_labels)]
        test_time = np.repeat([2024, 2025], len(test_labels) // 2 + 1)[:len(test_labels)]
    
    # 4. STEP 1: Monotonicity Check (on Validation set)
    val_time_buckets = pd.Categorical(val_time).codes
    val_time_labels = pd.Categorical(val_time).categories.tolist()
    
    is_monotonic, monotonicity_df = monotonicity_check(
        val_scores, val_labels, val_time_buckets, val_time_labels
    )
    
    # 5. STEP 2: If Monotonic, Apply Isotonic Calibration
    if is_monotonic:
        print("\n" + "="*80)
        print("APPLYING ISOTONIC CALIBRATION")
        print("="*80)
        
        iso_model = IsotonicRegression(out_of_bounds='clip')
        iso_model.fit(val_scores, val_labels)
        
        # Calibrate test scores
        test_scores_calibrated = iso_model.transform(test_scores)
        
        # Evaluate calibration improvement
        print("\nCalibration Metrics (Test Set):")
        print(f"  Raw Log Loss:        {log_loss(test_labels, test_scores):.4f}")
        print(f"  Calibrated Log Loss: {log_loss(test_labels, test_scores_calibrated):.4f}")
        print(f"  Raw Brier Score:     {brier_score_loss(test_labels, test_scores):.4f}")
        print(f"  Calibrated Brier:    {brier_score_loss(test_labels, test_scores_calibrated):.4f}")
        
        # Use calibrated scores for analysis
        final_scores = test_scores_calibrated
    else:
        print("\n⚠ SKIPPING CALIBRATION: Use raw scores as ranking signal only.")
        final_scores = test_scores
    
    # 6. STEP 3: Percentile Band Analysis (on Test set)
    percentile_stats, temporal_stability = percentile_analysis(
        final_scores, test_labels, test_pnl, test_time
    )
    
    # 7. Save Results
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Save monotonicity check
    if 'monotonicity_df' in locals():
        monotonicity_df.to_csv(output_path / "monotonicity_check.csv", index=False)
    
    # Save percentile stats
    percentile_stats.to_csv(output_path / "percentile_bands.csv")
    
    if temporal_stability is not None:
        temporal_stability.to_csv(output_path / "temporal_stability.csv")
    
    # Export calibrated scores for backtesting
    df_test['raw_score'] = test_scores
    df_test['calibrated_score'] = final_scores
    df_test['percentile_rank'] = pd.qcut(final_scores, q=10, labels=False, duplicates='drop')
    
    df_test[['entry_time', 'symbol', 'raw_score', 'calibrated_score', 'percentile_rank']].to_csv(
        output_path / "test_predictions.csv", index=False
    )
    
    print(f"\n✓ Results saved to {output_path}")
    print("="*80)

if __name__ == "__main__":
    trades_file = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top50" / "all_trades.csv"
    model_path = PROJECT_ROOT / "ml_orb_5m" / "models" / "saved_models" / "lstm_results_combined_top50_best.pth"
    output_dir = PROJECT_ROOT / "ml_orb_5m" / "results" / "calibration_corrected"
    
    calibration_pipeline(str(trades_file), str(model_path), str(output_dir))
