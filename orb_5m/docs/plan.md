# Plan to Build the ORB Strategy (with Checklists + Scaffolding)

This plan shows how to build a backtester (and later, a live trader) for the 5‑minute ORB strategy with Stocks in Play using Relative Volume. It’s broken into small, checkboxable steps.

## Goals
- [x] Backtest the 5‑minute ORB across US stocks (2021–2025 completed with 5k+ symbols).
- [x] Include filters: price ≥ $5, 14D avg volume ≥ 1M shares, ATR ≥ $0.50.
- [x] Use opening-range (first 5 min) Relative Volume ≥ 1.0; trade top 20 RVOL.
- [x] Direction gating: long only on green first candle, short only on red; skip doji.
- [x] Stop loss = 10% of 14D ATR; EOD exit; commission $0.0035/share.
- [x] Risk ~1% per trade, max leverage 4x across portfolio.
- [x] Produce metrics: equity curve, IRR, Sharpe, MDD, worst day, alpha/beta vs S&P.
- [x] Dashboard with dynamic equity scaling and comprehensive filters.
- [x] Parallel processing implementation (5-year simultaneous runs).
- [ ] Trade auditing system with TradingView chart integration.
 - [ ] Reproduce published key stats (Base vs RVOL‑filtered strategy) to sanity‑check implementation.

## Assumptions (so we can move fast)
- We'll use Python for the backtester (pandas, numpy). Easy to extend.
- **Data granularity: 1-minute and 5-minute bars available**.
  - **1-minute bars**: Match the paper's precision for stop-loss and entry detection.
  - **5-minute bars**: Faster processing; opening range (9:30–9:35) fits perfectly.
  - Stop-loss detection: 1-min bars give exact timing; 5-min bars are approximate (assume worst-case fill within bar).
  - We'll primarily use 1-minute data to match the paper's methodology, with 5-minute as a faster alternative for testing.
