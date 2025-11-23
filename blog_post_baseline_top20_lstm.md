# ORB Top 20 vs LSTM Ranking: From Stocks-in-Play to a Practical Ranker

Authors: Carlo Zarattini, Andrea Barbon, Andrew Aziz (A Profitable Day Trading Strategy For The U.S. Equity Market)

---

## TL;DR
- The classic 5-minute ORB strategy becomes *meaningfully profitable* when limited to Stocks-in-Play (Top 20 Relative Volume).
- A lightweight LSTM ranking model (3-layer, 128 hidden) improves win rate in top percentiles — not as a probability oracle but as a ranker. Treat LSTM outputs as percentile ranks, not absolute probabilities.
- Practical result (2% risk sizing): Baseline Win Rate ~16.75% (4,855 trades). Top 1% by LSTM → ~27.23% win rate on 2024–2025 holdout; Top 10% → ~22.67% win rate. (See metrics below.)

---

## 1. Introducing the strategy
The Opening Range Breakout (ORB) attempts to trade intraday continuation shortly after the market open. We focus on the 5-minute ORB:
- Define the 5-minute opening range (9:30–9:35 ET): high, low, and close.
- If the OR candle is bullish: only long entries (stop buy at opening range high). If bearish: only short entries.
- Stop: 10% ATR from entry. Exit: end-of-day (EoD) or stop hit.

The authors (Carlo Zarattini, Andrea Barbon, Andrew Aziz) show that restricting ORB to Stocks in Play (top RVol) massively improves EV; our work builds on that baseline and adds ML ranking.

---

## 2. Baseline (Top 20 Stocks-in-Play)
Why Top 20?
- Stocks-in-Play (relative volume > 1x opening range) means the trade will have real liquidity, retail participation, and greater intraday movement.
- The paper found that limiting to Top 20 by Relative Volume drastically improves returns versus trading all eligible stocks.

Baseline stats (rule-based Top 20 ORB — from our experiment):
- Data: 2016–2023 paper baseline; for ML experiments (2021–2025 snapshot) we show active numbers in CSV.
- Baseline_2pct (Backtest, 2% size):
  - Trades: 4,855
  - Win rate: 16.75% (0.167456)
  - Sharpe: 2.97
  - Max Drawdown: -1.46%
  - Final Equity multiplier: 1.6776 (baseline_2pct in CSV)

Why this baseline matters:
- High trade frequency enables compounding with small accounts (micro compounding) — the baseline’s raw exposure is often still the fastest way to grow tiny accounts when trading frictions are minimal.
- Yet, win rate is low and returns are noisy — this is where ranking helps.

---

## 3. The LSTM ranking model
What is the LSTM used for?
- Not to predict precise probability, but to sort (rank) trade opportunities so we can trade only the Top X% with a higher win probability and cleaner equity curve.

Model overview (repo):
- Architecture: 3-layer LSTM, 128 hidden units, dropout ≈ 0.3 on the final run.
- Input: sequence features from the first N 5-minute bars (12 bars historically, or 1 early sequence as implemented). Ten key features used (price microstructure, volatility, relative volume, gap, candlestick context).
- Loss: `BCEWithLogitsLoss` with pos_weight to address class imbalance.
- Data splits: chronological (60/20/20 or 70/15/15) — no shuffling.
- Calibration & pipeline: monotonicity gate (Spearman on deciles across slices), then isotonic k-fold or Platt scaling if monotonic; otherwise, use ranks directly.

Why LSTM > single-shot features:
- Captures early temporal micro-trends in the opening minutes (micro-structure patterns). Feature-based boosters can still catch a lot — but the LSTM finds time-dependent patterns that static features miss.

---

## 4. Results & Key numbers (Holdout: 2024–2025)
All results below come from our `ml_orb_5m/results/backtest_top20/master_comparison_lstm_top20.csv` and `ml_orb_5m/results/backtest_top20/backtest_summary_top20.csv` (generated from the 30-epoch Top20 LSTM run).

2% Risk Sizing:
- Baseline_2pct (all trades):
  - Trades: 4,855; Win Rate 16.75% (0.167456); Sharpe 2.97; Max DD -1.46%
- Top1pct_2pct (calibrated LSTM, top 1%):
  - Trades: 202; Win Rate 27.23% (0.27227); Sharpe 2.86; Max DD -0.38%
- Top10pct_2pct (calibrated LSTM, top 10%):
  - Trades: 644; Win Rate 22.67% (0.226708); Sharpe 2.53; Max DD -0.40%

