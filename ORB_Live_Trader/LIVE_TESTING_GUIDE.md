# ORB Live Trading: Go-Live Guide

Transitioning from local verification to live execution requires a disciplined, phased approach. Since the `TradeZero` execution is Selenium-based, absolute reliability and monitoring are key.

## 1. Prerequisites Checklist

Before running `main.py` in live mode, ensure the following are confirmed:
- [ ] **API Keys**: Alpaca API keys in `.env` have "Market Data" access.
- [ ] **TradeZero Credentials**: Username, Password, and **MFA Secret** are correctly set in `.env`.
- [ ] **Stable Environment**: The machine running the script (Local PC or VPS) must stay awake between 09:00 ET and 16:15 ET.
- [ ] **Browser Drivers**: Ensure the correct `chromedriver` is in path for Selenium.

---

## 2. Recommended Go-Live Phases

### Phase 1: The Built-in "Dry Run"
**Goal**: Verify that the pipeline triggers and order logic identifies breakouts correctly using live data, but without submitting orders to TradeZero.

1.  **Usage**: Run `main.py` with the new `--dry-run` flag.
    ```bash
    python ORB_Live_Trader/main.py --dry-run
    ```
2.  **Action**: The script will login to TradeZero, monitor live quotes, and track breakouts.
3.  **Check**: When a breakout occurs, you will see `[DRY RUN] Would place BUY...` in the console. This confirms your logic is ready.

### Phase 2: Single-Share "Penny" Test
**Goal**: Verify the Selenium integration actually clicks the buttons and fills an order.

1.  **Setting**: Set your `position_sizing` or `quantity` logic to fixed `1` share for all trades (or run normally but watch closely).
2.  **Action**: Run `python ORB_Live_Trader/main.py` (Real mode).
3.  **Check**: Monitor the TradeZero dashboard. Confirm the order appears, fills, and the stop loss is moved correctly.

### Phase 3: Restricted Go-Live
**Goal**: Trade with real capital but limited exposure.

1.  Set a Max Daily Loss or restricted per-trade dollar amount.
2.  Let the algorithm run autonomously while monitoring the logs via `tail -f`.

---

## 3. Scheduler & Automation

To automate the daily cycle, use the following schedule:

### The Daily Timeline (Eastern Time)
| Time | Action | Purpose |
| :--- | :--- | :--- |
| **09:10 ET** | **Pipeline Trigger** | Fetches fresh news, scores sentiment, and builds `daily_YYYY-MM-DD.parquet`. |
| **09:25 ET** | **Main Runner Starts** | Opens browser, logs into TradeZero, and waits for 09:30. |
| **16:10 ET** | **Post-Session Cleanup** | Script flattens and logs out automatically. |

### Setup on Windows (Task Scheduler)
1.  Create a `.bat` file:
    ```batch
    @echo off
    cd /d "C:\Path\To\Opening Range Breakout (ORB)"
    call conda activate your_env
    python ORB_Live_Trader/main.py
    pause
    ```
2.  Create a Task in **Windows Task Scheduler**:
    - **Trigger**: Daily at 09:20 AM ET.
    - **Settings**: "Run only when user is logged on" (since Selenium needs a GUI session unless running in advanced headless mode).

---

## 4. Monitoring & Debugging

### Real-Time Log Tailing
Open a dedicated PowerShell window and run:
```powershell
Get-Content -Path "ORB_Live_Trader/logs/session_YYYY-MM-DD.log" -Wait
```

### Critical Failure Recovery
- **Selenium Hangs**: If the browser freezes, kill the process. `main.py` is designed to be restartable—it will check existing positions upon login and resume monitoring.
- **MFA Errors**: If MFA fails, check that your `TRADEZERO_MFA_SECRET` is correctly imported into your authenticator/script.
- **Internet Blip**: If connection is lost, the script will retry quote fetching. If it stays down for > 5 mins, manual flattening via phone app is advised.

---

> [!WARNING]
> Always verify the **EOD Flattening** at 16:00 ET. Do not rely 100% on the script for the first week; stay near your computer to ensure no orphaned positions are carried overnight.
