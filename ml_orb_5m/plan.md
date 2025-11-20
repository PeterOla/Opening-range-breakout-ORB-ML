# ML-Enhanced Opening Range Breakout Strategy

## Goal
Train machine learning models on the core ORB strategy to predict trade entry decisions, improving win rate and risk-adjusted returns by learning patterns the rule-based system might miss.

## Project Overview

**Base Strategy Performance (Rule-Based):**
- 5-year backtest: $1k → $190k (18,941% return)
- CAGR: 185.72% | Max DD: -20.55%
- Win Rate: 16.79% | Profit Factor: 1.78
- 24,180 trades on top 20 RVOL stocks

**ML Objective:**
- Predict whether a breakout entry signal will be profitable
- Improve win rate from 16.79% to 25-30%+ while maintaining profit factor
- Reduce false breakouts and whipsaws
- Learn market regime changes and context dependencies

---

## Architecture

### 1. Feature Engineering Pipeline
**Input:** Raw 5-min/1-min bars + daily data  
**Output:** Feature matrix for each potential trade setup  
**Storage:** Parquet files for fast training iteration

### 2. Model Training
- **Target:** Binary classification (profitable trade = 1, loser = 0)
- **Models to test:** 
  - LightGBM (fast, interpretable)
  - XGBoost (robust to overfitting)
  - Neural networks (LSTM for sequential patterns)
  - Ensemble stacking
- **Training data:** 2021-2023 (60% train, 20% validation)
- **Test data:** 2024-2025 (20% holdout)

### 3. Backtesting Integration
- Replace rule-based entry decision with ML prediction
- Threshold tuning: Only enter if `P(profitable) > 0.6` (adjust based on precision-recall)
- Keep existing risk management (1% risk, 10% ATR stop, EOD exit)

### 4. Live Deployment (Future)
- Real-time feature calculation from streaming data
- Model inference < 100ms
- Fallback to rule-based if model fails

---

## Feature Research & Engineering

### **Category 1: Price Action Features** ✅ COMPLETED (Core Strategy Context)

**Status:** 29 features extracted for 24,169 trades | Win rate: 16.77%

#### Opening Range Metrics ✅
- [x] `or_open`, `or_high`, `or_low`, `or_close` - Basic OR levels
- [x] `or_volume` - Total volume in opening range
- [x] `or_range_size` = or_high - or_low
- [x] `or_range_pct` = (or_high - or_low) / or_low
- [x] `or_range_vs_atr` = or_range_size / atr_14d (normalized breakout potential)
- [x] `or_close_vs_open` = (or_close - or_open) / or_open (first candle direction strength)
- [x] `or_body_size` = |or_close - or_open|
- [x] `or_body_pct` = |or_close - or_open| / or_range_size (candle body ratio)
- [x] `or_upper_shadow` = or_high - max(or_open, or_close) (rejection at highs)
- [x] `or_lower_shadow` = min(or_open, or_close) - or_low (rejection at lows)
- [x] `or_upper_shadow_pct`, `or_lower_shadow_pct` - Shadow ratios

#### Gap Features ✅
- [x] `overnight_gap` = or_open - prev_close
- [x] `gap_pct` = (or_open - prev_close) / prev_close
- [x] `gap_direction` = sign(overnight_gap) (1, 0, -1)
- [x] `gap_vs_atr` = abs(overnight_gap) / atr_14d (gap magnitude)
- [x] `gap_filled_by_or` = 1 if gap between or_high and or_low else 0

#### Candlestick Patterns (First 5 mins) ✅
- [x] `is_doji` = 1 if or_close ≈ or_open (< 0.1% range)
- [x] `is_hammer` = lower_shadow > 2 * body and upper_shadow < 0.1 * range
- [x] `is_shooting_star` = upper_shadow > 2 * body and lower_shadow < 0.1 * range
- [x] `is_marubozu` = (upper_shadow + lower_shadow) < 0.1 * range (strong directional move)

#### Momentum Indicators (Opening Range Only - No Lookahead) ✅
- [x] `roc_5min` = (or_close - open_9:30) / open_9:30 (rate of change)
- [x] `rsi_5min` = RSI approximation on OR bars

#### Price Level Features ✅
- [x] `distance_to_prev_high` = (current_price - prev_day_high) / prev_day_high
- [x] `distance_to_prev_low` = (current_price - prev_day_low) / prev_day_low

#### ATR-Normalized Features ✅
- [x] `atr_14` - 14-day Average True Range from daily bars
- [x] `or_range_vs_atr` - Opening range size normalized by ATR
- [x] `gap_vs_atr` - Gap size normalized by ATR

