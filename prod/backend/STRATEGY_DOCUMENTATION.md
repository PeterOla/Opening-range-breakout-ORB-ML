# ORB Strategy Documentation

## Overview
This document outlines the core logic for the Opening Range Breakout (ORB) strategy, specifically focusing on **Position Sizing** and **Risk Management**.

## 1. Position Sizing (Equal Dollar Allocation)
The system uses an **Equal Dollar Allocation** model, not a fixed risk-per-trade model. This ensures that every trade receives the same amount of buying power, regardless of the stock's price or volatility.

### Formula
$$ \text{Shares} = \frac{(\text{Total Capital} / \text{Top N}) \times \text{Leverage}}{\text{Entry Price}} $$

### Parameters
*   **Total Capital (`TRADING_CAPITAL`):** The base account size (e.g., $1,000).
*   **Top N (`top_n`):** The number of trades to take per day (e.g., 5).
*   **Leverage (`FIXED_LEVERAGE`):** The leverage multiplier (e.g., 5x).

### Example Calculation
*   **Capital:** $1,000
*   **Top N:** 5 Trades
*   **Leverage:** 5x
*   **Stock Price:** $10.00

1.  **Allocation per Trade:** $1,000 / 5 = $200 (Cash)
2.  **Buying Power per Trade:** $200 * 5 = $1,000 (Leveraged)
3.  **Shares:** $1,000 / $10.00 = **100 Shares**

---

## 2. Risk Management

### Stop Loss
*   **Mechanism:** 10% of the 14-day Average True Range (ATR).
*   **Long Stop:** `Entry Price - (0.10 * ATR)`
*   **Short Stop:** `Entry Price + (0.10 * ATR)`

### Risk per Trade (Estimated)
Since position size is fixed (Equal Dollar), the actual dollar risk varies based on the stock's volatility (ATR).
*   **Risk Formula:** `Shares * Stop Distance`
*   **Example:**
    *   Shares: 100
    *   ATR: $0.50
    *   Stop Distance: $0.05 (10% of ATR)
    *   **Dollar Risk:** 100 * $0.05 = **$5.00**

### Kill Switch
*   **Daily Loss Limit:** Trading stops if the account loses more than `DAILY_LOSS_LIMIT_PCT` (default 10%) in a single day.

---

## 3. Execution Rules

### Entry
*   **Time:** 9:30 AM - 9:35 AM ET (First 5-minute candle).
*   **Long:** Buy if price breaks **ABOVE** the High of the first 5-min candle.
*   **Short:** Sell if price breaks **BELOW** the Low of the first 5-min candle.

### Exit
*   **Stop Loss:** Triggered immediately if price hits the stop level.
*   **End of Day (EOD):** All open positions are closed at 3:55 PM ET.

---

## 4. Configuration
Settings are managed in `prod/backend/core/config.py` and `.env`.

| Setting | Default | Description |
| :--- | :--- | :--- |
| `TRADING_CAPITAL` | 1000.0 | Base account size |
| `FIXED_LEVERAGE` | 5.0 | Leverage multiplier |
| `ORB_STRATEGY` | top5_both | Strategy preset (Top 5 Long & Short) |
| `ORB_UNIVERSE` | micro_small | Universe filter (Micro < 50M shares) |