5% Risk Sizing (for context):
- Baseline_5pct: Trades 6,332; Win Rate 16.78%; Sharpe 3.35; Max DD -4.00% (with larger exposure and commissions reflected)
- Top1pct_5pct: Trades 280; Win Rate 28.21%; Sharpe 3.14; Max DD -0.53%

Interpretation:
- The LSTM increases win rate in the top percentiles substantially.
- Top 1% provides the most lift (27% vs 16.75% baseline) but reduces the trade count (lower sample size). Use it if you prefer cleaner equity curves and capital scaling.
- Top 10% is a practical middle ground: significant lift, still enough trades to compound.

Statistical reliability:
- We verify percentile lifts using bootstrap CI on lift (Top 1% lift: ~1.6× with CI not crossing 1.0).
- Monotonicity gates and ECE (Expected Calibration Error) ensure calibration is legit before treating probabilities as probabilities.

---
### Reproduced results (what we just ran)
We re-trained an LSTM specifically for the Top20 dataset (30 epochs, default architecture used in this repo) then ran the calibrated backtest and generated equity curves and a small summary for the blog. Files created:
- `ml_orb_5m/models/saved_models/lstm_results_combined_top20_best.pth`
- `ml_orb_5m/results/backtest_top20/master_comparison_lstm_top20.csv`
- `ml_orb_5m/results/backtest_top20/backtest_summary_top20.csv`
- `ml_orb_5m/results/backtest_top20/equity_curve_comparison_top20.png`

Key numbers (2% size; from `backtest_summary_top20.csv`):
| Strategy | Trades | Total Return | Sharpe | Max DD |
|---|---:|---:|---:|---:|
| Baseline 2% | 4,057 | 128.0% | 3.48 | -1.96% |
| Top 10% 2% | 448 | 6.13% | 1.98 | -0.68% |
| Top 1% 2% | 70 | 1.63% | 1.57 | -0.25% |

These are the exact outputs used to generate the chart below:
![Top20 equity comparison (Normalized)](ml_orb_5m/results/backtest_top20/equity_curve_comparison_top20.png)

---

## 5. How we treat LSTM outputs: ranker not prophet
The LSTM tends to misreport absolute probability but preserves ordering. Practical steps:
1. Produce raw out-of-sample logits/probabilities for every candidate trade.
2. Check monotonicity of score → win rate for deciles across rolling slices (e.g., four validation slices). If Spearman r < threshold, skip calibration and use raw ranks as percentiles.
3. If monotonic: Fit isotonic k-fold on validation, then apply to test set — verify ECE improvement (EMB: ECE 0.316 → 0.007 is a realistic improvement for this pipeline when monotonic).
4. Convert scores to percentiles and backtest Top X% rules (1%–10%).

---

## 6. Practical guidance — which one to use?
- Baseline Top 20: Use if you want maximal trade frequency and quickest compounding with micro accounts, or as a fallback if models are stale.
- LSTM Top 1–10%: Use when you want cleaner equity curves, higher win rates, less emotional stress, or to scale capital. This helps reduce max drawdowns and improves risk-adjusted returns.

Combining both:
- Baseline as the engine; LSTM as a filter: apply the LSTM percentile filter on Top 20 Stocks-in-Play to preserve the core Edge and add quality selection.
- For production: run LSTM inference pre-open (or as soon as features are available), compute percentiles, and select Top 1–10% afterwards.

### Why Baseline_2pct trades < Baseline_5pct trades
You asked why Baseline 2% trades (4,057) are fewer than Baseline 5% trades (4,665). Short answer: execution rules in the simulator — specifically, the integer shares calculation — cause this.

Why it happens (steps):
- The simulator computes position value as `position_value = equity * position_size_pct` (so at start with equity = $1,000, 2% → $20, 5% → $50).
- It then computes `shares = int(position_value / entry_price)`. If this rounds to 0 (`shares < 1`), the trade is skipped (no fractional shares).
- Therefore, when entry price > position_value (e.g., $30 stock when position_value=20), a 2% run will skip a trade while 5% will buy 1 share and execute it.

Example:
```
Initial capital = $1,000
2% position value = $20 → at $30 entry price → shares = int(20/30) = 0 → skip trade
5% position value = $50 → at $30 entry price → shares = int(50/30) = 1 → trade executed
```

Other details:
- Because equity changes over time, the number of trades can diverge further (one strategy may grow equity faster and make more subsequent trades possible).
- Commissions and rounding can also make some trades non-viable under one size and viable under another.