**Implementation Details:**
- File: `ml_orb_5m/src/features/price_action.py` (310 lines)
- Output: `ml_orb_5m/data/features/price_action_features.parquet`
- Dataset: 24,169 rows × 36 columns (27 features + 8 metadata + 1 target)
- Lookahead bias: ✅ Validated - all features use only 09:30-09:35 data
- Processing time: ~18 mins (4 min preload + 14 min extraction)
- Date range: 2021-01-25 to 2025-11-13

---

### **Category 2: Volume & Liquidity Features** (Execution Quality) ✅ COMPLETED

#### Volume Metrics
- [x] `or_rvol_14` (already have - relative volume vs 14-day avg)
- [x] `or_volume` = total volume in opening range
- [x] `or_vol_vs_avg_daily` = or_volume / avg_daily_vol_14d
- [x] `avg_dollar_volume_14d` = avg_volume_14d * avg_price (liquidity in dollars)

#### Liquidity Proxies
- [x] `or_spread_pct` = (high - low) / close (intraday spread proxy)
- [x] `or_vol_per_min` = volume per minute in OR

---

### **Category 3: Volatility Features** (Breakout Validity) ✅ COMPLETED

#### ATR-Based Volatility
- [x] `atr_14_daily` (already have)
- [x] `or_range_vs_daily_atr` = or_range / atr_14d (intraday vs daily volatility)
- [x] `volatility_trend_5d_20d` = atr_5d / atr_20d

#### Range-Based Volatility
- [x] `or_log_range_vol` = log(high / low) (proxy for volatility)

---

### **Category 4: Market Context Features** (Regime Detection)

#### Broad Market Indices
- [ ] `spy_return_premarket` = (SPY_open - SPY_prev_close) / SPY_prev_close
- [ ] `spy_return_or` = (SPY_9:35 - SPY_9:30) / SPY_9:30
- [ ] `spy_return_intraday` = (SPY_current - SPY_open) / SPY_open
- [ ] `spy_trend_5d` = (SPY_close - SPY_close_5d_ago) / SPY_close_5d_ago
- [ ] `spy_above_sma_20` = 1 if SPY > SMA(20) else 0
- [ ] `spy_above_sma_50` = 1 if SPY > SMA(50) else 0

- [ ] `qqq_return_or` = (QQQ_9:35 - QQQ_9:30) / QQQ_9:30
- [ ] `qqq_correlation_5d` = rolling correlation(stock, QQQ) over 5 days

- [ ] `vix_level` = VIX close on previous day
- [ ] `vix_change` = (VIX_today - VIX_yesterday) / VIX_yesterday
- [ ] `vix_regime` = 0 (low < 15), 1 (medium 15-25), 2 (high > 25)

#### Sector Context
- [ ] `sector_index_return_or` = sector ETF return 9:30-9:35
- [ ] `sector_index_trend_5d` = (sector_close - sector_close_5d_ago) / sector_close_5d_ago
- [ ] `stock_vs_sector_correlation` = rolling corr(stock, sector) over 20 days
- [ ] `sector_relative_strength` = stock_return_5d / sector_return_5d
- [ ] `sector_momentum` = sector_return_20d (classify stocks by sector momentum)

#### Market Breadth
- [ ] `advancers_decliners_ratio` = (advancing_stocks / declining_stocks) on NYSE/NASDAQ
- [ ] `new_highs_lows_ratio` = (new_highs / new_lows) over 52-week period
- [ ] `up_volume_down_volume` = total up_volume / total_down_volume

#### Event Flags (Binary Features)
- [ ] `is_earnings_day` = 1 if earnings announcement today
- [ ] `is_ex_dividend_day` = 1 if ex-dividend date
- [ ] `is_fomc_day` = 1 if FOMC meeting/announcement
- [ ] `is_first_day_of_month` = 1 if trading day 1 of month
- [ ] `is_last_day_of_month` = 1 if trading day -1 of month
- [ ] `is_quad_witching` = 1 if options expiration day

---

### **Category 5: Temporal & Session Features** (Time-Based Patterns) ✅ COMPLETED

#### Day of Week Effects
- [x] `day_of_week` = 0 (Mon), 1 (Tue), ... 4 (Fri)
- [x] `month` = 1-12
- [x] `is_month_start` = 1 if first day of month
- [x] `is_month_end` = 1 if last day of month
- [x] `is_quarter_start` = 1 if first day of quarter
- [x] `is_quarter_end` = 1 if last day of quarter
- [x] `day_of_year` = 1-366

