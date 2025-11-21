# LSTM Ranking Model Refinement Plan

## Current State Analysis

### What Works
- Model achieves 22% precision vs 16% baseline (+37% relative lift)
- Deeper architecture (128 hidden, 3 layers) captures more patterns
- Proper 70/15/15 split prevents temporal leakage
- Ranking signal is real: Top decile shows 1.66x lift

### Critical Issues
1. **Calibration Disaster (ECE: 0.32)**
   - Model predicts 40-60% probabilities for events with 11-27% actual win rates
   - Probabilities are 2x inflated across all ranges
   - Cannot be used as probability oracle

2. **Weak AUC (0.576)**
   - Barely above random (0.50)
   - Below 0.60 threshold for reliable market edge
   - Suggests weak discriminative power

3. **Small Sample Fragility**
   - Best bucket (60-70%) has only 150 trades
   - High variance risk - could be statistical noise
   - Needs bootstrap validation

4. **Unknown Temporal Stability**
   - No evidence model works across different market regimes
   - May have overfit bull market (2024 test period)
   - Risk of performance collapse in different conditions

## Key Insight: Ranking vs Probability

**The model is NOT a probability estimator. It is a RANKING ENGINE.**

Evidence:
- When model says 60%, actual is 27% (wrong probability)
- But 27% is still 1.66x better than 16% baseline (correct ranking)
- Higher scores correlate with better outcomes (monotonic relationship)

## Action Plan

### Phase 1: Validation & Diagnosis (Priority: CRITICAL)

#### 1.1 Temporal Stability Test
```
Objective: Check if lift holds across time periods
Method: 
- Split test set by year/quarter
- Calculate lift for each period separately
- Plot lift over time
Success Criteria: 95% CI of lift > 1.0 across all periods
```

#### 1.2 Bootstrap Stability Test
```
Objective: Verify top decile edge is not statistical noise
Method:
- 1000 bootstrap samples
- Calculate lift for each sample
- Build confidence interval
Success Criteria: 95% CI excludes 1.0 (null hypothesis)
```

#### 1.3 Sample Size Analysis
```
Objective: Determine minimum viable threshold
Method:
- Test thresholds: [0.40, 0.45, 0.50, 0.55, 0.60]
- Plot sample size vs lift curve
- Find optimal trade-off
Success Criteria: At least 500 trades with lift > 1.3
```

### Phase 2: Calibration Methods (Priority: HIGH)

#### 2.1 Isotonic Regression
```
Use validation set to fit monotonic calibration
Pro: Non-parametric, preserves ranking order
Con: Can overfit with small samples
```

#### 2.2 Platt Scaling
```
Fit logistic regression on validation scores
Pro: Parametric, more stable
Con: Assumes sigmoid relationship
```

#### 2.3 Temperature Scaling
```
Add single scalar parameter T to soften/sharpen logits
Pro: Minimal parameters, fast
Con: Linear transformation only
```

**Test Metric:** Brier Score and Log Loss on hold-out test set

### Phase 3: Quantile-Based Trading Rules (Priority: HIGH)

#### 3.1 Decile Analysis
```
Split predictions into 10 equal-sized bins
Measure:
- Win rate per decile
- EV per trade per decile
- Cumulative PnL curve
Strategy: Trade top 2-3 deciles only
```

#### 3.2 Dynamic Threshold Optimization
```
Instead of fixed 0.50:
- Use validation set to find optimal threshold
- Maximize Sharpe or Sortino ratio
- Backtest on test set
```

### Phase 4: Model Improvements (Priority: MEDIUM)

#### 4.1 Auxiliary Loss for Magnitude
```python
# Current: Binary cross-entropy only
loss = BCEWithLogitsLoss(win_loss_labels)

# Proposed: Multi-task learning
loss = BCE(win_loss) + alpha * MSE(pnl_magnitude)
```

Benefits:
- Model learns not just direction but size of moves
- Better risk-adjusted decisions
- Captures edge vs spread cost

#### 4.2 Attention Mechanism
```
Add attention layer to LSTM
- Identifies which bars matter most
- Interpretable feature importance
- May improve AUC
```

#### 4.3 Ensemble Strategy
```
Train 5 models with different:
- Random seeds
- Architecture variations (2-layer vs 3-layer)
- Feature subsets

Combine via:
- Rank averaging (robust to calibration)
- Stacking with meta-learner
```

### Phase 5: Feature Engineering (Priority: LOW)

#### 5.1 Market Regime Features
```
Add to input:
- VIX percentile rank
- Market trend (SPY 20d MA slope)
- Sector rotation signals
- Time-of-day volatility patterns
```

#### 5.2 Trade Context Features
```
- Distance from daily VWAP
- Relative spread (bid-ask / price)
- Recent momentum (5-bar slope)
- Volume profile deviation
```

## Implementation Roadmap

### Week 1: Validation Sprint
- [ ] Implement temporal stability analysis
- [ ] Run 1000-iteration bootstrap test
- [ ] Test calibration methods (Isotonic, Platt, Temperature)
- [ ] Document findings

### Week 2: Ranking Optimization
- [ ] Build quantile-based backtest framework
- [ ] Optimize threshold on validation set
- [ ] Compare strategies: Top 10%, Top 20%, Top 30%
- [ ] Test across different position sizing (1%, 2%, 5%)

### Week 3: Model Architecture Experiments
- [ ] Implement multi-task loss (direction + magnitude)
- [ ] Train ensemble of 5 models
- [ ] Add attention mechanism
- [ ] Compare AUC and calibration metrics

### Week 4: Production Pipeline
- [ ] Finalize best approach (likely: Isotonic + Top 20%)
- [ ] Build inference pipeline with calibration
- [ ] Create monitoring dashboard
- [ ] Document model card with limitations

## Success Metrics

### Minimum Viable Product
- Bootstrap 95% CI lift > 1.2
- At least 1000 trades in top quantile
- Sharpe ratio > 2.0 on out-of-sample test
- Stable performance across 2+ years

### Stretch Goals
- AUC > 0.65
- Calibration ECE < 0.10
- Top decile lift > 1.8
- Works on both Top 20 and Top 50 universes

## Risk Mitigation

### Known Risks
1. **Overfitting bull market**: Test set is 2024-2025, strong uptrend
2. **Regime shift**: Model may fail in volatility spike
3. **Sample size**: Top buckets have <200 trades

### Mitigations
- Test on 2021-2022 bear market data separately
- Build regime-switching thresholds
- Use conservative position sizing (1-2% max)
- Monitor calibration drift in production

## Final Recommendation

**Treat this as a trade filter, not a probability model.**

Strategy:
1. Use Isotonic calibration on validation set
2. Trade top 20% of ranked opportunities only
3. Start with 1% position sizing
4. Monitor lift metric weekly
5. Re-calibrate monthly

Expected Outcome:
- 500-800 trades per year
- 20-22% win rate (vs 16% baseline)
- Sharpe 2.5-3.0 (if lift holds)
- Max drawdown < 5% (due to low position sizing)

This is a **signal strength model**, not a pricing model. Use it to rank, not to bet.