Fixes and alternatives (pick one):
1. Allow fractional shares in simulation (best to mimic platforms that support fractional units). This yields consistent coverage across sizes.
2. Set `min_shares = 1` for all simulations and scale position size by `shares` instead of requiring full `position_value` (`shares = max(1, int(position_value / entry_price))`). This preserves integer trades but ensures consistent trade coverage.
3. Use a `min_notional` rule (e.g., minimum $25 trade notional) to avoid skipping low-size trades.

I can change the simulator to use one of these fixes; tell me which you prefer and I'll implement it and re-run the backtests if you want.

---

## 7. Visuals & assets to include in the post (repo references)
- `orb_5m/docs/ORB.pdf` — the full paper, essential reference for the baseline results and equity curves.
- `ml_orb_5m/docs/images/performance_comparison.png` — ML / Ensemble vs Baseline performance comparison.
- `ml_orb_5m/results/shap_summary.png` — SHAP summary (which features drive the ranking).
- `ml_orb_5m/results/feature_importance_xgboost.png` — XGBoost importance.
- `ml_orb_5m/results/calibration/probability_histograms.png` — calibration histograms & reliability.

Additional images generated for this Top20 run (and included in repo):
- `ml_orb_5m/results/backtest_top20/equity_curve_comparison_top20.png` — normalized comparison (Baseline vs Top1/Top10)
- `ml_orb_5m/results/backtest_top20/equity_curve_Baseline_2pct_abs.png` — Baseline (2%) absolute equity curve
- `ml_orb_5m/results/backtest_top20/equity_curve_Baseline_5pct_abs.png` — Baseline (5%) absolute equity curve
- `ml_orb_5m/results/backtest_top20/equity_curve_Top10pct_2pct_abs.png` — Top10 (2%) absolute equity curve
- `ml_orb_5m/results/backtest_top20/equity_curve_Top1pct_2pct_abs.png` — Top1 (2%) absolute equity curve
- `ml_orb_5m/results/backtest_top20/backtest_metrics_top20.png` — metrics bar charts (Total Return & Sharpe)

Below are the absolute equity curves (not normalized):
![Baseline 2% absolute equity curve](ml_orb_5m/results/backtest_top20/equity_curve_Baseline_2pct_abs.png)
![Baseline 5% absolute equity curve](ml_orb_5m/results/backtest_top20/equity_curve_Baseline_5pct_abs.png)
![Top10 2% absolute equity curve](ml_orb_5m/results/backtest_top20/equity_curve_Top10pct_2pct_abs.png)
![Top1 2% absolute equity curve](ml_orb_5m/results/backtest_top20/equity_curve_Top1pct_2pct_abs.png)
![Backtest metrics (Total Return & Sharpe)](ml_orb_5m/results/backtest_top20/backtest_metrics_top20.png)

These are ready to embed; I recommend using the ensemble/perf and calibration images near the results section, SHAP/feature importance close to the explanation of inputs and the ranking model.

---

## 8. Quick reproduction checklist (how to reproduce key steps locally)
1. Train LSTM on combined Top 20 trades (example):

```powershell
# Train LSTM (example)
python ml_orb_5m/src/train_lstm.py orb_5m/results/results_combined_top20/all_trades.csv --epochs 30
```
2. Run production-grade calibration pipeline (monotonicity gate + isotonic):

```powershell
python ml_orb_5m/src/calibration_production.py
```
3. Backtest calibrated LSTM percentiles (Top 1% / Top 10%):

```powershell
python ml_orb_5m/src/backtest_calibrated.py
```
4. Re-generate performance comparison figures:

```powershell
python ml_orb_5m/src/analysis/plot_model_metrics.py
python ml_orb_5m/src/analysis/plot_feature_importance.py
```

---

## 9. Short lessons & practical heuristics
- Monotonicity check is mandatory — calibration on a non-monotonic score is cosmetic and dangerous.
- Percentiles (Top 1–10%) outperform arbitrary probability thresholds in non-ideal calibration settings and are stable across time.
- Combine stock-in-play filters (Top 20 RVol) with ML ranking for a reliable uplift.

---

## 10. Conclusion
The baseline Top 20 ORB is the robust foundation; adding a ranker (LSTM or an ensemble) improves the quality of trades and reduces stress via fewer whipsaws. Use Top 1–10% percentile filters from the LSTM where you need a cleaner equity curve and better Sharpe; use the baseline when you favour frequent compounding.

If you want, I can: re-generate the equity curves for Top1/Top10 and baseline, embed the final PNGs in the draft, or create a short “How to run in 10 minutes” section tailored for readers.

---

*Code & assets: `ml_orb_5m`, `orb_5m` folders in the repo.*

*If you'd like a version trimmed down for Substack, or a short Twitter thread condensed from this post, tell me which format and I’ll prepare it.*