---

## Feature Engineering Workflow

### Step 1: Data Collection & Preprocessing
```
Input sources:
- orb_5m/results/results_combined_top20/all_trades.csv (24k+ trades)
- data/processed/5min/*.parquet (5-min bars)
- data/processed/1min/*.parquet (1-min bars)
- data/processed/daily/*.parquet (daily bars for ATR)
- External: SPY, QQQ, VIX, sector ETFs

Pipeline:
1. Load all trades with entry timestamps
2. For each trade, look back at data up to entry_time
3. Calculate all features at decision point (9:35 AM)
4. Label: 1 if net_pnl > 0, else 0
5. Save to ml_orb_5m/data/features/train_features.parquet
```

### Step 2: Feature Selection & Importance
```
Methods:
- Correlation analysis (remove highly correlated features > 0.95)
- Feature importance from tree models (LightGBM feature_importances_)
- Recursive feature elimination (RFE)
- SHAP values for interpretability
- Target encoding for categorical features

Output:
- Top 50-100 most predictive features
- Feature importance report
- Correlation heatmap
```

### Step 3: Feature Validation
```
Checks:
- No lookahead bias (only use data before entry_time)
- No data leakage (target not encoded in features)
- Stationarity tests (features stable across time periods)
- Missing value imputation strategy
- Outlier detection and clipping

Quality gates:
- < 5% missing values per feature
- No perfect predictors (feature importance < 0.8)
- Feature distributions similar across train/test splits
```

---

## Model Development

### Phase 1: Baseline Models (Week 1-2)

**Model 1: Logistic Regression**
- Simple, interpretable baseline
- Features: Top 20 most important from EDA
- Hyperparameters: L1/L2 regularization, class weights

**Model 2: LightGBM Classifier**
- Fast gradient boosting
- Features: All 100+ features
- Hyperparameters: 
  - `num_leaves`: 31, 63, 127
  - `learning_rate`: 0.01, 0.05, 0.1
  - `max_depth`: 5, 7, 10
  - `min_data_in_leaf`: 20, 50, 100

**Model 3: XGBoost Classifier**
- Robust to overfitting
- Features: All 100+ features
- Hyperparameters:
  - `max_depth`: 3, 5, 7
  - `learning_rate`: 0.01, 0.05, 0.1
  - `subsample`: 0.7, 0.8, 0.9
  - `colsample_bytree`: 0.7, 0.8, 0.9

**Evaluation Metrics:**
- Precision @ 60% threshold (avoid false positives)
- Recall (capture true winners)
- F1-Score
- ROC-AUC
- Profit factor on validation set

### Phase 2: Advanced Models (Week 3-4)

**Model 4: LSTM Neural Network**
- Sequential pattern recognition
- Input: Time series of 5-min bars (9:30-9:35)
- Architecture:
  - LSTM(128) → Dropout(0.3) → LSTM(64) → Dense(32) → Output(1, sigmoid)
- Loss: Binary cross-entropy
- Optimizer: Adam (lr=0.001)

**Model 5: Transformer (Optional)**
- Attention mechanism for price patterns
- Input: Same as LSTM
- Architecture: Multi-head attention + feed-forward layers

**Model 6: Ensemble Stacking**
- Combine predictions from LightGBM, XGBoost, LSTM
- Meta-learner: Logistic regression or simple averaging
- Weights optimized on validation set

### Phase 3: Hyperparameter Tuning (Week 5)

**Methods:**
- Grid search for small parameter spaces
- Random search for exploration
- Bayesian optimization (Optuna) for efficiency
- Walk-forward optimization (retrain every 6 months)

**Validation Strategy:**
- Time-series split (no shuffling)
- Train: 2021-2022
- Validation: 2023
- Test: 2024-2025
- Cross-validation: Rolling window (6-month train, 1-month validate)

---

## Backtesting Integration

### Entry Decision Logic
```python
# Original rule-based
if rvol >= 1.0 and direction != 0 and price_crosses_or_level:
    enter_trade = True

# ML-enhanced
if rvol >= 1.0 and direction != 0:
    features = calculate_features(symbol, timestamp)
    prob_profitable = model.predict_proba(features)[0][1]
    
    if prob_profitable >= THRESHOLD:  # e.g., 0.6
        enter_trade = True
    else:
        skip_trade = True  # ML filters out low-confidence setups
```

### Threshold Optimization
- Test thresholds: 0.5, 0.55, 0.6, 0.65, 0.7
- Evaluate:
  - Win rate improvement
  - Trade frequency reduction
  - Profit factor change
  - Sharpe ratio
  - Max drawdown

