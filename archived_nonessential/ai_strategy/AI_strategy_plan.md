# Plan: Use AI to Build and Improve Trading Strategies

This file is a **step‑by‑step checklist** to go from your raw minute data → AI model → trading strategy.

---

## 1. Prepare Data for AI

- [x] Decide initial timeframe (our default):
  - [x] Use **5‑minute** bars for **modeling and feature building** (less noise, faster training).
  - [x] Keep **1‑minute** bars available for **execution/backtesting** (more precise fills and P&L).
- [x] Confirm each parquet has:
  - [x] `timestamp`
  - [x] `open`
  - [x] `high`
  - [x] `low`
  - [x] `close`
  - [x] `volume`
  - [x] `symbol`
- [x] Ensure:
  - [x] Data sorted by `timestamp`.
  - [x] No duplicate timestamps per `symbol`.
  - [x] Timestamps are timezone‑consistent (UTC or NY time).

**Next:** Open one parquet file in a notebook and visually check the columns and ordering.

---

## 2. Build Basic Features (Per Symbol)

Goal: turn raw OHLCV bars into numeric features that a model can use.

- [x] Create a script: `ai_strategy/build_features_5min.py` (prototype for one symbol, e.g., AAPL).
- [x] For one symbol (AAPL):
  - [x] Load 5m parquet.
  - [x] Sort by `timestamp`.
  - [x] Add simple features:
    - [x] 1‑bar return: `ret_1`
    - [x] 5‑bar return: `ret_5`
    - [x] Short MA: `ma_10`
    - [x] Long MA: `ma_50`
    - [x] MA ratio: `ma_ratio = ma_10 / ma_50`
    - [x] Volume MA: `vol_ma_20`
    - [x] Relative volume: `rvol_20 = volume / vol_ma_20`
  - [x] Add label (target) for the model:
    - [x] Forward 5‑bar return: `ret_fwd_5`
  - [x] Drop rows with missing values in features or label.

**Minimal code sketch:**

```python
# ...existing code...
df["ret_1"] = df["close"].pct_change(1)
df["ret_5"] = df["close"].pct_change(5)
df["ma_10"] = df["close"].rolling(10).mean()
df["ma_50"] = df["close"].rolling(50).mean()
df["ma_ratio"] = df["ma_10"] / df["ma_50"]
df["vol_ma_20"] = df["volume"].rolling(20).mean()
df["rvol_20"] = df["volume"] / df["vol_ma_20"]
df["ret_fwd_5"] = df["close"].shift(-5).pct_change(5)
# ...existing code...
```

- [ ] Save / inspect a small sample of the feature table.

**Next:** Run the script for **one symbol** and print the first 10 rows to confirm features look sane.

---

## 3. Train a First ML Model (Simple Baseline)

Goal: show that the pipeline works end‑to‑end for one symbol.

- [x] Create `ai_strategy/train_model_5min.py`.
- [x] Use these features:
  - [x] `['ret_1', 'ret_5', 'ma_ratio', 'rvol_20']`
- [x] Use label:
  - [x] `ret_fwd_5`
- [x] Train/test split:
  - [x] Use the **earliest 80%** of rows for training.
  - [x] Use the **latest 20%** for testing.
  - [x] Do **not shuffle** (keep time order).
- [x] Model:
  - [x] Use `RandomForestRegressor` (scikit‑learn).
- [x] After training:
  - [x] Generate predictions on the test set.
  - [x] Print a small table of `timestamp`, `ret_fwd_5`, `pred`.

**Minimal code sketch:**

```python
# ...existing code...
model = RandomForestRegressor(
    n_estimators=200,
    max_depth=6,
    n_jobs=-1,
    random_state=42,
)
model.fit(X_train, y_train)
df_test["pred"] = model.predict(X_test)
# ...existing code...
```

- [ ] Check that:
  - [ ] Script runs without errors.
  - [ ] Predictions are finite numbers (no NaN / inf).

**Next:** Run `python scratch/train_model_example.py` and inspect printed predictions.

---

## 4. Turn Predictions into a Simple Strategy

Goal: convert model predictions into a basic trading rule and equity curve.

