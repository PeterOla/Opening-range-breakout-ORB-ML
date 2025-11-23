# ML-Enhanced ORB Strategy

## Project Overview
This project applies Machine Learning (XGBoost + Logistic Regression Ensemble) to the classic Opening Range Breakout (ORB) strategy. The goal is to filter out low-probability trades and improve the Win Rate and Profit Factor.

## Key Results (2024-2025)
- **Win Rate**: Improved from **15.6%** (Baseline) to **28.9%** (ML).
- **Profit Factor**: Increased from **1.82** to **2.48**.
- **Risk**: Max Drawdown reduced by **50%**.

## Documentation
- [Dual Model Results (Final Strategy)](docs/dual_model_results.md) - **READ THIS FIRST**. Summary of the final Long/Short split strategy.
- [Model Analysis & Feature Importance](docs/model_analysis.md) - Analysis of the initial single model.
- [Project Plan](plan.md) - Development roadmap and status.

## Usage
1. **Train Models**: `python src/models/train_dual_models.py`
2. **Run Backtest**: `python src/backtest/ml_backtest_dual.py`

## Results locations & conventions
- Models: `ml_orb_5m/models/saved_models/` (pickles / weights)
- Backtests: `ml_orb_5m/results/backtest/` (general backtest outputs)
- Top20-specific outputs: `ml_orb_5m/results/backtest_top20/`

If you find results in the repo root, please use the `scripts/enforce_result_paths.ps1` script to move them into canonical locations; or run `scripts/move_root_results_to_ml.ps1` to copy older results safely.
