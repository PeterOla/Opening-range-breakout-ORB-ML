Set-Location -LiteralPath 'C:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)'

if (-Not (Test-Path 'archived_nonessential')) {
    New-Item -Path 'archived_nonessential' -ItemType Directory | Out-Null
}

$items = @(
    'ai_strategy',
    'ml_orb_5m/src/models/train_ensemble.py',
    'ml_orb_5m/src/models/train_core_models.py',
    'ml_orb_5m/src/models/feature_selection.py',
    'ml_orb_5m/src/backtest/ml_backtest_dual.py',
    'ml_orb_5m/src/backtest/ml_backtest.py',
    'ml_orb_5m/src/analysis/plot_dual_model_analysis.py',
    'ml_orb_5m/src/analysis/analyze_missed_winners.py',
    'ml_orb_5m/test-plan.md',
    'ml_orb_5m/test_one_row_complete.py',
    'ml_orb_5m/test_single_trade.py',
    'ml_orb_5m/test_new_features.py',
    'orb_5m/results/results_combined_top50',
    'experiments_plan.md'
)

foreach ($i in $items) {
    if (Test-Path $i) {
        Write-Output ("Archiving: {0}" -f $i)
        Move-Item -LiteralPath $i -Destination 'archived_nonessential' -Force -Verbose
    } else {
        Write-Output ("Not found (skipping): {0}" -f $i)
    }
}
