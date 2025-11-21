# ORB LSTM Ranking Pipeline Documentation

## 1. Purpose
A calibrated LSTM model to *rank* Opening Range Breakout (ORB) trade candidates, not to predict true probabilities. It filters opportunities to raise win rate and improve capital efficiency.

## 2. Core Components
- `lstm_model.py`: 3-layer LSTM (128 hidden) + FC head.
- `lstm_dataset.py`: Sequence builder (12×5m bars, 10 engineered features, chronological ordering).
- `train_lstm.py`: Chronological 60/20/20 split (now using 70/15/15 previously) with `BCEWithLogitsLoss(pos_weight)`.
- `calibration_production.py`: Monotonicity gate → k‑fold isotonic calibration → percentile lift analysis.
- `backtest_calibrated.py`: Out‑of‑sample (final 20%) trading simulation using calibrated percentiles (Top 1%, Top 10%).

## 3. Feature Set (10)
1. Normalised OHLC (relative to sequence start)
2. Log volume
3. RSI(14) scaled 0–1
4. ATR%(14)
5. Relative Volume (log1p of vol/rolling20)
6. Upper shadow ratio
7. Lower shadow ratio

(OHLC counted as four, giving total 10 features.)

## 4. Training Details
- Sequence length: 12 (first hour of market context).
- Loss: `BCEWithLogitsLoss(pos_weight≈4.46)` handles ~17% positives.
- Metric focus: Precision (win rate among filtered trades) over raw accuracy.
- Best validation precision: ~22% vs baseline ~16–17%.

## 5. Calibration Workflow
1. Validation set predictions (raw logits → sigmoid).
2. Monotonicity check across 4 time buckets (Spearman > 0.2, p < 0.1 in ≥75%).
3. If PASS → k-fold isotonic regression; else skip calibration.
4. Compute Log Loss, Brier Score, AUC, ECE (raw vs calibrated).
5. Generate reliability diagram, probability histograms, temporal lift plot.
6. Percentile bootstrap (Top 1/5/10/20/30%).

### Post-Calibration Improvements (Validation)
- Log Loss: 0.68 → 0.47
- Brier: 0.245 → 0.145
- ECE: 0.316 → 0.007
- AUC unchanged (~0.58) → Ranking preserved.

## 6. Out-of-Sample Backtest Results (Last 20%)
| Strategy | Win Rate | Trades | Sharpe | Max DD | Return (2% sizing) |
|----------|----------|--------|--------|--------|--------------------|
| Baseline | 16.75%   | 4,855  | 2.97   | -1.46% | 167.8%             |
| Top 10%  | 22.67%   |   644  | 2.53   | -0.40% | 4.9%               |
| Top 1%   | 27.23%   |   202  | 2.86   | -0.38% | 4.6%               |

(More capital ⇒ filtered strategies become attractive for risk control.)

## 7. File Retention / Cleanup
Removed legacy: `calibration_analysis.py`, `calibration_corrected.py`, `backtest_lstm.py`, slow `generate_price_action_features.py`.
Kept: `calibration_production.py`, `backtest_calibrated.py`, core model & dataset, fast feature generator.

## 8. Usage Commands
```bash
# Train
python ml_orb_5m/src/train_lstm.py orb_5m/results/results_combined_top50/all_trades.csv --epochs 30

# Calibrate
python ml_orb_5m/src/calibration_production.py

# Backtest calibrated strategies
python ml_orb_5m/src/backtest_calibrated.py
```

## 9. Interpretation Rules
- Do NOT read calibrated probabilities literally; treat as rank scores.
- Use percentile cuts (e.g. Top 5–10%) rather than fixed probability thresholds.
- Re-calibrate monthly; re-train quarterly or after regime shifts.

## 10. Extension Roadmap
- Multi-task head: Add regression for `net_pnl` magnitude.
- Attention layer for interpretability (bar-level weighting).
- Ensemble (different seeds/feature subsets) with rank averaging.
- Regime features (VIX percentile, SPY slope) for stability across volatility cycles.

## 11. Monitoring Suggestions
- Weekly: Win rate of traded percentile band vs baseline.
- Monthly: Calibration drift (ECE, reliability diagram).
- Quarterly: Temporal stability (lift by quarter) + bootstrap CI refresh.

## 12. Quick Decision Guide
| Goal | Recommended Action |
|------|--------------------|
| Max return on small acct | Baseline (all trades) |
| Improve win rate + low DD | Top 1–5% band |
| Balance trade count & lift | Top 10% band |
| Scale to larger capital | Combine Top 1–10% with dynamic sizing |

## 13. Key Takeaway
This is a **ranking filter**. Its power lies in lifting the win rate while preserving manageable drawdowns. Treat outputs as *relative edge scores*, not literal probabilities.
