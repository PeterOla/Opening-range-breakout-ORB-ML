# Results & Models: Naming & Canonical Paths

This document lists the canonical locations for all experiment models and backtest outputs. Use the paths below when writing new artifacts to avoid scattered files in the repo root or experiment directories.

Canonical folders

- Models (pickles / weights):
  - `ml_orb_5m/models/saved_models/`
  - Examples: `xgb_context_short_model.pkl`, `logreg_context_short_model.pkl`, `lstm_results_combined_top20_best.pth`

- General ML results & analysis:
  - `ml_orb_5m/results/`
    - `ml_orb_5m/results/backtest/` - Backtests for Top50 and general experiments
    - `ml_orb_5m/results/backtest_top20/` - Top20-specific backtest outputs and plots
    - `ml_orb_5m/results/calibration/` - Calibration model and diagnostic outputs
    - `ml_orb_5m/results/shap/` or `shap_importance.png` and other analysis images

- Baseline/Rule-based results (ORB):
  - `orb_5m/core/results/` - Baseline backtest outputs and plot images

Guidelines

- For scripts that produce outputs, they must create the canonical folder if not present and write to the path rather than the repo root.
- Use `PROJECT_ROOT` in scripts to build path (simplest consistent pattern below):
  ```python
  from pathlib import Path
  PROJECT_ROOT = Path(__file__).parent.parent.parent
  output_dir = PROJECT_ROOT / "ml_orb_5m" / "results" / "backtest"
  output_dir.mkdir(parents=True, exist_ok=True)
  df.to_csv(output_dir / "equity_curve_Baseline_6pct.csv", index=False)
  ```

- Prefer descriptive names: `equity_curve_{strategy_name}.csv`, `trade_log_{strategy_name}.csv`, `master_comparison_*.csv`

Enforcement & Cleanups

- If you find files like `equity_curve_*.csv` or `trade_log_*.csv` at repo root, move them into the folder above (and optionally archive if duplicates exist). See `scripts/enforce_result_paths.ps1` for a helper script to do so.

If in doubt, ask when moving existing files; the `archived_nonessential/` folder is used for temporary safe storage.

Help & Contact

- If anything breaks after moving files, follow these steps:
  1. Run the backtest script with `--output_dir` or set `PROJECT_ROOT / ml_orb_5m / results / backtest` explicitly.
  2. Regenerate required CSVs with the script that owns the logic (usually `ml_orb_5m/src/backtest_*`)
  3. Report issues or raise a PR if you need me to update defaults.