- [x] Create `ai_strategy/simple_strategy_5min.py`.
- [x] Reuse the same features and model as above.
- [x] Define a rule:
  - [x] Long‑only:
    - [x] Compute 90th percentile of `pred` on the test set.
    - [x] `signal = 1` if `pred > cutoff`, else `0`.
- [x] Compute:
  - [x] Strategy return per bar: `strategy_ret = signal * ret_fwd_5`.
  - [x] Equity curve: `(1 + strategy_ret).cumprod()`.
- [x] Print:
  - [x] Number of bars traded.
  - [x] Final total return.

**Implemented in:** `ai_strategy/simple_strategy_5min.py` (tested on AAPL 5m data).

- [ ] Optionally:
  - [ ] Plot the equity curve to visually inspect behavior.

**Next:** Run `python ai_strategy/simple_strategy_5min.py` and note total return and number of trades.

---

## 5. Make It ORB‑Specific

Once the generic pipeline works, adapt it to your ORB strategy.

### 5.1 Build ORB Features (Per Day + Symbol)

- [ ] For each symbol + trading day:
  - [ ] Identify first N minutes (e.g. 5‑minute opening range).
  - [ ] Compute:
    - [ ] `or_open`, `or_high`, `or_low`, `or_close`, `or_volume`.
    - [ ] Direction (green / red / doji).
    - [ ] OR size: `(or_high - or_low) / or_open`.
    - [ ] Gap vs previous close.
    - [ ] ATR(14) from daily data.
    - [ ] Opening‑range RVOL (vs last 14 days).
- [ ] Build a daily table:
  - [ ] One row per symbol per day.
  - [ ] Columns: OR features + ATR + gap + market features (e.g., SPY move).

**Next:** Create `scratch/build_orb_features.py` and implement a first version for 1 symbol.

### 5.2 Add ORB‑Style Labels

- [ ] For each ORB candidate (symbol + day that passes filters):
  - [ ] Simulate ORB trade using 1‑minute data:
    - [ ] Entry at OR high (long) or OR low (short) in allowed direction.
    - [ ] Stop = 10% of ATR(14) from entry.
    - [ ] Exit at EOD if stop not hit.
  - [ ] Build label:
    - [ ] Option 1: `hit_target` = 1 if price reached, say, +2R before stop; else 0.
    - [ ] Option 2: raw intraday P&L in R‑multiples.
- [ ] Attach label to the ORB feature row.

**Next:** Create `scratch/build_orb_labels.py` that, for a small sample of days, returns a table `[features..., hit_target]`.

---

## 6. Train a Model on ORB Setups

- [ ] Use ORB feature table as input `X`.
- [ ] Use `hit_target` (0/1) as `y` (classification) or P&L as regression.
- [ ] Train:
  - [ ] Start with `RandomForestClassifier` (for 0/1 label).
- [ ] Evaluate:
  - [ ] Accuracy or ROC AUC.
  - [ ] Average P&L of top‑probability trades vs all ORB trades.

**Next:** Implement `scratch/train_orb_model.py` and train on a subset of symbols first.

---

## 7. Use the Model to Filter and Size ORB Trades

- [ ] For each trading day:
  - [ ] Generate all ORB candidates.
  - [ ] Compute ORB features.
  - [ ] Use model to predict:
    - [ ] Probability of success (`p_win`) or expected P&L.
  - [ ] Apply rules:
    - [ ] Only trade candidates with `p_win` above a threshold.
    - [ ] Rank by `p_win` and take top N (e.g., top 20).
    - [ ] Size positions based on edge (higher `p_win` → larger size within risk limits).
- [ ] Backtest:
  - [ ] Apply normal ORB rules (entry, stop, EOD exit).
  - [ ] Compare:
    - [ ] Base ORB vs AI‑filtered ORB by Sharpe, MDD, total return.

**Next:** Add a new backtest script `scratch/backtest_orb_ai_filter.py` that plugs the model into your existing ORB backtester.

---

## 8. Scale Up and Clean Up

- [ ] Extend from 1 symbol → full universe (5000 symbols).
- [ ] Parallelize where needed (per symbol / per day).
- [ ] Save:
  - [ ] Feature tables.
  - [ ] Trained models.
  - [ ] Backtest results (trades, daily equity).

**Next:** After it works on a few symbols, move the "scratch" code into proper `src/ai/` modules and wire into your main backtesting pipeline.

---
