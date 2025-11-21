# Opening Range Breakout (ORB) Project

Core implementation of ORB scanning, trade generation, and now an ML-based ranking filter to improve selection quality.

## ML Ranking Filter (LSTM)
A production-grade LSTM acts as a trade *ranking* engine (NOT a probability oracle). It increases win rate in top percentiles while preserving stable drawdowns.

### Documentation
- Detailed pipeline: `ml_orb_5m/docs/ML_RankingPipeline.md`
- Blog / narrative draft: `blog_post_substack.md`

### Usage
```bash
# Train
python ml_orb_5m/src/train_lstm.py orb_5m/results/results_combined_top50/all_trades.csv --epochs 30

# Calibrate (monotonicity gate + k-fold isotonic)
python ml_orb_5m/src/calibration_production.py

# Backtest percentile strategies (Top 1%, Top 10%)
python ml_orb_5m/src/backtest_calibrated.py
```

### Retained Core Files
- `ml_orb_5m/src/models/lstm_model.py`
- `ml_orb_5m/src/data/lstm_dataset.py`
- `ml_orb_5m/src/train_lstm.py`
- `ml_orb_5m/src/calibration_production.py`
- `ml_orb_5m/src/backtest_calibrated.py`

Legacy experimental scripts (early calibration attempts, slow feature generation, older backtest) were removed to reduce noise.

### Key Interpretation Rules
- Use percentile bands (Top 5–10%) rather than raw probability thresholds.
- Probabilities are *relative edge scores* post-calibration.
- Re-calibrate monthly; re-train quarterly or after regime shifts.

### Next Enhancements (Roadmap)
- Multi-task head (win flag + PnL magnitude)
- Attention for interpretability
- Regime features (VIX percentile, SPY slope)
- Lightweight ensemble (seed & feature subsets)

### Monitoring Checklist
- Weekly: Win rate lift of traded percentile vs baseline.
- Monthly: Calibration drift (ECE + reliability diagram).
- Quarterly: Temporal lift stability (bootstrap CI refresh).

---
For full experimental rationale and metrics, see `ml_orb_5m/docs/ML_RankingPipeline.md`.
