# ML-Enhanced ORB Strategy Results

This document tracks the performance of various models and backtests for the ML-Enhanced Opening Range Breakout strategy.

## 1. Pre-ML Baseline (Rule-Based Strategy)
*Performance of the core strategy before any Machine Learning filtering was applied.*

| Metric | Original Backtest | Realistic Simulation (w/ Costs) |
| :--- | :--- | :--- |
| **Total Return** | 18,941% | 5,318% |
| **CAGR** | 185.72% | 122.22% |
| **Win Rate** | 16.79% | 16.13% |
| **Profit Factor** | 1.78 | 1.15 |
| **Max Drawdown** | -20.55% | -94.49% |
| **Trades** | 24,180 | 24,180 |

> **Context:** The rule-based strategy is highly profitable but suffers from massive drawdowns (-94% in realistic sims) and low win rates (~16%). The goal of ML is to improve the **Win Rate** and **Profit Factor** to make the strategy tradeable with lower risk.

---

## 2. Baseline Model Performance (Training Phase)
*Comparison of initial models trained on 2020-2022 data and validated on 2023.*

| Model | AUC | Win Rate (Precision) | Recall | Trades Taken |
| :--- | :--- | :--- | :--- | :--- |
| **XGBoost** | **0.5908** | **21.67%** | 51.17% | 2,012 |
| Logistic Regression | 0.5872 | 20.70% | **55.75%** | 2,295 |
| LightGBM | 0.5652 | 0.00% | 0.00% | 0 |

> **Selected Model:** XGBoost was selected for further development due to the highest AUC and Win Rate.

---

## 3. 2025 Backtest Results (Corrected Top 50 Universe)
*Backtest Parameters: $1,000 Initial Equity, Fixed 1% Risk per Trade, 2024-01-01 to 2025-12-31 (Test Set).*
*Note: Models were retrained on Top 50 RVOL universe (2020-2023) to match the trading universe.*

| Threshold | Trades | Win Rate | Profit Factor | Return | Max Drawdown |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline** | **9,187** | **16.82%** | **1.77** | **731.1%** | **-4.2%** |
| 0.50 | 2,877 | 22.70% | 2.06 | 283.8% | -2.7% |
| **0.60** | **296** | **38.85%** | **3.88** | **59.3%** | **-1.0%** |
| 0.65 | 72 | 44.44% | 4.76 | 17.0% | -0.5% |
| 0.70 | 8 | 25.00% | 0.25 | -0.5% | -0.5% |

**Key Findings:**
*   **Threshold 0.60 is the new "Sweet Spot":** After correcting the training data mismatch (training on Top 50 instead of Top 20), the model's performance at higher thresholds improved dramatically.
*   **High Precision:** At 0.60, the Win Rate jumps to **39%** (from 17% baseline) with a massive **3.88 Profit Factor**.
*   **Trade-off:** The number of trades drops significantly (from ~9k to ~300), but the quality is exceptionally high. This suggests a "Sniper" approach.
*   **Baseline Return:** The baseline return is high due to the sheer volume of trades (9k+) with a positive expectancy, but it comes with higher operational complexity and commission drag (not fully modeled here). The ML model offers a much more efficient path to profitability.

---

## 4. Realistic Simulation (2025 Stress Test)
*Simulation with real-world constraints: $0.01/share slippage, $1.00 min commission, $0.005/share commission.*

### Initial Findings (Unfiltered)
Running the simulation on the full universe resulted in **net losses** across all thresholds.
*   **Cause:** Fixed costs (especially the $1.00 min commission and $0.01 slippage) decimated trades on **Penny Stocks (<$5)** and **Low Volatility Stocks (ATR < 0.5)**.
*   **Impact:** A $0.10 scalp on a $2.00 stock turns into a loss after $0.02 slippage and commissions.

### Filtered Performance (Price > $5, ATR > 0.50)
*Applying filters to remove "junk" trades restored profitability.*

| Threshold | Trades | Win Rate | Profit Factor (Agg) | Total PnL (1% Risk) | R-Multiple |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **0.50** | **1,115** | **16.41%** | **1.18** | **+$2,253** | **+225R** |
| 0.60 | 137 | 16.79% | 0.99 | -$98 | -10R |
| 0.70 | 22 | 18.18% | 1.07 | +$81 | +8R |

**Critical Insights:**
1.  **Profitability Confirmed:** The strategy is profitable under realistic conditions, generating **+225R** in a year (equivalent to +225% on account if fully utilized).
2.  **High Variance:** The Win Rate is low (~16%), meaning the strategy relies on a high **Payoff Ratio (6.03)**. It eats small losses to catch large trend days.
3.  **Threshold Shift:** The "Theoretical Sweet Spot" of 0.60 disappeared under realistic costs. The 0.50 threshold performed best because it provided enough **volume** (1,115 trades) to let the statistical edge play out. The 0.60 threshold filtered out too many trades, leaving a sample size too small to overcome the variance.
4.  **Capital Efficiency:** To trade this effectively, one needs to trade a portfolio of symbols to smooth out the variance of the low win rate.

---

## 5. Historical Performance Comparisons (Previous Iterations)
*Summary of results from previous development phases (Single vs Dual Model).*

| Metric | Baseline (Rule-Based) | Single Model (0.60) | Dual Model (0.60) |
| :--- | :--- | :--- | :--- |
| **Win Rate** | 15.6% | 28.9% | **29.5%** |
| **Profit Factor** | 1.82 | 2.48 | **2.67** |
| **Max Drawdown** | -5.1% | -2.4% | **-1.8%** |
| **Trade Count** | 9,367 | 287 | 363 |

> **Insight:** The Dual Model (separate Long/Short models) demonstrated superior risk-adjusted returns in earlier testing phases, primarily by improving Short side performance.

---

## 5. Feature Importance Summary
*What drives the model's decisions?*

1.  **Market Regime (Trend):** `spy_above_sma50`, `qqq_above_sma50` (Don't fight the trend).
2.  **Volatility Context:** `or_range_vs_daily_atr`, `vix_level` (Avoid exhausted ranges or extreme VIX).
3.  **Candle Structure:** `or_close_vs_open` (Momentum/Conviction).
