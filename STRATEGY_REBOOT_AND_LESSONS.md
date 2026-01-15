# Strategy Reboot & Engineering Post-Mortem
**Date:** January 15, 2026
**Status:** CRITICAL_REFLECTION
**Author:** GitHub Copilot (on behalf of the Engineering Team)

---

## 🛑 The "Data is GOD" Manifesto

In the last 30 days, we failed because we trusted **processes** (logs, timestamps, "job completed" statuses) instead of verifying **outcomes** (the actual data in the file). We traded on assumptions. 

**New Rule:** The system does not ask "Did the data update run?" 
**New Rule:** It asks "I am holding the data file. Does the last row equal yesterday's date?" 

If the answer is "No", the system **must crash immediately**.

---

## 1. The Strategy: Source of Truth

This section defines the strategy with **zero ambiguity**. This is the blueprint for the rebuild.

### A. The Universe (Strict)
*   **Target:** Micro-Cap Stocks (High Volatility, Low Float).
*   **Source File:** `data/backtest/orb/universe/universe_micro_full.parquet` (or equivalent verified subset).
*   **Constraint:** The strategy **ONLY** trades symbols present in this list.
*   **Scanning Logic:** Never scan "All Symbols". Always iterate through the defined Universe list.

### B. The Filters (Fail-Closed)
A trade is **FORBIDDEN** unless it passes all filters.

1.  **Sentiment Filter (The Gatekeeper)**
    *   **Source:** Alpaca News API (24h Window: yesterday 9:30 AM - today 9:30 AM).
    *   **Model:** FinBERT (ProsusAI/finbert).
    *   **Threshold:** `Label = Positive` AND `Score >= 0.90`.
    *   **Action:** If a stock has 0 news, or scores < 0.90: **REJECT**.
    *   **Failure Mode:** If News API is down or Model fails to load: **ABORT ALL TRADING**.

2.  **Relative Volume (RVOL)**
    *   **Calculation:** `Today's Volume (Projected/Current) / 20-Day Average Volume`.
    *   **Role:** Ranking mechanism. High sentiment + High RVOL = Top Priority.

3.  **Price Constraints**
    *   **Cap:** None. (Removed to match historical runners like GME/AMC).
    *   **Direction:** **Long Only**. (Short selling is permanently disabled for this strategy).

---

## 2. Post-Mortem: The 30-Day Mistakes
*A specific autopsy of why the previous iteration failed.*

### 💀 Mistake 1: The "Fail-Open" Bug (The DUOL Incident)
*   **What happened:** The Sentiment Scanner was treated as an "optional" filter. When the data wasn't initialized, the code defaulted to allowing *all* trades, assuming "No news is good news."
*   **Why it failed:** It allowed a Large Cap (DUOL) to be traded because the Universe input defaulted to `None` (meaning "All Market") and the sentiment check returned "Pass" on empty data.
*   **The Fix:** **Fail-Closed Architecture.**
    *   Code must default to `return False` / `return Empty List`.
    *   Explicitly pass the Universe. If `universe is None`, raise `ValueError`.

### 💀 Mistake 2: The "False Green" Data Sync
*   **What happened:** On Jan 15th, the system reported "All data up to date."
*   **Why it failed:** The specific file `CJMB.parquet` had a modified timestamp of Jan 14th 1:30 PM. The file *existed*, so the file-checker passed. But the *content* only went up to Jan 13th. The sync job ran mid-day and didn't capture the close.
*   **The Fix:** **Content Verification ("Data Guard").**
    *   Do not check file timestamps.
    *   Open the file. Read `df.iloc[-1].date`.
    *   Assert `last_date == previous_trading_day`.
    *   If False: `sys.exit(1)`.

### 💀 Mistake 3: Configuration Drift (Live vs. Backtest)
*   **What happened:** We added a `$20 Price Cap` to the live scanner "for safety," which was **never** present in the backtest.
*   **Why it failed:** It filtered out the best performing setups (like high-priced momentum runners), breaking the statistical edge calculated in research.
*   **The Fix:** **Single Config Source.**
    *   One `config.yaml` or `settings.py` drives BOTH the backtest engine and the live execution engine.
    *   Manual overrides in live scripts are banned.

### 💀 Mistake 4: Implicit Time Assumptions
*   **What happened:** We assumed because we ran a script "in the morning," it processed "yesterday's data."
*   **Why it failed:** Scripts are dumb. If the scheduler misses a beat, or a timezone variable is wrong, the script processes old data silently.
*   **The Fix:** **Explicit Time Windows.**
    *   All fetchers must require explicit `start_dt` and `end_dt` arguments.
    *   Calculate `target_date = now()`. If the data found is `target_date - 2 days`, throw an error.

---

## 3. The New Architecture Rules (Reboot Protocol)

For the restart, we adhere to these engineering principles:

1.  **Orchestrator Pattern**: A robust "Orchestrator" script runs the sequence. It does not proceed to Step 2 until Step 1 is verified with **Data Guard**.
    *   *Step 1: Sync & Verify Data (Hard Stop if stale).*
    *   *Step 2: Generate Universe & Sentiment (Hard Stop if empty).*
    *   *Step 3: Execution.*

2.  **No "All" Defaults**: Functions like `get_universe()` or `scan_market()` never default to "All Tickers". They must require a specific list.

3.  **Strict Logging**: Logs must state *what* they found, not just that they finished.
    *   *Bad:* "Sync complete."
    *   *Good:* "Sync complete. Processed 2,744 symbols. Last date verified: 2026-01-14."

4.  **Premium Data Utilisation**: We pay for Alpaca Premium.
    *   **Always** fetch fresh aggregates for the critical decision window.
    *   **Never** rely solely on a local database that might be 12 hours old for critical signals.

---

*This document serves as the constitution for the project reboot. All code verification must reference these rules.*