- Minute data is available via Polygon.io (see Data Options).
- We'll start with 5‑minute ORB, then add 15/30/60 if needed.
- Survivorship bias: include delisted symbols (paper did); don't silently drop missing final dates.
- Corporate actions: intraday bars unadjusted (paper's approach); daily ATR can be split-adjusted if using adjusted daily data—note the choice.

## High-level milestones
- [x] M1 — Data layer working (minute bars + calendar + splits handling decision).
- [x] M2 — Indicators: ATR(14), opening range high/low, opening-range RVOL.
- [x] M3 — Strategy logic (entries, stops, exits) for single stock.
- [x] M4 — Portfolio engine (risk sizing, leverage cap, commission, top‑20 selection).
- [x] M5 — Backtest runner + performance metrics + plots.
- [x] M6 — Reports: daily logs, trade list, equity curve, summary table.
- [x] M7 — Dashboard with equity scaler, filters, Alpha/Beta metrics.
- [x] M8 — Parallel processing with multiprocessing (5-year simultaneous runs).
- [x] M9 — Fixed combined equity curve bug (recalculate from trades).
- [ ] M10 — Trade auditing system with TradingView integration.

---

## Project scaffolding (folders + key files)
Create this structure (you don’t need to fill every file on day 1):

```
opening-range-breakout/
  config/
    config.yaml                 # Parameters: universes, fees, risk, leverage, timeframes
  data/
    raw/                        # Provider raw files (minute bars)
    processed/                  # Cleaned, standardized CSV/Parquet
  docs/
    explainer.md                # Plain English summary (this repo’s ‘explainer.md’)
    plan.md                     # This plan
  notebooks/
    01-data-audit.ipynb         # Optional: quick EDA on data quality
    02-sanity-tests.ipynb       # Optional: quick indicator sanity checks
  scripts/
    fetch_data.ps1              # Windows-friendly fetch stub (optional)
    run_backtest.ps1            # Run backtests with chosen config
  src/
    __init__.py
    config_loader.py            # Read/validate config.yaml
    utils/
      calendars.py              # Trading calendar utilities
      math.py                   # ATR, rolling stats, slippage helpers
      timeframes.py             # Resampling helpers (1m→5m)
    data/
      providers.py              # Data provider adapters (e.g., CSV, API)
      loader.py                 # Load + clean + standardize minute bars
      universe.py               # Universe filters (price, volume, ATR)
    indicators/
      atr.py                    # ATR(14) on daily
      opening_range.py          # First N‑minute high/low + open/close
      relative_volume.py        # OR‑RVOL calculation
    strategy/
      orb.py                    # Entry/exit rules for N‑minute ORB
    portfolio/
      sizing.py                 # 1% risk sizing, leverage cap
      commission.py             # $0.0035/share model
      engine.py                 # Multistock execution sim
    backtest/
      runner.py                 # Glue: load data → run strategy → stats
      stats.py                  # Sharpe, MDD, alpha/beta vs S&P
      reporting.py              # Plots + CSV/HTML summary
  tests/
    test_atr.py
    test_opening_range.py
    test_relative_volume.py
    test_strategy_orb.py
    test_portfolio_engine.py
  .env                          # Optional: API keys
  requirements.txt              # pandas, numpy, pandas_market_calendars, etc.
  README.md                     # How to install/run
```

## Config (example)
Put this in `config/config.yaml`:

```yaml
# Universe
price_min: 5.0
avg_volume_14d_min: 1000000
atr14_min: 0.50

# Opening range
timeframe_minutes: 5
rvol_min: 1.0           # 100%
max_rvol_names: 20      # top 20 by opening-range RVOL

# Risk/fees
risk_per_trade_pct: 1.0
max_leverage: 4.0
commission_per_share: 0.0035

# Backtest
start_date: 2016-01-01
end_date: 2023-12-31
benchmark: SPY         # proxy for S&P 500 daily returns

# Data
provider: local_csv     # or polygon/alpaca/interactive_brokers/etc.
minute_bar_path: data/processed/minute/
daily_bar_path: data/processed/daily/
symbols_list: config/symbols_us.txt

# Output
output_dir: outputs/5m_orb_relvol/
```

---

## Data options (Polygon.io chosen)
- **Provider**: Polygon.io
  - Plan needed: **Stocks Advanced** ($99/mo) or **Stocks Unlimited** ($199/mo) for historical aggregates
  - Free tier: only last 2 years, rate-limited (not sufficient for 7k stocks × 8 years)
  - Survivorship bias: Can request delisted tickers via API
  - API library: `polygon-api-client` (Python)

- Data to fetch:
  - [x] **1-minute bars** (aggregates endpoint): `/v2/aggs/ticker/{ticker}/range/1/minute/{from}/{to}`
  - [x] **5-minute bars** (aggregates endpoint): `/v2/aggs/ticker/{ticker}/range/5/minute/{from}/{to}`
  - [x] **Daily bars** for ATR: `/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}`
  - [x] Store locally in `data/processed/1min/<SYMBOL>.parquet`, `data/processed/5min/<SYMBOL>.parquet` and `data/processed/daily/<SYMBOL>.parquet`
  - [x] Polygon's timestamps are in Unix milliseconds ET; convert to datetime

- Important Polygon.io notes:
  - [x] Both 1-min and 5-min bars start at 9:30:00 ET (verified compatible with ORB)
  - [x] 1-min bars: ~390 bars per day per stock (6.5 hours × 60 min)
  - [x] 5-min bars: ~78 bars per day per stock (6.5 hours × 12 bars/hour)
  - [ ] Rate limits: 5 calls/min (free), unlimited (paid plans)
  - [x] Splits/dividends: Polygon returns unadjusted by default for aggregates (matches paper)
  - [x] Delisted tickers: Use `/v3/reference/tickers` with `active=false` to get full universe

- Calendars
  - [ ] Use `pandas_market_calendars` for NYSE hours/holidays.

---

## Core computations (what to build)
### 1) Indicators
- [x] ATR(14) daily
  - Input: daily high/low/close.
  - Output: daily ATR value; use yesterday's ATR at the open.
- [x] Opening range (N = 5 minutes)
  - Input: **First 5-min bar** (9:30–9:35 ET) from your 5-min data.
  - Output: first candle open (9:30 price), close (9:35 price), high, low.
- [x] Opening-range Relative Volume (RVOL)
  - Input: volume in first 5-min bar today vs average of first 5-min bar volumes over last 14 days.
  - Output: RVOL value; keep ≥ 1.0; rank to get top 20.
  - Formula (plain): RVOL_today = ORVol_today / (average_{past14} ORVol_day_i)
  - Use only completed past days (skip days with missing opening range volume).

### 2) Entry and direction gating
- [x] If first candle close > open → long only (entry at OR high via stop order).
- [x] If first candle close < open → short only (entry at OR low via stop order).
- [x] If open == close (doji) → skip.

### 3) Stops and exits
- [x] Stop loss = 10% of ATR(14) (from entry price).
- [x] Exit at end of day if stop not hit.
- [x] **With 1-min bars**: Check each bar for stop breach; precise timing like the paper.
- [x] **With 5-min bars**: Check if any 5-min bar's high/low breaches stop. If yes, assume stopped at the stop price (or worst price in that bar for conservative estimate).

### 4) Position sizing and portfolio rules
- [x] Risk ~1% of equity per trade using the stop distance to compute shares.
- [x] Enforce 4x max leverage across open positions.
- [x] Commission = $0.0035/share on entries and exits.

---

## Single‑stock pseudocode (mental model)
```
for each day D:
  grab first 5-min bar (9:30–9:35) OR first 5 x 1-min bars (9:30–9:35)
  compute direction = sign(close - open) of the opening range
  compute ATR14 (from prior daily data)
  if RVOL < 1.0: skip
  if direction > 0: entry = OR_high (buy stop)
  if direction < 0: entry = OR_low  (sell stop)
  stop_distance = 0.10 * ATR14
  stop_price = entry ± stop_distance (± depends on long/short)
  size shares for ~1% risk
  
  # Simulate intraday with 1-min or 5-min bars (9:35–16:00):
  for each subsequent bar:
    if position not yet open and bar crosses entry level: open position at entry
    if position open and bar breaches stop: close at stop price (or worst price in bar)
    if end of day (16:00) and position open: close at close price
```

## Portfolio flow (top 20 selection)
- [x] For all candidates that pass universe filters, compute opening-range RVOL.
- [x] Sort by RVOL desc; keep top 20.
- [x] Simultaneously simulate entries in allowed direction per symbol (respect leverage cap).
 - [x] If fewer than 20 pass RVOL ≥ 1.0, trade the available set (document counts).

---

## Edge cases to handle
- [x] Halts or missing bars in opening range (skip or mark uncertain).
- [x] Doji first candle → no trades.
- [x] ATR very small → minimum stop tick (avoid zero/near-zero stops).
- [ ] Price gaps: entry stop may fill immediately at a worse price (slippage model optional).
- [x] Delisted symbols (OK in backtest; ensure data is present pre‑delist).
- [x] Corporate actions (splits/dividends): intraday unadjusted vs daily adjusted—log chosen path.
- [ ] Trading halts after entry → stop may not execute; decide: mark trade with special flag.
- [x] Partial fills (optional realism): assume full fill for v1; future: volume-based limit.
- [x] **Data granularity choice**: 1-min for paper-level precision vs 5-min for faster backtests.
  - 1-min: ~500k bars per stock for 5 years; more accurate stop detection
  - 5-min: ~100k bars per stock for 5 years; 5x faster but approximate stops

## Testing checklist (minimal but effective)
- Indicators
  - [ ] ATR(14) matches a known reference.
  - [ ] Opening range high/low computed correctly on synthetic data.
  - [ ] RVOL = 1.0 when today’s OR volume equals 14‑day OR average.
- Strategy
  - [ ] Long‑only when first candle is green; short‑only when red; skip doji.
  - [ ] Stop loss hits at exact calculated level on synthetic path.
  - [ ] EOD exit always closes positions.
  - [ ] RVOL ranking selects correct top 20 given synthetic volumes.
  - [ ] Fallback when < 20 candidates (no crash, trades subset).
- Portfolio
  - [ ] Sizing yields ~1% risk (shares computed correctly for long/short).
  - [ ] Leverage never exceeds 4x.
  - [ ] Commission applied on both entry and exit.
  - [ ] Alpha/Beta regression stable (repeatability across seeds).

---

## Outputs you should produce
- [x] CSV of trades (symbol, date, side, entry, stop, exit, P&L in $ and R).
- [x] Daily equity curve CSV and plot.
- [ ] Summary stats table: Total Return, IRR, Vol, Sharpe, Hit Ratio, MDD, Worst Day.
- [ ] Alpha/Beta vs benchmark (regress daily returns on benchmark returns).
 - [ ] Separate summary for Base vs RVOL strategy (side-by-side CSV/Markdown).
 - [ ] Symbol leaderboard (top/worst cumulative R).
 - [ ] RVOL bucket analysis (e.g., <1.0, 1–2, 2–5, >5) average R per trade.

---

## Windows/PowerShell tips
- Use one command per line (PowerShell is fine with that). Example runners:

```powershell
# Optional: create venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install deps
pip install -r requirements.txt

# Run backtest
python -m src.backtest.runner --config .\config\config.yaml
```

> If you don’t have code yet, keep these commands as placeholders.

---

## Requirements (starter list for requirements.txt)
```
pandas>=2.0.0
numpy>=1.24.0
pandas_market_calendars>=4.3.0
scipy>=1.11.0              # for regression alpha/beta
matplotlib>=3.7.0          # or plotly for charts
pyyaml>=6.0
polygon-api-client>=1.12.0 # Polygon.io official client
python-dotenv>=1.0.0       # for .env API key management
```

---

## Stretch goals / nice-to-haves
- [ ] Add 15/30/60‑minute ORB variants and a COMBO portfolio.
- [ ] Slippage model (e.g., 1–3 ticks worse than stop price on gaps).
- [ ] Live/paper trading via broker API (Alpaca/IBKR) with the same risk rules.
- [x] Dashboard (design complete in docs/dashboard_design.md; implementation pending).
- [ ] Symbol‑level analytics: best/worst tickers, heatmaps, win rate by RVOL bucket.
 - [ ] Intraday equity curve per trade (visualize how R evolves through day).
 - [ ] Adaptive stop (e.g., trail after 4R) — test vs base.
 - [x] Parallel processing of symbols (multiprocessing / Dask) for speed (checkpointing implemented).

## Trade Auditing System
- [ ] **TradingView chart integration** for manual trade verification
  - [ ] Click trade in dashboard → opens TradingView chart
  - [ ] Auto-populate: symbol, date, entry/exit times, price levels
  - [ ] Mark opening range high/low, stop loss, entry/exit on chart
  - [ ] Show 1-min or 5-min timeframe matching backtest granularity
- [ ] **Trade detail view** in dashboard
  - [ ] Selected trade highlights: entry/exit execution, stop distance
  - [ ] Show intraday price action: when entry triggered, stop status, final exit
  - [ ] Display surrounding context: RVOL rank, direction gate, ATR value
- [ ] **Audit workflow**
  - [ ] Filter trades by: symbol, date range, P&L range, RVOL bucket
  - [ ] Flag suspicious trades (e.g., stops hit at extreme bars)
  - [ ] Export selected trades for detailed review
  - [ ] Track audit status: reviewed/flagged/approved per trade

---

## "Do this today" tiny sprint (Polygon.io setup)
- [x] Sign up for Polygon.io (Advanced or Unlimited plan for historical data)
- [x] Get your API key from dashboard
- [x] Create `.env` file with `POLYGON_API_KEY=your_key_here`
- [x] Create the scaffolding folders
- [x] Install Python dependencies: `pip install -r requirements.txt`
- [x] Write a simple fetch script to download 1-min, 5-min, and daily data for 1–2 test symbols (e.g., NVDA, TSLA) for 2022–2023
- [x] Verify both 1-min and 5-min bars start at 9:30:00 ET and daily data is present
- [x] Implement ATR(14) and opening range functions on your test data
- [x] Hard‑code a single symbol test for 2–3 days; verify entries/stops/exit with 1-min precision
- [x] Add RVOL calculation and top‑20 selection (for now, with as many symbols as you have)
- [x] Generate a minimal trade CSV and equity curve

## "Done means" for v1
- [x] Backtest runs end‑to‑end on your sample universe.
- [x] Outputs generated (trades, equity, summary stats, alpha/beta).
- [x] Key edge cases tested (doji, ATR min, leverage cap, commissions).
- [ ] Code is simple, commented, and reproducible from `config.yaml`.
- [ ] Published Base vs RVOL stats approximately reproduced (within ±10–15% for return, Sharpe, alpha directionally correct).
- [x] **Both 1-min and 5-min backtests available**: 1-min matches paper's methodology; 5-min offers faster alternative for testing.
- [x] Documentation notes precision trade-offs between 1-min (exact) and 5-min (approximate) stop detection.
