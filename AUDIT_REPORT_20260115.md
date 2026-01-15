# Critical Systems Audit Report: ORB-Live-001
**Date**: January 15, 2026
**Auditor**: GitHub Copilot (Agent)
**Subject**: Unintended Position Entry (DUOL) & Sentiment Filter Failure

## 1. Executive Summary
The live trading system executed a trade on **DUOL** ($150+ share price, Neutral Sentiment) which resulted in a loss. This violated the user's intended strategy of trading **Micro-cap** stocks with **Positive Sentiment (>0.90)**.

The failure was caused by two critical configuration and logic gaps:
1.  **Defaulting to "All" Universe**: The live configuration `ORB_UNIVERSE` was not restricted to "micro", allowing Large Cap stocks like DUOL (`rank: 2` today) to be scanned.
2.  **"Fail-Open" Logic in Sentiment**: The scanner is designed to *skip* the sentiment filter if the daily data file (`allowlist_YYYY-MM-DD.json`) is missing, ensuring the system runs even if data is late. This "availability over correctness" design choice caused it to ignore the missing sentiment data instead of aborting.

## 2. Incident Analysis: Why DUOL was traded

### A. The Price/Cap Violation
*   **Expectation**: Strategy runs on Micro-caps (e.g., < $20, Low Float).
*   **Reality**: `DUOL` trading at ~$155 was selected.
*   **Root Cause**: 
    *   The `manual_scanner.py` and `orb_scanner.py` do not enforce a `max_price` cap by default.
    *   They rely on the **Universe File** to provide the filter.
    *   **Settings Gap**: The system defaulted to `ORB_UNIVERSE="all"` (implied default in `orb_scanner.py`), which loads *all* available daily bars, not the restricted `universe_micro_full.parquet`.

### B. The Sentiment Violation
*   **Expectation**: Only trade stocks with Sentiment Score > 0.90.
*   **Reality**: DUOL (Sentiment Score ~0.0) was traded.
*   **Root Cause**:
    *   The file `data/sentiment/allowlist_2026-01-15.json` **does not exist**.
    *   **Logic Flaw**: In `prod/backend/services/orb_scanner.py`, lines 240-244:
        ```python
        if sentiment_allowed is not None:
            # ... apply filter ...
        else:
            print(f"[Sentiment] Filter enabled but no allowlist found for {today}. Skipping.")
        ```
    *   The code explicitly chose to **proceed without filtering** rather than stopping. This is a "Fail-Open" design which is dangerous for filter-dependent strategies.

## 3. Codebase / Strategy Gap
The user asks: *"Our baseline strategy was supposed to be modeled after the fast_backtest."*

*   **`fast_backtest.py`**:
    *   Takes a `--universe` argument (e.g., `universe_2021...parquet`).
    *   **Doesn't** have runtime price caps; it assumes the universe file is already filtered.
    *   **Doesn't** have runtime sentiment fetch; it assumes the universe is pre-filtered (e.g. `universe_sentiment_0.90.parquet`).
*   **`orb_scanner.py` (Live)**:
    *   Attempts to replicate this by loading a universe and intersecting with an allowlist.
    *   **CRITICAL FAILURE**: It allows the system to run "Unfiltered" if inputs are missing, whereas `fast_backtest.py` would simply crash or return 0 results if the universe file was wrong.

## 4. Remediation Plan

### Immediate Code Fixes (Required for Trust)
1.  **Switch to Fail-Closed**: Modify `orb_scanner.py` to **ABORT** the scan (or return 0 candidates) if `use_sentiment_filter=True` but the data is missing.
2.  **Enforce Universe Config**: Hardcode or strictly validate `ORB_UNIVERSE` setting.
3.  **Add Max Price Cap**: Add explicit `max_price=20.0` (or similar) to the scanner arguments to prevent Large Cap leakage even if the universe file is broad.

### Process Fixes
1.  **Sentiment Job Integration**: The script to generate `allowlist_YYYY-MM-DD.json` must be added to the scheduler *before* the scanner runs (e.g., 9:00 AM).

---
**Status**: Pending User Approval for Code Changes.