### Position Sizing (Future Enhancement)
- Scale position size by ML confidence:
  - `P(profitable) > 0.8` → 1.5% risk
  - `P(profitable) 0.6-0.8` → 1.0% risk (baseline)
  - `P(profitable) < 0.6` → skip trade

---

## Performance Targets

### Baseline (Rule-Based ORB)
- Win Rate: 16.79%
- Profit Factor: 1.78
- CAGR: 185.72%
- Max DD: -20.55%
- Trades: 24,180 over 5 years

### ML-Enhanced Goals (Conservative)
- **Win Rate: 25-30%** (improve by 50-80%)
- **Profit Factor: 2.0-2.5** (increase by 12-40%)
- **CAGR: 200%+** (maintain or exceed)
- **Max DD: < 15%** (reduce drawdowns)
- **Trades: 12k-18k** (filter out 25-50% of low-quality setups)

### Success Criteria
1. **Statistically significant improvement** on 2024-2025 holdout test set
2. **Consistent performance across years** (2024 and 2025 both positive)
3. **No overfitting** (train/validation/test metrics within 10%)
4. **Interpretable features** (SHAP values show logical patterns)
5. **Robust to market regimes** (works in high/low volatility periods)

---

## Project Structure

```
ml_orb_5m/
  data/
    features/
      train_features.parquet       # 2021-2023 features
      test_features.parquet         # 2024-2025 features
      feature_metadata.json         # Feature definitions
    external/
      spy_daily.parquet
      qqq_daily.parquet
      vix_daily.parquet
      sector_etfs.parquet
  
  notebooks/
    01_feature_engineering.ipynb   # Build all features
    02_eda.ipynb                   # Exploratory data analysis
    03_feature_selection.ipynb     # Select best features
    04_baseline_models.ipynb       # Train logistic/tree models
    05_advanced_models.ipynb       # Train LSTM/ensemble
    06_model_evaluation.ipynb      # Compare all models
    07_hyperparameter_tuning.ipynb # Optimize best model
    08_backtest_integration.ipynb  # Test with ML-enhanced entries
  
  src/
    features/
      price_action.py              # Category 1 features
      volume_liquidity.py          # Category 2 features
      volatility.py                # Category 3 features
      market_context.py            # Category 4 features
      temporal.py                  # Category 5 features
      feature_engineering.py       # Master pipeline
    
    models/
      baseline.py                  # Logistic, LightGBM, XGBoost
      neural_nets.py               # LSTM, Transformer
      ensemble.py                  # Stacking, blending
      model_utils.py               # Training, evaluation utils
    
    backtest/
      ml_enhanced_orb.py           # Modified ORB with ML filtering
      threshold_optimizer.py       # Find optimal prediction threshold
      walk_forward.py              # Retrain models periodically
  
  models/
    saved_models/
      lightgbm_v1.pkl
      xgboost_v1.pkl
      lstm_v1.h5
      ensemble_v1.pkl
    
  results/
    model_comparisons.csv          # Model performance table
    feature_importance.csv         # Top features
    backtest_ml_enhanced.csv       # ML-enhanced backtest results
    shap_analysis/                 # SHAP plots
  
  config/
    model_config.yaml              # Model hyperparameters
    feature_config.yaml            # Feature definitions
  
  tests/
    test_features.py               # Unit tests for features
    test_no_lookahead.py           # Validate no data leakage
    test_models.py                 # Model sanity checks
  
  plan.md                          # This file
  README.md                        # Project overview
```

---

## Implementation Timeline

### Week 1-2: Feature Engineering ✅ 100% COMPLETE
- [x] Build Category 1 (Price Action) features - **DONE: 29 features, 24,169 trades**
- [x] Fetch external market data (SPY/QQQ) - **DONE: 1,225 days each**
- [x] Validate no lookahead bias - **DONE: All features use 09:30-09:35 only**
- [x] Build Category 2 (Volume/Liquidity) features - **DONE**
- [x] Build Category 3 (Volatility) features - **DONE**
- [x] Build Category 5 (Temporal) features - **DONE**
- [x] Build Category 4 (Market Context) features - **DONE**
- [x] Merge all feature categories into master dataset - **DONE: all_features.parquet (52 features)**

### Week 3: Baseline Models ✅ COMPLETED
- [x] Split data into Train (2020-2022), Val (2023), Test (2024-2025) - **DONE**
- [x] Train Logistic Regression (Baseline) - **DONE (AUC 0.587)**
- [x] Train LightGBM with default params - **DONE (Failed - 0 trades)**
- [x] Train XGBoost with default params - **DONE (Best - AUC 0.591, Win Rate 21.7%)**
- [x] Evaluate on validation set (2023) - **DONE**

