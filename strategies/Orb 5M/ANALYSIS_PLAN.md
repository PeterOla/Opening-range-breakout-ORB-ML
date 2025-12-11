# ORB Win/Loss Pattern Analysis & Feature Engineering Plan

## Objective

Rebuild Top 20 trade datasets with expanded features; identify patterns via statistical testing (univariate correlation, logistic regression, ensemble methods, LSTM); develop rules or ranking model to increase win rate.

---

## Phase Overview

| Phase | Week | Tasks | Deliverable |
|-------|------|-------|-------------|
| **Phase 1** | This week | Compute Tier 1 features; rebuild Top 20 dataset | Trade feature CSV with gap, pre-market move, price, vol-rank, streak |
| **Phase 2** | Next 2 weeks | Univariate correlation, logistic regression, RF, XGBoost | Model comparison report (AUC, feature importance, SHAP) |
| **Phase 3** | Week 3–4 | Train LSTM; ensemble all 4 models; re-backtest Top X% subsets | LSTM validation curves, percentile ranks, backtest P&L lift |
| **Phase 4** | Week 5+ | Rule extraction, live paper trading validation | Entry gate rules + final rule book |

---

## Phase 1: Feature Engineering & Dataset Rebuild

### 1.1 Column Definitions

**From existing daily parquets (already available):**
- `symbol`, `trade_date`, `entry_price`, `exit_price`, `exit_reason`, `pnl_pct`
- `atr_14`, `avg_volume_14`, `shares_outstanding`
- `price` (close price at entry day)

**From 5-min bars (to extract):**
- `or_high`, `or_low`, `or_open`, `or_close`, `or_volume`
- `bars_to_entry` (number of bars after 9:35 ET until breakout triggered)
- `momentum_pattern` (characterization of first 3 post-OR bars: strength, consistency)

**Tier 1 — Computed from existing data (this phase):**
1. **gap_pct** = (open price – prev close) / prev close × 100
2. **gap_filled_by_eod** = boolean (did price touch/cross prev close before EOD?)
3. **pre_market_move_pct** = (market open – prev close) / prev close × 100
4. **float_adjusted_rvol** = RVOL × (market_cap_decile or shares_outstanding weighting)
5. **prior_day_volume_rank** = rank of prior day volume vs 20-day average (1=high, 20=low)
6. **consecutive_up_down_streak** = count of consecutive up/down days at today's entry (same-day trend context)

**Tier 2 — Requires external fetch (Phase 2):**
- `short_interest` (shares shorted, from FINRA weekly)
- `si_ratio` = short_interest / float
- `si_to_volume_ratio` = short_interest / avg_daily_volume

**Tier 3 — External feeds (Phase 3+):**
- `market_breadth` (advance/decline ratio at entry time)
- `sector_momentum` (XLK, XLE, XLF returns at entry time)
- `vix_level` (real-time VIX at 9:35 ET)

### 1.2 Data Sources & Computation

| Feature | Source | Availability | Effort | Formula |
|---------|--------|--------------|--------|---------|
| gap_pct | Daily parquet (open, prev_close) | Daily | Trivial | (open – prev_close) / prev_close × 100 |
| pre_market_move_pct | Daily parquet | Daily | Trivial | Same as gap_pct (pre-market = gap to open) |
| price | Daily parquet (close) | Daily | Trivial | Close price at entry day |
| float_adjusted_rvol | Daily + shares_outstanding | Daily | Low | RVOL × (float percentile or cap-weight factor) |
| prior_day_vol_rank | Daily parquet (14-day rolling) | Daily | Low | Rank of prior day volume vs 20d avg |
| consecutive_streak | Daily parquet (close > open pattern) | Daily | Low | Count same-direction closes in last 5 days ending today |
| short_interest | FINRA weekly API | Weekly (2-week lag) | Medium | Merge weekly SI to daily trades (point-in-time) |
| si_ratio | FINRA + shares_outstanding | Weekly | Medium | short_shares / float |
| bars_to_entry | 5-min bars | Intraday | Low | Index of first bar that triggers entry level |
| momentum_pattern | 5-min bars (first 3 post-OR) | Intraday | Medium | Encode: (bar1_close > bar1_open) + (bar2_momentum) + (bar3_momentum) |

