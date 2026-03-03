# ORB Backtest Strategy & Logic Chain

This document serves as the **Source of Truth** for the Opening Range Breakout (ORB) strategy implementation. All live trading components MUST adhere to the logic defined here to maintain consistency between backtest predictions and live execution.

## Strategy Overview
The strategy identifies high-momentum stocks within the first 5 minutes of the market open and enters a long position on a breakout of the Opening Range (OR) high, specifically targeting symbols with high **Relative Volume (RVOL)**.

---

## 1. Selection & Universe Filtering
This phase defines which stocks are eligible for trading today.

### Step-by-Step Selection Chain:
1.  **Technical Pre-Filters**:
    *   **ATR(14)**: Must be `>= 0.50` (Excludes low-volatility "dead" stocks).
    *   **Avg Daily Volume(14)**: Must be `>= 100,000` (Ensures liquidity).
2.  **5-Minute Opening Range (OR) Extraction**:
    *   Calculated from the first bar of the day (`09:30 - 09:35 ET`).
3.  **Price Floor Filter**:
    *   **OR Open**: Must be `>= $5.00`. (Excludes penny stocks and high-volatility micro-caps).
4.  **Directional Signal (Green Candle)**:
    *   **Condition**: `OR Close > OR Open`.
    *   The strategy **only** trades bullish (Green) opening candles.
5.  **RVOL Ranking**:
    *   `RVOL = (OR_Volume * 78) / Avg_Daily_Volume_14`.
    *   Normalization: 78 is the multiplier used to compare the 5-minute OR volume against the 390-minute trading day.
    *   **Execution**: Only the **Top 5** symbols ranked by RVOL are placed on the active watchlist.

---

## 2. Trade Execution & Management
Once a symbol is selected for the Top 5 watchlist:

### Entry Logic
*   **Trigger**: A buy order is triggered if any subsequent 5-minute bar reaches or exceeds the `OR_High`.
*   **Price**: Executed at `OR_High + Spread` (Market/Limit offset).

### Risk Management (Examine/Exit)
*   **Position Sizing**:
    *   Equal allocation across Top 5 watchlist.
    *   Leverage: **6.0x**.
    *   Budget: `(Account Equity / 5) * 6`.
*   **Stop Loss**:
    *   Trailing/Fixed Level: `OR_High - (0.10 * ATR_14)`.
    *   Trigger: Any 5-minute bar where `Low <= Stop_Level`.
*   **End-of-Day (EOD) Exit**:
    *   All positions MUST be flattened at market close.
    *   Backtest Exit: Final 5-minute bar (`15:55 - 16:00 ET`).
    *   Live Implementation: **15:45 ET** (provides buffer for MOC cutoff).

---

## 3. Discrepancy Gate
Any trade observed in Live that does NOT appear in the Backtest for the same date represents a **bug** in the live implementation's adherence to this source of truth.
