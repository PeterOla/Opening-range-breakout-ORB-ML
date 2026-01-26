# ORB Live Trader: Detailed Expected Behavior

This document defines the "Contract of Operation" for the automated ORB trading system. It outlines exactly what should happen at each stage of the trading day.

## 1. Daily Lifecycle (ET)

### 1.1 Pre-Market & Initialization (09:00 - 09:30)
- **TradeZero Standby (09:25)**: Selenium logs into the platform ensuring the session is active before volatility hits.
- **Clock Alignment**: The system remains in standby until exactly **09:30:01 ET** to trigger the primary data pipeline.

### 1.2 Selection & Pool Pool (09:30 - 09:35)
- **News Pull (09:30:01)**: The system runs the `live_pipeline` module to fetch fresh candidates.
- **Micro Universe News**: Fetches news for all 2700+ symbols in the micro-cap universe from 09:30 yesterday to 09:30 today (Rolling 24H).
    - **Source File**: [universe_micro_full.parquet](file:///c:/Users/Olale/Documents/Codebase/Quant/Opening Range Breakout (ORB)/ORB_Live_Trader/data/reference/universe_micro_full.parquet)
- **FinBERT Scoring**: All fetched headlines are scored via FinBERT. Only highly positive items (`sentiment > 0.90`) qualify for the initial pool.
- **Pool Generation**: Identifies the **Top 15** candidates by RVOL.
- **Standby**: The system waits in standby while the market forms the first 5-minute candle.

### 1.3 Entry Execution (Integer Sizing Aligned)
- **At 09:35:05**: 
    - The system immediately submits **BUY STOP** orders for the Top 5 candidates.
    - **Trigger Price**: Exactly at the `or_high`.
- **Sizing Model (Equal Allocation)**: 
    - **Calculation**: `Total Buying Power / 5` per trade.
    - **Integer Sizing**: All share counts are rounded to the nearest whole integer (e.g., 8.67 -> 9), matching the Backtest engine. (Minimum: 1 share).
- **Passive Monitoring**: Once orders are sent, the system waits for the broker to handle the breakout trigger.
- **Fill Detection & Protection**: The moment a Buy Stop fills, the system immediately submits a **Resting SELL STOP** order to the broker at `or_high - (0.05 * ATR_14)`.
- **Risk Management**:
    - **Stop Loss**: Fixed at `or_high - (0.05 * ATR_14)`.
    - **Fees**: Commissions ($0.005/share, min $0.99) are tracked and subtracted from PNL for **Net PNL** reporting.

### 1.4 Market Close (15:55 - 16:00)
- **EOD Flatten (15:55 ET)**: The system initiates flattening 5 minutes before the bell to ensure liquidity.
- **Relentless Retry**: If any position fails to close, the system automatically retries every 10 seconds until **exactly 16:00:00 ET** or until all positions are 100% flattened.
- **Safe Exit**: Uses `safe_place_market_order` which falls back to Limit (Sell at Bid) if Market orders are rejected by the broker.

---

## 2. Data Persistence & Architecture

The system follows a strict "Persistence for Transparency" rule. Every piece of data used to make a trade decision is saved to local subfolders for end-of-day audit.

### 2.1 News & Sentiment (Alpaca)
- **Raw News**: Saved to `data/news/news_YYYY-MM-DD.parquet`.
- **Scored Sentiment**: Saved to `data/sentiment/sentiment_YYYY-MM-DD.parquet`.
- **Review**: You can open these files to see exactly which headlines FinBERT scored and why a symbol entered the watchlist.

### 2.2 Price Data (Alpaca & Local)
- **Live Mode**: Fetches 5-min bars from Alpaca and persists them to `data/bars/` dynamically.
- **Verification Mode**: References the main `data/processed/` archive, but **caches** the specific bars used for that date into `data/bars/` for immediate review.

### 2.3 Execution Monitoring (TradeZero)
- **Positions & Quotes**: Scraped every 5s from the Web UI.
- **Audit Trail**: Every fill event and exit is written to the **Daily Trading Log** in `logs/trading_YYYY-MM-DD.log`.

---

## 3. Advanced Execution Safety

- **Manual Kill Switch**: Aborts the session if `state/orb_kill_switch.lock` exists.
- **R78 Fallback (Limit Protection)**: If a Market order is rejected, the system automatically retries with a **Limit Order** at the current Bid/Ask.
- **Proactive Stop Auditor**: A secondary 60s loop verifies that every fill has a resting stop-loss on the broker's books.
- **Fail-Safe Flatten**: If a protective stop cannot be placed, the system engages the Kill Switch and flattens the position immediately.

---

## 4. State & Recovery
- **DuckDB Integration**: Every trade state and signal is mirrored in `orb_state.duckdb`.
- **Reboot Recovery**: On restart, the system identifies open positions from the broker and resumes stop-monitoring based on the local database.
