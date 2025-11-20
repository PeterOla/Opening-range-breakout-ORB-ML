# Analysis of Missed Winners & Bear Market Performance

## 1. The "Missed Winners" Problem
We analyzed the 1,379 winning trades that the ML model rejected (Threshold 0.60).
*   **Average ML Probability**: 0.37 (The model strongly disliked them).
*   **Cause**: The model is heavily biased towards **Longs in Bull Markets**. It rejects most counter-trend trades or trades in choppy conditions, even if they turn out to be winners.

## 2. Long vs. Short Asymmetry
The model is significantly better at picking Longs.

| Side | Available Trades | Baseline Win Rate | ML Selected | ML Win Rate |
| :--- | :--- | :--- | :--- | :--- |
| **Long** | 4,411 | 14.0% | 71 | **36.6%** |
| **Short** | 4,956 | 17.0% | 215 | **26.5%** |

*   **Insight**: The model is a "Long Sniper" but a "Short Guesser". It struggles to identify high-probability shorts, likely because the features (SPY > SMA50) are optimized for bullish regimes.

## 3. Relaxing the Filter (Dynamic Thresholds)
We tested using a lower threshold for Shorts to catch more winners.

| Scenario | Win Rate | Profit Factor | Return | Drawdown | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline** | 15.6% | 1.82 | **802%** | -5.1% | High volume, low accuracy. |
| **ML (0.60)** | **28.9%** | **2.48** | 35% | **-2.4%** | "Sniper". High accuracy, low volume. |
| **ML (0.50)** | 21.6% | 1.98 | 131% | -3.9% | Balanced approach. |
| **L:0.6 / S:0.45** | 20.0% | 1.86 | 133% | -4.3% | Catches more shorts, but quality drops. |

## 4. Recommendations

### Option A: The "Balanced" Approach (Recommended for now)
Use a **Global Threshold of 0.50**.
*   **Why**: It captures ~1,400 trades (vs 287), increasing total return to **130%**, while still keeping Win Rate > 21% (significantly better than baseline 15%).

### Option B: The "Specialist" Approach (Future Work)
To truly fix Bear Market performance, we need to **Split the Models**.
1.  **Train `Long_Model`**: Trained only on Long trades.
2.  **Train `Short_Model`**: Trained only on Short trades.
    *   This allows the Short model to learn that "Market Weakness" is a *positive* signal for shorts, rather than a negative signal for everything.