### 1.3 Deliverable

**Output file**: `data/backtest/top_20_trades_with_features.parquet`

Columns (in order):
```
symbol, trade_date, direction (1/-1), entry_price, exit_price, exit_reason, 
pnl_pct, atr_14, avg_volume_14, shares_outstanding, price,
or_high, or_low, or_open, or_close, or_volume, rvol,
gap_pct, gap_filled_by_eod, pre_market_move_pct, 
float_adjusted_rvol, prior_day_volume_rank, consecutive_streak,
bars_to_entry, momentum_pattern,
[Tier 2 columns to be added in Phase 2]
```

**Row count**: ~20,000 trades (Top 20 ORB across 2021–2025)

---

## Phase 2: Statistical Analysis & Model Baseline

### 2.1 Univariate Correlation Analysis

**Method**: Spearman rank correlation (feature vs binary win/loss outcome)

**Output**:
- Correlation matrix (all Tier 1 + Tier 2 features)
- Volcano plot: feature importance (x-axis) vs −log10(p-value) (y-axis)
- Top 5–10 statistically significant features (p < 0.05)

**Example output**:
```
Feature                  Corr    p-value   Significant
gap_pct                  0.12    0.0001    ✓
pre_market_move_pct      0.09    0.0015    ✓
si_ratio                 -0.07   0.0045    ✓
price                    0.05    0.028     ✓
consecutive_streak       0.04    0.087     ✗
```

### 2.2 Logistic Regression (GLM Baseline)

**Model**: Logistic regression with L2 regularization

**Data split**: 70% train (chronological), 30% test (holdout)

**Features**: All Tier 1 + Tier 2 (standardized)

**Output**:
- Coefficients & odds ratios (interpretable)
- AUC-ROC on holdout (compare to null model = baseline win rate)
- Confusion matrix, precision, recall, F1

**Example result**:
```
Model               AUC     Accuracy  Precision  Recall
Null (baseline)     0.50    0.165     0.165      1.0
Logistic Regression 0.58    0.195     0.18       0.85
```

### 2.3 Ensemble Methods

**Random Forest**:
- 100 trees, max_depth=10, min_samples_split=20
- Feature importance (mean decrease in impurity)
- AUC-ROC, confusion matrix

**XGBoost**:
- 100 rounds, max_depth=5, learning_rate=0.1
- SHAP values for interpretability
- AUC-ROC, feature importance (gain, cover, frequency)

**Output**: Feature importance comparison (RF vs XGBoost SHAP)

### 2.4 Deliverable

**Report**: `strategies/Orb 5M/docs/phase_2_model_comparison.md`

Contains:
- Univariate correlation table + volcano plot
- Logistic regression summary (coef, p-values)
- RF & XGBoost feature importance plots
- Model performance comparison (AUC, accuracy, precision, recall)
- Top 5 most predictive features for next phase

---

## Phase 3: LSTM Pattern Detection & Model Ensemble

### 3.1 LSTM Architecture

**Input design** (Option A — recommended):
- Sequence: First 5 post-OR bars (9:35–10:00 ET)
- Each bar: OHLCV (5 features)
- Aggregate stats: gap_pct, RVOL, ATR, price, si_ratio, prior_vol_rank, consecutive_streak (10 features)
- Total input size: 5 bars × 5 + 10 stats = 35 features, sequence length = 1 time step
  
**Alternative** (Option B — fuller pattern):
- All 78 bars (9:30–16:00 ET) × OHLCV = 390 features
- Sequence length = 78 time steps
- Captures full intraday pattern but heavier training

**Architecture** (3-layer LSTM):
```
Input (batch, 1, 35) or (batch, 78, 5)
  ↓
LSTM layer 1: 128 units, return_sequences=True
  ↓
Dropout: 0.3
  ↓
LSTM layer 2: 64 units, return_sequences=False
  ↓
Dropout: 0.3
  ↓
Dense: 32 units, ReLU
  ↓
Output: Dense 1 unit, Sigmoid (binary win/loss probability)
```

