# Turning an ORB Scanner into a Ranking Engine (Not a Fortune Teller)

*How a miscalibrated LSTM went from "lying confidently" to a statistically robust filter that actually improves trade selection.*

---
## 1. The Starting Point
I began with a simple goal: take a noisy Opening Range Breakout (ORB) strategy with ~16% win rate and use machine learning to filter trades. The first LSTM looked good on paper (85% accuracy) yet predicted *zero winners*. Classic collapse: the model learned to always say "lose" because the class imbalance made that locally optimal.

So I fixed imbalance the naive way: weighted sampling. That broke temporal ordering and produced prettier training logs but fake generalisation. I was *optimising the spreadsheet*, not the edge.

---
## 2. The Reframe: Ranking > Probability
The real breakthrough came when I stopped treating the model as a probability oracle. Its raw outputs said things like 0.60 (60% chance of win) but the actual win rate of those trades was ~27%. Disastrous calibration — but those 27% trades were still **1.6× better** than baseline. The scores were *comparative information*. The model was a **ranking engine**.

Once that clicked, the whole pipeline changed:
- Stop obsessing over predicted probabilities.
- Focus on lift: win rate in top X% vs overall.
- Guard calibration with a monotonicity test first (is the ranking stable over time?).

---
## 3. Engineering the Real Pipeline
| Phase | What Changed | Why It Matters |
|-------|--------------|----------------|
| Architecture | 3-layer LSTM, 128 hidden | Enough capacity without overkill |
| Features | Expanded to 10 (structure + volatility + volume context) | Captures trade microstructure |
| Split | Chronological 60/20/20 (then 70/15/15) | Prevents temporal leakage |
| Loss | `BCEWithLogitsLoss(pos_weight)` | Handles imbalance honestly |
| Calibration | Monotonicity → k-fold isotonic | Prevents fitting garbage |
| Evaluation | Percentile bootstrap | Quantifies robustness (CI excluding 1.0) |

---
## 4. Monotonicity as a Gatekeeper
Before any calibration, I force the model to prove its ranking is stable across time slices (Spearman correlation of decile ranks vs win rate). If ranking wobbles, calibration just makes wrong numbers cleaner.

Result: **100% pass across 4 validation periods** (correlations 0.74–0.92). That gave me licence to calibrate.

---
## 5. Calibration Done Properly
Raw vs calibrated (validation set):
- Log Loss: 0.68 → **0.47**
- Brier Score: 0.245 → **0.145**
- ECE: 0.316 → **0.007**
- AUC: ~0.58 → unchanged ≈**0.58** (ranking preserved)

Important: AUC not amazing. This isn’t a perfect discriminator; it’s a *useful sorter*.

---
## 6. What Actually Improves?
Out-of-sample (last 20% of time-ordered trades):

| Strategy (2% size) | Trades | Win Rate | Lift vs Base | Sharpe | Max DD |
|--------------------|--------|----------|--------------|--------|--------|
| Baseline (all)     | 4,855  | 16.75%   | 1.00×        | 2.97   | -1.46% |
| Top 10%            |   644  | 22.67%   | 1.35×        | 2.53   | -0.40% |
| Top 1%             |   202  | 27.23%   | 1.63×        | 2.86   | -0.38% |

Bootstrap CI for Top 1% lift: **[1.46, 2.06]** → statistically real.

Trade-off:
- Baseline compounds faster with micro-sized account.
- Top 1–10% gives cleaner equity curve, higher hit rate, lower stress. Ideal for scaling capital or discretionary hybrid overlays.

---
## 7. Why Not Chase Even Higher Win Rate?
Because shrinking the sample too far invites variance collapse. A 35% win rate on 40 trades means nothing if next month regime shifts. Percentiles let you tune risk appetite dynamically while keeping statistical footing.

---
## 8. What This Model Is NOT
- NOT a pricing model.
- NOT a timing model.
- NOT a regime classifier.

It is a **signal strength model**. Input: early sequence features. Output: relative edge score. Use it to *rank*, then layer execution logic (spreads, slippage controls, cancel conditions).

---
## 9. How to Use It in Production
1. Generate predictions pre-open (or first hour rolling).
2. Convert scores to percentiles.
3. Trade only Top X% (start with 10%).
4. Size positions conservatively (1–2%).
5. Monitor weekly: percentile win rate vs baseline.
6. Re-calibrate monthly; re-train quarterly.

---
## 10. Next Enhancements
| Idea | Why | Expected Gain |
|------|-----|---------------|
| Multi-task head (PnL magnitude) | Differentiates shallow wins from meaningful moves | Better EV selection |
| Attention layer | Interpretability & adaptive focus | Possible AUC bump |
| Regime features (VIX, SPY slope) | Stabilise across volatility shifts | Lower variance of lift |
| Ensemble (seed/feature subsets) | Smooth idiosyncratic ranking noise | More consistent top percentile |

---
## 11. Lessons Learned
- Calibration without *temporal monotonicity* is cosmetics.
- High AUC obsession misleads; lift + robustness beats raw discrimination.
- Percentiles > thresholds for longitudinal stability.
- Treat model outputs as *ordering suggestions*, not gospel.

---
## 12. Final Takeaway
The edge wasn’t in predicting truth; it was in **sorting noise into a usable hierarchy**. The LSTM doesn’t tell me what WILL win; it points me toward where the *rate of winning is statistically higher*. That’s enough to allocate capital more intelligently.

---
*If you want the code layout and reproducibility details, the cleaned repository now ships a single calibration script (`calibration_production.py`) and a percentile backtester (`backtest_calibrated.py`). Everything else was pruned.*

**Next Post Preview:** Extending the ranking model with a magnitude-aware head and testing if EV‑weighted selection beats pure win rate filtering.