### Week 4: Feature Selection & Advanced Models
- [x] Correlation analysis (remove redundant features) - **DONE (7 removed)**
- [x] SHAP analysis for interpretability - **DONE (Top predictor: or_close_vs_open)**
- [x] Recursive Feature Elimination (RFE) - **DONE (Selected 25 features)**
- [x] Select top 20-30 features - **DONE**
- [ ] Train Ensemble (Voting/Stacking) using selected features
- [ ] Train LSTM on sequential price data (Optional)

### Week 5: Backtesting Integration
- [ ] Modify ORB backtest to use ML predictions

### Week 4: Advanced Models
- [ ] Train LSTM on sequential price data
- [ ] Train ensemble (LightGBM + XGBoost + LSTM)
- [ ] Hyperparameter tuning with Optuna
- [ ] SHAP analysis for interpretability

### Week 5: Backtesting Integration
- [ ] Modify ORB backtest to use ML predictions
- [ ] Test thresholds (0.5, 0.6, 0.7)
- [ ] Evaluate on 2024-2025 holdout set
- [ ] Compare ML-enhanced vs rule-based
- [ ] Generate performance report

### Week 6: Refinement & Documentation
- [ ] Walk-forward analysis (retrain every 6 months)
- [ ] Stress test on different market regimes
- [ ] Document final model architecture
- [ ] Write deployment guide
- [ ] Create model monitoring dashboard

---

## Risk Considerations

### Overfitting Risks
- **Mitigation:** Use time-series splits, early stopping, regularization
- **Validation:** Test on completely unseen 2024-2025 data
- **Monitoring:** Track train/val/test metric divergence

### Lookahead Bias
- **Mitigation:** Strict timestamp filtering in feature engineering
- **Validation:** Manual code review of all feature calculations
- **Testing:** Unit tests to ensure features only use past data

### Data Quality Issues
- **Risk:** Missing bars, survivorship bias, corporate actions
- **Mitigation:** Data validation pipeline, filter out low-quality days
- **Fallback:** Use rule-based system if data quality flags raised

### Market Regime Changes
- **Risk:** Model trained on 2021-2023 may not work in 2024-2025
- **Mitigation:** Walk-forward retraining, ensemble of models trained on different periods
- **Monitoring:** Track model performance weekly, retrain if degradation detected

### Execution Slippage
- **Risk:** ML may select more volatile stocks with wider spreads
- **Mitigation:** Include liquidity features in training
- **Testing:** Realistic slippage simulation (already done in orb_5m)

---

## Success Metrics

### Model Performance (Offline)
- **ROC-AUC > 0.65** on test set (2024-2025)
- **Precision @ 60% threshold > 0.35** (35% of ML-predicted trades win)
- **Feature importance stable** across train/val/test

### Backtest Performance (Online)
- **Win Rate improvement: 16.79% → 25%+** (min +8pp)
- **Profit Factor improvement: 1.78 → 2.0+** (min +0.22)
- **Max DD improvement: -20.55% → -15%** (max -5pp reduction)
- **Sharpe Ratio improvement: Increase by 20%+**

### Production Readiness
- **Inference time < 100ms** per prediction
- **Model monitoring dashboard** with drift detection
- **A/B testing framework** (50% rule-based, 50% ML-enhanced)
- **Graceful fallback** to rule-based if ML fails

---

## Dependencies

```
# requirements_ml.txt
pandas>=2.0.0
numpy>=1.24.0
scikit-learn>=1.3.0
lightgbm>=4.0.0
xgboost>=2.0.0
tensorflow>=2.13.0  # or pytorch>=2.0.0
optuna>=3.3.0
shap>=0.42.0
matplotlib>=3.7.0
seaborn>=0.12.0
plotly>=5.16.0
jupyterlab>=4.0.0
```

---

## Next Steps

1. **Set up ml_orb_5m project structure** (folders, config files)
2. **Fetch external data** (SPY, QQQ, VIX, sector ETFs from Polygon.io)
3. **Start feature engineering notebook** (01_feature_engineering.ipynb)
4. **Build feature calculation functions** (src/features/*.py)
5. **Generate training dataset** (2021-2023 trades with all features)
6. **Train baseline LightGBM model** (quick validation of approach)
7. **Iterate on features** based on importance scores

**Estimated timeline:** 6 weeks to first ML-enhanced backtest results.