**Loss**: BCEWithLogitsLoss with pos_weight for class imbalance (baseline win rate ~16%)

**Data split**: 60% train, 20% validation, 20% test (chronological, no shuffling)

### 3.2 LSTM Training & Validation

**Output**:
- Training/validation loss curves
- Test AUC-ROC, confusion matrix
- Prediction probabilities (percentile ranks 1–100 for all trades)

**Expected performance**: 
- Should beat logistic regression by capturing non-linear momentum patterns
- AUC target: 0.62–0.68

### 3.3 Model Ensemble

**Strategy 1** (Equal average):
```
ensemble_prob = (logit_prob + rf_prob + xgb_prob + lstm_prob) / 4
```

**Strategy 2** (AUC-weighted):
```
weights = [logit_auc, rf_auc, xgb_auc, lstm_auc] / sum(...)
ensemble_prob = Σ(weight_i × model_i_prob)
```

**Strategy 3** (Meta-learner stacking):
- Train secondary model on outputs of 4 models
- More sophisticated but higher variance risk

**Recommendation**: Start with Strategy 1 (simplest, reduces variance)

### 3.4 Percentile Ranking & Re-backtesting

**Percentile rank**: For each trade, compute composite percentile (1–100):
```
percentile = ensemble_prob × 100
```

**Re-backtest by percentile subsets**:
```
Subset     Trades   Win Rate  Sharpe  Notes
All        20,000   16.0%     2.97    Baseline
Top 50%    10,000   17.5%     2.45    Slight improvement
Top 25%     5,000   19.2%     1.98    Moderate improvement
Top 10%     2,000   22.8%     1.55    Good improvement
Top 5%      1,000   26.1%     1.12    Excellent improvement (but small sample)
```

**Metric**: Calculate **Win Rate Lift** = (new_wr − baseline_wr) / baseline_wr × 100%

### 3.5 Deliverable

**Notebook**: `strategies/Orb 5M/phase_3_lstm_ensemble.ipynb`

Contains:
- LSTM training curves + validation metrics
- Ensemble probability distribution plot
- Percentile ranking results table
- Re-backtest P&L curves by percentile subset
- Summary: recommended percentile cutoff (e.g. "Trade only Top 20%")

---

## Phase 4: Rule Extraction & Live Validation

### 4.1 Hard Rules from Feature Importance

From Phase 2 & 3, identify features with **clear threshold separations** between winners/losers:

**Example rules** (to be validated on Phase 2 results):
```
SKIP trade if:
  - gap_pct < −3% OR gap_pct > 5%        (extreme gaps: higher whipsaws)
  - si_ratio > 0.20                      (high short interest: crowded trades)
  - consecutive_streak < −2              (downtrend context: lower edge)
  - price < $5.00 OR price > $50.00      (penny stocks / high-price dilution)

PREFER trade if:
  - pre_market_move_pct > 1%             (positive overnight momentum)
  - prior_day_volume_rank <= 5           (volume was elevated yesterday)
  - consecutive_streak >= 1              (uptrend context)
```

### 4.2 Entry Gate Rules + Probabilistic Ranking

**Workflow**:
1. Apply hard rules (accept/reject)
2. For accepted trades, compute ensemble percentile rank
3. **Trade only if** (hard rules pass) **AND** (percentile rank > threshold)

**Example**:
```
IF gap_pct in [−3%, 5%] 
   AND si_ratio <= 0.20
   AND price in [$5, $50]
   THEN compute ensemble_percentile
   IF ensemble_percentile >= 60 THEN TRADE
   ELSE SKIP
```

### 4.3 Live Paper Trading Validation

Run Top 20 ORB scanner with new rules for 2–4 weeks (paper trading):
- Track win rate on live entries
- Compare to historical backtest
- Measure **Win Rate Lift** (expected vs actual)
- Monitor **Drawdown & Sharpe** under new filtering

### 4.4 Deliverable

**Rule book**: `strategies/Orb 5M/docs/FINAL_RULES.md`

