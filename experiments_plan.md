# Strategy Comparison Master Plan

## Objective
Identify the "Golden Strategy" by systematically comparing performance across Universe, Model, Features, and Sizing dimensions.

## 1. The Comparison Matrix (Experiments)

We will run the following combinations. All runs will use **Standardized Benchmark Costs** ($0.01 slippage, $1.00 min comm) to ensure a fair, apples-to-apples comparison before we worry about specific broker fees.

| ID | Strategy Type | Universe | Model / Logic | Features | Sizing |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1.1** | Baseline | Top 20 | Rules Only (No ML) | N/A | Fixed (1%) |
| **1.2** | Baseline | Top 50 | Rules Only (No ML) | N/A | Fixed (1%) |
| | | | | | |
| **2.1** | ML - XGBoost | Top 20 | Dual Model (Long/Short) | **With** Market Context | Fixed (1%) |
| **2.2** | ML - XGBoost | Top 50 | Dual Model (Long/Short) | **With** Market Context | Fixed (1%) |
| | | | | | |
| **3.1** | ML - XGBoost | Top 20 | Dual Model (Long/Short) | **NO** Market Context | Fixed (1%) |
| **3.2** | ML - XGBoost | Top 50 | Dual Model (Long/Short) | **NO** Market Context | Fixed (1%) |
| | | | | | |
| **4.1** | ML - LogReg | Top 20 | Logistic Regression | **With** Market Context | Fixed (1%) |
| **4.2** | ML - LogReg | Top 50 | Logistic Regression | **With** Market Context | Fixed (1%) |
| **4.5** | ML - LogReg | Top 20 | Logistic Regression | **NO** Market Context | Fixed (1%) |
| **4.6** | ML - LogReg | Top 50 | Logistic Regression | **NO** Market Context | Fixed (1%) |
| | | | | | |
| **5.1** | ML - LSTM | Top 50 | LSTM (Sequential) | Price Sequence | Fixed (1%) |
| **5.2** | ML - LSTM | Top 20 | LSTM (Sequential) | Price Sequence | Fixed (1%) |
| | | | | | |
| **6.1** | ML - Ensemble | Top 50 | LightGBM + XGB + LSTM | All Features | Fixed (1%) |
| **6.2** | ML - Ensemble | Top 20 | LightGBM + XGB + LSTM | All Features | Fixed (1%) |
| | | | | | |
| **0.1** | **Theoretical** | Top 50 | Rules Only | N/A | Fixed (1%) |
| **0.2** | **Theoretical** | Top 50 | XGBoost Dual | With Context | Fixed (1%) |

*Note: Theoretical runs use $0.00 slippage and $0.00 commission to establish the "Ceiling" performance.*

## 2. Sizing Optimization (The Kelly Test)

**Validate Edge Before Aggression**

Once we identify the **Winner** from Section 1 (the most robust strategy), we will run a dedicated test to apply **Kelly Criterion** sizing to it.

*   **Goal**: Verify if the model's probability estimates are accurate enough to support aggressive position sizing without excessive drawdown.
*   **Metric**: Compare `Total Return` and `Max Drawdown` of Fixed vs. Kelly for the winning strategy.

## 3. Broker Scenarios (Deployment Check)

Once the best strategy is identified and sized, we will validate it against specific broker profiles:

1.  **Interactive Brokers (IBKR Pro - Tiered)**:
    *   Slippage: $0.01/share (Good execution)
    *   Commission: $0.0035/share
    *   Min Commission: $0.35/trade
2.  **Alpaca (Commission Free)**:
    *   Slippage: $0.02/share (PFOF / Worse execution)
    *   Commission: $0.00/share
    *   Min Commission: $0.00/trade

## 3. Edge Cases & Stress Tests (The "What Ifs")

I have added these specific scenarios to test robustness:

1.  **The "Junk" Filter Sensitivity**:
    *   We know Price < $5 kills us. What if we raise it to **$10**? Does performance improve or do we lose too many opportunities?
2.  **Liquidity Shock**:
    *   Re-run the best performing model with **$0.03 slippage** (3x normal). If it survives this, it's bulletproof.
3.  **Sector Concentration Risk**:
    *   Check if 80%+ of trades are in one sector (e.g., Tech). If so, the strategy is just a "QQQ Proxy" and not a true alpha.
4.  **Long vs. Short Asymmetry**:
    *   Does the strategy only work on the Long side? If Shorting loses money net-net, we might cut it entirely to simplify operations.

## 3. Execution Plan (Re-run from Scratch)

1.  **Data Prep**: Ensure Top 20 and Top 50 datasets are clean and aligned.
2.  **Model Training (The Heavy Lift)**:
    *   *Existing*: XGBoost Dual (With Context).
    *   *To Train*: XGBoost Dual (No Context).
    *   *To Train*: Logistic Regression (With/Without Context).
    *   *To Train*: LSTM (Sequential Price Data).
    *   *To Train*: Ensemble (LGBM + XGB + LSTM).
3.  **Simulation Batch**:
    *   Create a `run_experiments.py` script to loop through the Matrix.
    *   Generate a single `master_comparison.csv` with columns: `Strategy_ID`, `Win_Rate`, `Profit_Factor`, `Total_Return`, `Max_DD`, `Kelly_Pct`.
4.  **Analysis**:
    *   Generate the "Winner's Report".

## 4. Output Format (CSV Structure)

The final CSV will look like this:

```csv
experiment_id, strategy, universe, model_type, use_context, sizing_method, trades, win_rate, profit_factor, total_pnl, max_drawdown, sharpe_ratio
1.1, Baseline, Top20, RuleBased, False, Fixed, 1500, 0.16, 1.1, 5000, -200, 0.5
...
```
