# Opening Range Breakout (ORB) Strategy: End-to-End Documentation

## 1. Strategy Overview (The "Layman's" Explanation)

### The Big Idea
The stock market is most volatile and active right when it opens at 9:30 AM. This strategy tries to catch the "momentum" of that initial burst. We assume that if a stock starts strong and breaks out of its opening price range, it will keep moving in that direction for the rest of the day.

### Step 1: The Setup (9:30 AM – 9:35 AM)
When the market bell rings, we do **nothing** for exactly 5 minutes. We just watch.
*   We look at the very first 5-minute candle (bar) of the day.
*   We mark the **High** price and the **Low** price of that 5-minute period.
*   This creates our "Opening Range."

### Step 2: The Checklist (The Filters)
Before we even think about trading, the stock must pass a strict checklist. If it fails any of these, we walk away.

1.  **The "Crowd" Check (Relative Volume)**:
    *   We look at how many shares were traded in those first 5 minutes.
    *   Is it *unusually* busy? We want to see volume that is higher than normal for that specific stock. If it's a quiet day, we don't trade.

2.  **The "Direction" Check**:
    *   Did the price go UP or DOWN during those first 5 minutes?
    *   If it went **UP** (Green candle), we are only allowed to **Buy** (Go Long).
    *   If it went **DOWN** (Red candle), we are only allowed to **Bet Against It** (Go Short).

3.  **The "AI Brain" Check (Our Secret Weapon)**:
    *   Before taking the trade, we ask our Machine Learning model: *"Given the current market mood (SPY, VIX), the gap this morning, and the volatility, is this trade likely to work?"*
    *   The AI gives us a probability score (e.g., "55% chance of winning").
    *   If the score is too low (below 40%), we skip the trade, even if everything else looks perfect.

### Step 3: The Trigger (Entry)
If the checklist passes, we set a "trap":
*   **For a Buy Trade**: We place an order to buy immediately if the price breaks **above** the High of the first 5 minutes.
*   **For a Short Trade**: We place an order to sell immediately if the price breaks **below** the Low of the first 5 minutes.

If the price stays inside that range all day, we never enter.

### Step 4: The Safety Net (Stop Loss)
As soon as we enter, we set a safety exit.
*   We calculate the stock's "normal" daily volatility (ATR).
*   We place a Stop Loss order a specific distance away from our entry.
*   **In simple terms:** If the trade goes against us by a calculated amount, we admit we were wrong and exit immediately to prevent a small loss from becoming a big disaster.

### Step 5: The Exit (Payday)
We hold the trade throughout the day. We exit in two scenarios:
1.  **Bad Scenario**: The price hits our Safety Net (Stop Loss). We take a small loss.
2.  **Good Scenario**: The market closes (4:00 PM). We sell everything and take whatever profit (or loss) we have at the end of the day.

---

## 2. AI Model & Training Details

### Training Period (The "Textbook")
*   **Training Data**: All historical data **before January 1, 2024**.
*   **Testing Data**: Data from **2024 and 2025** was used as "unseen" exams to verify the strategy works on data it has never seen before.

### The Features (The "Inputs")
The AI looks at **25 specific clues** for every trade, categorized as follows:

#### A. The Opening Range (Price Action)
*   `or_range_pct`: How big is the first 5-minute candle relative to the price? (Big moves = high momentum).
*   `or_body_pct`: Is the candle mostly solid body or mostly wicks? (Solid body = strong conviction).
*   `or_close_vs_open`: Did it close near the top or bottom?
*   `or_upper_shadow` / `or_lower_shadow`: Are there long wicks rejecting prices?
*   `gap_pct`: Did the stock gap up or down overnight?

#### B. Market Context (The "Weather")
*   `spy_above_sma50`: Is the overall market (SPY) in a long-term uptrend?
*   `qqq_trend_5d`: Is the Tech sector (QQQ) trending up or down this week?
*   `vix_level`: Is the "Fear Index" (VIX) high or low? (High fear usually means more volatility).
*   `vix_change_5d`: Is fear rising or falling?

#### C. Volatility (The "Energy")
*   `atr_14_daily`: What is the stock's normal daily range?
*   `or_range_vs_daily_atr`: Is this morning's move unusually explosive compared to normal?
*   `volatility_trend_5d_20d`: Is the stock becoming more volatile lately?

#### D. Technical Levels
*   `distance_to_prev_high`: How close are we to yesterday's high? (Breakouts often stall there).
*   `distance_to_prev_low`: How close are we to yesterday's low?

#### E. Time
*   `day_of_week`: Certain days (like Fridays) behave differently.

## 3. Experiment: Removing Market Context (November 2025)

### Motivation
We wanted to test if the strategy relies too heavily on broad market indicators (SPY, QQQ, VIX). If the strategy is robust, it should be able to find profitable trades based purely on the stock's own price action and volatility, without needing to know if the S&P 500 is up or down.

### The Experiment
*   **Action**: We retrained the AI models (Long and Short) using a reduced feature set.
*   **Removed Features**: All features related to SPY, QQQ, and VIX (e.g., `spy_trend`, `vix_level`).
*   **Remaining Features**: Only stock-specific Price Action, Volatility, and Technical Levels.

### Results (Pre-2024 Training Data)
The models performed surprisingly well even without market context, suggesting the core "Opening Range Breakout" signal is strong on its own.

| Model | AUC Score | Precision | Win Rate (Baseline) |
| :--- | :--- | :--- | :--- |
| **Long Model** | **0.726** | 25.2% | 16.16% |
| **Short Model** | **0.749** | 33.6% | 18.99% |

*Note: An AUC > 0.5 indicates the model is better than random guessing. Scores above 0.70 are considered strong for financial data.*

### Visualizations

#### Long Model Performance
**ROC Curve (Ability to distinguish winners)**
![Long ROC Curve](reports/figures/roc_curve_long_no_context.png)

**Feature Importance (What matters most?)**
![Long Feature Importance](reports/figures/feature_importance_long_no_context.png)

#### Short Model Performance
**ROC Curve**
![Short ROC Curve](reports/figures/roc_curve_short_no_context.png)

**Feature Importance**
![Short Feature Importance](reports/figures/feature_importance_short_no_context.png)