Contains:
- Hard entry gate rules (with justification from Phase 2)
- Percentile rank threshold (from Phase 3 re-backtesting)
- Expected performance (win rate, Sharpe, max DD)
- Live validation results (2–4 week paper trading)
- Recommended threshold for live trading

---

## Data Flow Diagram

```
Phase 1: Feature Engineering
┌─────────────────────────────────────────────────────┐
│ Input: simulated_trades.parquet (basic Top 20)       │
│        daily parquets (ATR, volume, shares, etc.)    │
│        5-min bars (opening range, momentum)          │
└──────────────────┬──────────────────────────────────┘
                   │
        [Compute gap_pct, pre_market_move_pct,
         price, vol_rank, consecutive_streak, etc.]
                   │
                   ▼
        Output: top_20_trades_with_features.parquet
        
Phase 2: Statistical Analysis
┌─────────────────────────────────────────────────────┐
│ Input: top_20_trades_with_features.parquet           │
└──────────────────┬──────────────────────────────────┘
                   │
        [Univariate correlation, Logit, RF, XGBoost]
                   │
                   ▼
        Output: phase_2_model_comparison.md
                (AUC, feature importance, top 5 features)
        
Phase 3: LSTM & Ensemble
┌─────────────────────────────────────────────────────┐
│ Input: top_20_trades_with_features.parquet           │
│        Phase 2 model outputs (probabilities)         │
└──────────────────┬──────────────────────────────────┘
                   │
        [Train LSTM, ensemble 4 models,
         re-backtest Top X% subsets]
                   │
                   ▼
        Output: phase_3_lstm_ensemble.ipynb
                (percentile ranks, backtest lift)
        
Phase 4: Rule Extraction & Live Validation
┌─────────────────────────────────────────────────────┐
│ Input: Phase 2 (feature importance)                  │
│        Phase 3 (percentile threshold)                │
└──────────────────┬──────────────────────────────────┘
                   │
        [Extract hard rules, set percentile cutoff,
         run 2–4 week paper trading]
                   │
                   ▼
        Output: FINAL_RULES.md
                (entry gates, percentile threshold,
                 live validation results)
```

---

## Key Decisions to Finalize Before Phase 1

1. **Tier 1 feature priority** — All 6 Tier 1 features go in first round? Or subset?
   - **Recommendation**: Include all 6 (low effort, high signal potential)

2. **LSTM input design** — Option A (5 bars + stats) or Option B (78 bars)?
   - **Recommendation**: Option A (faster, lighter, still captures momentum)

3. **Pre-market move definition** — Market open vs prev close?
   - **Recommendation**: (open – prev_close) / prev_close × 100 (matches gap_pct, aligned with same-day volume context)

4. **Consecutive streak window** — Last 5 days or same-day trend?
   - **Recommendation**: Count of consecutive up/down days ending **today** (market regime signal at entry time)

5. **Start Phase 1 immediately?** — Yes, once backtest Top 20 dataset is available (should be ready after daily_sync completes)
   - **Recommendation**: YES — begin feature computation while daily_sync finishes

---

## Success Metrics

| Metric | Baseline | Target | Phase |
|--------|----------|--------|-------|
| **Win Rate** | 16.0% | 20%+ | Phase 3 (Top 25% subset) |
| **Sharpe Ratio** | 2.97 | 3.2+ | Phase 3 |
| **Profit Factor** | 1.7 | 2.0+ | Phase 3 |
| **Max Drawdown** | −1.46% | −1.0% | Phase 3 |
| **Model AUC** | 0.50 (null) | 0.65+ | Phase 2 |
| **Win Rate Lift** | — | 25%+ | Phase 3 |

---

## Notes

- **No external data required for Phase 1** — All features computable from existing daily/5-min parquets
- **LSTM training time** — Expect 5–30 minutes on GPU (or 1–2 hours CPU)
- **Feature scaling** — Standardize all features before fitting models (zero mean, unit variance)
- **Class imbalance** — Use pos_weight in LSTM loss and sample_weight in sklearn models
- **Cross-validation** — Chronological split (no shuffling) to avoid data leakage
- **Interpretability** — Logistic regression + SHAP (XGBoost) preferred over pure RF for rule extraction
