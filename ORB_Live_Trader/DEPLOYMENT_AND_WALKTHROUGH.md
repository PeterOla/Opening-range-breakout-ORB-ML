# ORB Live Trader: Final Deployment & Logic Summary
*Date: 2026-02-02 (Live Session Active)*

This document serves as the permanent record of the logic parity achieved with the backtest and the official guide for cloud deployment.

---

## 1. Cloud Deployment Guide (Windows VPS)
The bot requires a **Windows Desktop environment** with at least **8GB RAM** to run FinBERT AI and Selenium together.

### 💰 Recommended Hosting
- **Contabo (Best Value)**: Cloud VPS 2 (~$14.50/mo + Windows License).
- **Vultr (Best Performance)**: High Frequency Compute (~$40/mo). Use hourly billing to save on weekends.

### 🚀 Setup Steps (Remote Desktop)
1. **Install Chrome**: Standard Google Chrome install.
2. **Setup Python**: Install Python 3.9+. **Check "Add to PATH"**.
3. **Download Code**: `git clone` or copy-paste the project folder.
4. **Environment**: Create a `.env` file with your keys:
   ```ini
   ALPACA_API_KEY=your_key
   ALPACA_SECRET_KEY=your_secret
   TRADEZERO_USERNAME=your_user
   TRADEZERO_PASSWORD=your_pass
   TRADEZERO_MFA_SECRET=your_mfa_secret
   TRADEZERO_HEADLESS=true
   ```
5. **Autostart**: Use **Windows Task Scheduler** to run `python main.py` at **09:25 AM ET** every weekday.

---

## 2. Logic Parity (Backtest vs. Live)
The following rules are now enforced in the live code to match the backtest's performance exactly:

- **Sentiment Window**: Rolling 24H (Prev 09:30 to Curr 09:30).
- **Sentiment Threshold**: **0.90** (Matched to the optimized 2021-2024 backtest universe).
- **Minimum Price**: **$5.00** (Symbols below $5 are skipped).
- **Selection Filter**: Only **Green Candles** (`Refinement Close > Refinement Open`) are considered.
- **Priority**: Ranked by **RVOL** (Relative Volume) at 09:35 AM.

### ✅ Verified Match (Jan 2026)
- **2026-01-29**: 100% Match (Watchlist: `INOD, VELO, CMPR, HAFC, ENVA`).
- **2026-01-30**: 100% Match (Watchlist: `VPG, INOD, DLX, GSIT`). `MSGY` ($0.84) was correctly ignored.

---

## 3. Safety Features (2026-02-02 Update)
Following a live session "Panic Loop" scenario, we implemented critical circuit breakers:

1. **Exit Lock (is_exiting)**: The bot will only attempt **one** Market Sell order per symbol in a repair scenario. If it fails, it will not spam the broker.
2. **Null-Safety**: The scraper now handles Selenium timeouts gracefully by returning empty lists instead of crashing.
3. **Session Persistence**: `triggered_symbols` are saved to `state/session_YYYY-MM-DD.json` so the bot can resume where it left off after a crash.

---

## 🛠️ Maintenance Commands
To check current broker status without running the bot:
```powershell
python diagnose_tz.py
```
To run the bot in safe "Dry Run" mode (Paper Trading):
```powershell
python main.py --dry-run
```
