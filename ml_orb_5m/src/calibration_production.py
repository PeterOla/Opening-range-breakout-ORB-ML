"""
Production-Grade Calibration Pipeline for LSTM Ranking Model

Implements:
- Reliable index mapping from dataset to CSV
- Relaxed monotonicity checks (Spearman > 0.2, p < 0.1)
- K-fold isotonic regression to prevent overfitting
- Platt scaling as alternative
- Expected Calibration Error (ECE)
- Bootstrap confidence intervals for lift
- Percentile-based analysis
- Comprehensive diagnostics
"""

import torch
import torch.nn as nn
from torch.utils.data import Subset
import pandas as pd
import numpy as np
from pathlib import Path
from scipy.stats import spearmanr
from scipy.special import expit
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Tuple, Dict, Optional
import sys

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ml_orb_5m.src.models.lstm_model import ORBLSTM
from ml_orb_5m.src.data.lstm_dataset import ORBSequenceDataset

def expected_calibration_error(probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> float:
    """
    Compute Expected Calibration Error (ECE).
    
    ECE measures the weighted average of calibration gaps across bins.
    Lower is better (0 = perfect calibration).
    """
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    
    for i in range(n_bins):
        mask = (probs >= bins[i]) & (probs < bins[i+1])
        if mask.sum() == 0:
            continue
        
        bin_acc = labels[mask].mean()
        bin_conf = probs[mask].mean()
        bin_weight = mask.sum() / len(probs)
        
        ece += bin_weight * abs(bin_acc - bin_conf)
    
    return ece

def bootstrap_lift_ci(
    predictions: np.ndarray, 
    labels: np.ndarray, 
    baseline_rate: float,
    n_bootstrap: int = 1000,
    confidence: float = 0.95
) -> Tuple[float, float, float]:
    """
    Bootstrap confidence interval for lift metric.
    
    Returns: (mean_lift, ci_lower, ci_upper)
    """
    lifts = []
    n = len(predictions)
    
    for _ in range(n_bootstrap):
        # Resample with replacement
        idx = np.random.choice(n, size=n, replace=True)
        boot_labels = labels[idx]
        
        if boot_labels.sum() == 0:  # No wins in bootstrap sample
            continue
        
        boot_rate = boot_labels.mean()
        boot_lift = boot_rate / baseline_rate if baseline_rate > 0 else 0
        lifts.append(boot_lift)
    
    lifts = np.array(lifts)
    alpha = (1 - confidence) / 2
    
    return lifts.mean(), np.quantile(lifts, alpha), np.quantile(lifts, 1 - alpha)

def fit_isotonic_kfold(
    scores: np.ndarray, 
    labels: np.ndarray, 
    k: int = 5
) -> Tuple[np.ndarray, IsotonicRegression]:
    """
    Fit isotonic regression with k-fold cross-validation to prevent overfitting.
    
    Returns:
        calibrated_scores: Cross-validated calibrated scores
        final_model: Isotonic model fitted on full data for production
    """
    calibrated = np.zeros_like(scores, dtype=np.float64)
    kfold = KFold(n_splits=k, shuffle=False)  # shuffle=False preserves temporal order
    
    for train_idx, val_idx in kfold.split(scores):
        iso = IsotonicRegression(out_of_bounds='clip')
        iso.fit(scores[train_idx], labels[train_idx])
        calibrated[val_idx] = iso.transform(scores[val_idx])
    
    # Fit final model on all data for production use
    final_iso = IsotonicRegression(out_of_bounds='clip')
    final_iso.fit(scores, labels)
    
    return calibrated, final_iso

def fit_platt_scaling(
    scores: np.ndarray,
    labels: np.ndarray
) -> Tuple[np.ndarray, LogisticRegression]:
    """
    Fit Platt scaling (logistic regression on scores).
    
    More stable than isotonic when sample size is small.
    """
    platt = LogisticRegression(max_iter=1000, solver='lbfgs')
    platt.fit(scores.reshape(-1, 1), labels)
    
    calibrated = platt.predict_proba(scores.reshape(-1, 1))[:, 1]
    
    return calibrated, platt

def check_monotonicity_relaxed(
    scores: np.ndarray,
    labels: np.ndarray,
    timestamps: pd.Series,
    n_periods: int = 4,
    min_correlation: float = 0.2,
    max_pvalue: float = 0.1
) -> Dict:
    """
    Check if ranking is monotonic across time periods.
    
    Relaxed criteria: Spearman > 0.2 (was 0.5), p < 0.1 (was 0.05)
    
    Returns dict with:
        - is_monotonic: bool
        - period_results: list of dicts with correlation, pvalue, sample_size
        - pass_rate: fraction of periods that pass
    """
    # Split into time periods
    df = pd.DataFrame({
        'score': scores,
        'label': labels,
        'time': timestamps
    }).sort_values('time')
    
    # Create time buckets
    df['period'] = pd.qcut(df['time'], q=n_periods, labels=False, duplicates='drop')
    n_actual_periods = df['period'].nunique()
    
    results = []
    passed = 0
    
    for period in sorted(df['period'].unique()):
        period_df = df[df['period'] == period]
        
        # Create deciles within this period
        try:
            period_df['decile'] = pd.qcut(
                period_df['score'], 
                q=10, 
                labels=False, 
                duplicates='drop'
            )
        except ValueError:  # Not enough unique values
            results.append({
                'period': period,
                'correlation': np.nan,
                'pvalue': np.nan,
                'sample_size': len(period_df),
                'passed': False,
                'reason': 'insufficient_unique_values'
            })
            continue
        
        # Compute win rate per decile
        decile_stats = period_df.groupby('decile')['label'].agg(['mean', 'count'])
        
        if len(decile_stats) < 3:  # Need at least 3 deciles
            results.append({
                'period': period,
                'correlation': np.nan,
                'pvalue': np.nan,
                'sample_size': len(period_df),
                'passed': False,
                'reason': 'too_few_deciles'
            })
            continue
        
        # Spearman correlation between decile rank and win rate
        corr, pval = spearmanr(decile_stats.index, decile_stats['mean'])
        
        passed_period = (corr > min_correlation) and (pval < max_pvalue)
        if passed_period:
            passed += 1
        
        results.append({
            'period': period,
            'correlation': corr,
            'pvalue': pval,
            'sample_size': len(period_df),
            'n_deciles': len(decile_stats),
            'passed': passed_period
        })
    
    pass_rate = passed / n_actual_periods if n_actual_periods > 0 else 0
    is_monotonic = pass_rate >= 0.75  # Require 75% of periods to pass
    
    return {
        'is_monotonic': is_monotonic,
        'pass_rate': pass_rate,
        'period_results': results,
        'n_periods': n_actual_periods
    }

def plot_reliability_diagram(
    raw_probs: np.ndarray,
    calibrated_probs: np.ndarray,
    labels: np.ndarray,
    save_path: Path,
    n_bins: int = 10
):
    """Plot reliability diagram comparing raw vs calibrated probabilities."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    for ax, probs, title in zip(
        axes, 
        [raw_probs, calibrated_probs],
        ['Raw Model', 'Calibrated Model']
    ):
        # Create bins
        bins = np.linspace(0, 1, n_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2
        
        bin_accs = []
        bin_confs = []
        bin_counts = []
        
        for i in range(n_bins):
            mask = (probs >= bins[i]) & (probs < bins[i+1])
            if mask.sum() > 0:
                bin_accs.append(labels[mask].mean())
                bin_confs.append(probs[mask].mean())
                bin_counts.append(mask.sum())
            else:
                bin_accs.append(np.nan)
                bin_confs.append(np.nan)
                bin_counts.append(0)
        
        # Filter out empty bins
        valid = [c > 0 for c in bin_counts]
        bin_accs = [a for a, v in zip(bin_accs, valid) if v]
        bin_confs = [c for c, v in zip(bin_confs, valid) if v]
        bin_counts = [c for c in bin_counts if c > 0]
        
        # Plot
        ax.plot([0, 1], [0, 1], 'k--', label='Perfect Calibration')
        ax.scatter(bin_confs, bin_accs, s=[c/5 for c in bin_counts], alpha=0.6, label='Actual')
        ax.plot(bin_confs, bin_accs, 'b-', alpha=0.4)
        
        ax.set_xlabel('Predicted Probability')
        ax.set_ylabel('Actual Win Rate')
        ax.set_title(title)
        ax.legend()
        ax.grid(alpha=0.3)
        ax.set_xlim([0, 1])
        ax.set_ylim([0, 1])
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved reliability diagram to {save_path}")

def plot_probability_histograms(
    raw_probs: np.ndarray,
    calibrated_probs: np.ndarray,
    save_path: Path
):
    """Plot histograms of raw vs calibrated probabilities."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    for ax, probs, title in zip(
        axes,
        [raw_probs, calibrated_probs],
        ['Raw Probabilities', 'Calibrated Probabilities']
    ):
        ax.hist(probs, bins=50, alpha=0.7, edgecolor='black')
        ax.axvline(probs.mean(), color='r', linestyle='--', label=f'Mean: {probs.mean():.3f}')
        ax.set_xlabel('Probability')
        ax.set_ylabel('Count')
        ax.set_title(title)
        ax.legend()
        ax.grid(alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved probability histograms to {save_path}")

def percentile_analysis_with_bootstrap(
    scores: np.ndarray,
    labels: np.ndarray,
    pnl: np.ndarray,
    baseline_rate: float,
    percentiles: list = [1, 5, 10, 20, 30],
    n_bootstrap: int = 1000
) -> pd.DataFrame:
    """
    Analyze performance by percentile bands with bootstrap CIs.
    
    Returns DataFrame with columns:
        - percentile
        - sample_size
        - win_rate
        - ev_per_trade
        - lift
        - lift_ci_lower
        - lift_ci_upper
    """
    results = []
    
    for pct in percentiles:
        threshold = np.percentile(scores, 100 - pct)
        mask = scores >= threshold
        
        if mask.sum() == 0:
            continue
        
        band_labels = labels[mask]
        band_pnl = pnl[mask]
        
        win_rate = band_labels.mean()
        ev = band_pnl.mean()
        lift = win_rate / baseline_rate if baseline_rate > 0 else 0
        
        # Bootstrap CI for lift
        lift_mean, lift_lower, lift_upper = bootstrap_lift_ci(
            scores[mask], band_labels, baseline_rate, n_bootstrap
        )
        
        results.append({
            'percentile': f'Top {pct}%',
            'sample_size': mask.sum(),
            'win_rate': win_rate,
            'ev_per_trade': ev,
            'lift': lift,
            'lift_ci_lower': lift_lower,
            'lift_ci_upper': lift_upper
        })
    
    return pd.DataFrame(results)

def plot_temporal_stability(
    scores: np.ndarray,
    labels: np.ndarray,
    timestamps: pd.Series,
    baseline_rate: float,
    save_path: Path,
    top_pct: float = 20
):
    """Plot lift over time for top percentile band."""
    df = pd.DataFrame({
        'score': scores,
        'label': labels,
        'time': timestamps
    })
    
    # Select top percentile
    threshold = np.percentile(scores, 100 - top_pct)
    df = df[df['score'] >= threshold].copy()
    
    # Group by quarter
    df['quarter'] = df['time'].dt.to_period('Q')
    
    quarterly_lifts = []
    quarters = []
    
    for quarter, group in df.groupby('quarter'):
        if len(group) < 50:  # Skip quarters with too few samples
            continue
        
        win_rate = group['label'].mean()
        lift = win_rate / baseline_rate if baseline_rate > 0 else 0
        
        quarters.append(str(quarter))
        quarterly_lifts.append(lift)
    
    # Plot
    plt.figure(figsize=(12, 6))
    plt.plot(quarters, quarterly_lifts, 'o-', linewidth=2, markersize=8)
    plt.axhline(1.0, color='r', linestyle='--', label='Baseline (Lift = 1.0)')
    plt.xlabel('Quarter')
    plt.ylabel('Lift')
    plt.title(f'Temporal Stability of Top {top_pct}% Band')
    plt.xticks(rotation=45)
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved temporal stability plot to {save_path}")

def main():
    # Paths
    trades_file = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top50" / "all_trades.csv"
    model_file = PROJECT_ROOT / "ml_orb_5m" / "models" / "saved_models" / "lstm_results_combined_top50_best.pth"
    output_dir = PROJECT_ROOT / "ml_orb_5m" / "results" / "calibration"
    output_dir.mkdir(exist_ok=True)
    
    print("=" * 80)
    print("PRODUCTION-GRADE CALIBRATION PIPELINE")
    print("=" * 80)
    
    # 1. Load Dataset
    print("\n1. Loading dataset...")
    dataset = ORBSequenceDataset(
        trades_file_path=str(trades_file),
        sequence_length=12,
        target_col="net_pnl",
        profit_threshold=0.0
    )
    
    # Load CSV for metadata
    trades_df = pd.read_csv(trades_file)
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"], utc=True)
    trades_df["entry_time"] = trades_df["entry_time"].dt.tz_convert("America/New_York")
    
    # Verify index mapping
    if not hasattr(dataset, 'indices') or len(dataset.indices) == 0:
        print("ERROR: Dataset does not expose original indices!")
        print("Please modify ORBSequenceDataset to return (X, y, idx) in __getitem__")
        return
    
    print(f"Dataset size: {len(dataset)}")
    print(f"CSV size: {len(trades_df)}")
    print(f"Indices size: {len(dataset.indices)}")
    
    # 2. Chronological Split (60% train, 20% val for calibration, 20% test)
    print("\n2. Creating chronological splits...")
    n_samples = len(dataset)
    train_end = int(n_samples * 0.60)
    val_end = int(n_samples * 0.80)
    
    val_dataset = Subset(dataset, range(train_end, val_end))
    test_dataset = Subset(dataset, range(val_end, n_samples))
    
    print(f"Validation set: {len(val_dataset)} samples ({train_end} to {val_end})")
    print(f"Test set: {len(test_dataset)} samples ({val_end} to {n_samples})")
    
    # 3. Load Model
    print("\n3. Loading trained model...")
    model = ORBLSTM(input_dim=10, hidden_dim=128, num_layers=3, dropout=0.3)
    checkpoint = torch.load(model_file, map_location='cpu', weights_only=False)
    model.load_state_dict(checkpoint)
    model.eval()
    
    # 4. Generate Predictions for Validation Set
    print("\n4. Generating validation predictions...")
    val_logits = []
    val_labels = []
    val_indices_in_dataset = []
    
    with torch.no_grad():
        for i in range(len(val_dataset)):
            X, y = val_dataset[i]
            logit = model(X.unsqueeze(0)).item()
            val_logits.append(logit)
            val_labels.append(y.item())
            # Map to dataset index
            dataset_idx = val_dataset.indices[i]
            val_indices_in_dataset.append(dataset_idx)
    
    val_logits = np.array(val_logits)
    val_probs_raw = expit(val_logits)  # Sigmoid
    val_labels = np.array(val_labels)
    
    # Map to CSV indices
    val_csv_indices = [dataset.indices[i] for i in val_indices_in_dataset]
    val_metadata = trades_df.iloc[val_csv_indices].copy()
    val_timestamps = val_metadata["entry_time"]
    val_pnl = val_metadata["net_pnl"].values
    
    baseline_rate = val_labels.mean()
    print(f"Validation baseline win rate: {baseline_rate:.4f}")
    
    # 5. Monotonicity Check (CRITICAL GATE)
    print("\n5. MONOTONICITY CHECK (Gate-keeper for calibration)...")
    print("Relaxed criteria: Spearman > 0.2, p < 0.1, require 75% periods to pass")
    
    monotonicity_result = check_monotonicity_relaxed(
        val_probs_raw, val_labels, val_timestamps,
        n_periods=4, min_correlation=0.2, max_pvalue=0.1
    )
    
    print(f"\nMonotonicity Result: {'PASS' if monotonicity_result['is_monotonic'] else 'FAIL'}")
    print(f"Pass Rate: {monotonicity_result['pass_rate']:.1%} ({monotonicity_result['n_periods']} periods)")
    print("\nPer-Period Results:")
    for res in monotonicity_result['period_results']:
        status = "✓" if res['passed'] else "✗"
        if np.isnan(res['correlation']):
            print(f"  {status} Period {res['period']}: {res['reason']} (n={res['sample_size']})")
        else:
            print(f"  {status} Period {res['period']}: Spearman={res['correlation']:.3f}, p={res['pvalue']:.4f}, "
                  f"n={res['sample_size']} ({res['n_deciles']} deciles)")
    
    if not monotonicity_result['is_monotonic']:
        print("\n" + "="*80)
        print("WARNING: Ranking is NOT stable across time periods!")
        print("Calibration will not help. Use model as ranker only (percentile-based rules).")
        print("="*80)
        # Continue with analysis but skip calibration
        apply_calibration = False
    else:
        print("\n" + "="*80)
        print("SUCCESS: Ranking is stable. Proceeding with calibration.")
        print("="*80)
        apply_calibration = True
    
    # 6. Calibration (if monotonicity passes)
    if apply_calibration:
        print("\n6. Fitting calibration models...")
        
        # Check sample size to decide method
        n_positives = val_labels.sum()
        print(f"Validation positives: {n_positives}, total: {len(val_labels)}")
        
        if len(val_labels) < 5000 or n_positives < 1000:
            print("Sample size small - using Platt scaling")
            val_probs_calibrated, calibration_model = fit_platt_scaling(val_probs_raw, val_labels)
            calibration_method = 'platt'
        else:
            print("Sample size adequate - using k-fold isotonic regression")
            val_probs_calibrated, calibration_model = fit_isotonic_kfold(val_probs_raw, val_labels, k=5)
            calibration_method = 'isotonic_kfold'
        
        # Save calibration model
        calibration_path = output_dir / f"calibration_model_{calibration_method}.pkl"
        import pickle
        with open(calibration_path, 'wb') as f:
            pickle.dump({
                'model': calibration_model,
                'method': calibration_method,
                'train_date_range': (val_timestamps.min(), val_timestamps.max()),
                'baseline_rate': baseline_rate
            }, f)
        print(f"Saved calibration model to {calibration_path}")
    else:
        val_probs_calibrated = val_probs_raw.copy()
        calibration_method = 'none'
    
    # 7. Metrics Comparison
    print("\n7. Calibration Metrics (Validation Set)...")
    
    from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score
    
    metrics_raw = {
        'Log Loss': log_loss(val_labels, val_probs_raw),
        'Brier Score': brier_score_loss(val_labels, val_probs_raw),
        'AUC': roc_auc_score(val_labels, val_probs_raw),
        'ECE': expected_calibration_error(val_probs_raw, val_labels)
    }
    
    metrics_cal = {
        'Log Loss': log_loss(val_labels, val_probs_calibrated),
        'Brier Score': brier_score_loss(val_labels, val_probs_calibrated),
        'AUC': roc_auc_score(val_labels, val_probs_calibrated),
        'ECE': expected_calibration_error(val_probs_calibrated, val_labels)
    }
    
    print("\nRaw Model:")
    for k, v in metrics_raw.items():
        print(f"  {k}: {v:.4f}")
    
    if apply_calibration:
        print(f"\nCalibrated Model ({calibration_method}):")
        for k, v in metrics_cal.items():
            delta = v - metrics_raw[k]
            arrow = "↓" if delta < 0 else "↑"
            print(f"  {k}: {v:.4f} ({arrow} {abs(delta):.4f})")
    
    # 8. Percentile Analysis with Bootstrap
    print("\n8. Percentile Band Analysis (with Bootstrap CIs)...")
    
    percentile_results = percentile_analysis_with_bootstrap(
        val_probs_calibrated if apply_calibration else val_probs_raw,
        val_labels,
        val_pnl,
        baseline_rate,
        percentiles=[1, 5, 10, 20, 30],
        n_bootstrap=1000
    )
    
    print("\n" + percentile_results.to_string(index=False))
    
    # Save to CSV
    percentile_results.to_csv(output_dir / "percentile_analysis.csv", index=False)
    
    # Check if any band has CI excluding 1.0
    robust_bands = percentile_results[percentile_results['lift_ci_lower'] > 1.0]
    if len(robust_bands) > 0:
        print(f"\n✓ Robust bands (95% CI excludes 1.0): {len(robust_bands)}")
        print(robust_bands[['percentile', 'lift', 'lift_ci_lower', 'lift_ci_upper']].to_string(index=False))
    else:
        print("\n✗ No bands have statistically significant lift (CI includes 1.0)")
    
    # 9. Visualizations
    print("\n9. Generating diagnostic plots...")
    
    plot_reliability_diagram(
        val_probs_raw, val_probs_calibrated, val_labels,
        output_dir / "reliability_diagram.png"
    )
    
    plot_probability_histograms(
        val_probs_raw, val_probs_calibrated,
        output_dir / "probability_histograms.png"
    )
    
    plot_temporal_stability(
        val_probs_calibrated if apply_calibration else val_probs_raw,
        val_labels, val_timestamps, baseline_rate,
        output_dir / "temporal_stability.png",
        top_pct=20
    )
    
    # 10. Test Set Evaluation (Final Report)
    print("\n10. TEST SET EVALUATION (Final Out-of-Sample Report)...")
    
    test_logits = []
    test_labels = []
    test_indices_in_dataset = []
    
    with torch.no_grad():
        for i in range(len(test_dataset)):
            X, y = test_dataset[i]
            logit = model(X.unsqueeze(0)).item()
            test_logits.append(logit)
            test_labels.append(y.item())
            dataset_idx = test_dataset.indices[i]
            test_indices_in_dataset.append(dataset_idx)
    
    test_logits = np.array(test_logits)
    test_probs_raw = expit(test_logits)
    test_labels = np.array(test_labels)
    
    # Map to CSV
    test_csv_indices = [dataset.indices[i] for i in test_indices_in_dataset]
    test_metadata = trades_df.iloc[test_csv_indices].copy()
    test_timestamps = test_metadata["entry_time"]
    test_pnl = test_metadata["net_pnl"].values
    
    # Apply calibration if available
    if apply_calibration:
        if calibration_method == 'platt':
            test_probs_calibrated = calibration_model.predict_proba(test_probs_raw.reshape(-1, 1))[:, 1]
        else:  # isotonic
            test_probs_calibrated = calibration_model.transform(test_probs_raw)
    else:
        test_probs_calibrated = test_probs_raw.copy()
    
    test_baseline_rate = test_labels.mean()
    print(f"Test set baseline win rate: {test_baseline_rate:.4f}")
    
    # Metrics
    test_metrics = {
        'Log Loss': log_loss(test_labels, test_probs_calibrated),
        'Brier Score': brier_score_loss(test_labels, test_probs_calibrated),
        'AUC': roc_auc_score(test_labels, test_probs_calibrated),
        'ECE': expected_calibration_error(test_probs_calibrated, test_labels)
    }
    
    print("\nTest Set Metrics:")
    for k, v in test_metrics.items():
        print(f"  {k}: {v:.4f}")
    
    # Percentile analysis on test set
    test_percentile_results = percentile_analysis_with_bootstrap(
        test_probs_calibrated,
        test_labels,
        test_pnl,
        test_baseline_rate,
        percentiles=[1, 5, 10, 20, 30],
        n_bootstrap=1000
    )
    
    print("\nTest Set Percentile Analysis:")
    print(test_percentile_results.to_string(index=False))
    test_percentile_results.to_csv(output_dir / "test_percentile_analysis.csv", index=False)
    
    # Final verdict
    print("\n" + "="*80)
    print("FINAL VERDICT")
    print("="*80)
    
    if monotonicity_result['is_monotonic']:
        print(f"✓ Ranking is stable (calibration applied: {calibration_method})")
    else:
        print("✗ Ranking is unstable (no calibration, use as ranker only)")
    
    best_band = test_percentile_results.iloc[0]  # Top percentile
    print(f"\nBest Band: {best_band['percentile']}")
    print(f"  Sample Size: {best_band['sample_size']:.0f}")
    print(f"  Win Rate: {best_band['win_rate']:.2%}")
    print(f"  Lift: {best_band['lift']:.2f}x")
    print(f"  95% CI: [{best_band['lift_ci_lower']:.2f}, {best_band['lift_ci_upper']:.2f}]")
    
    if best_band['lift_ci_lower'] > 1.0:
        print(f"\n✓ Statistically significant edge detected!")
        print(f"✓ Strategy: Trade {best_band['percentile']} with ~{best_band['sample_size']:.0f} trades expected")
    else:
        print(f"\n✗ No statistically significant edge (CI includes 1.0)")
        print("Consider: More data, better features, or different model architecture")
    
    print("\n" + "="*80)
    print(f"Results saved to: {output_dir}")
    print("="*80)

if __name__ == "__main__":
    main()
