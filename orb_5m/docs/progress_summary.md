# ORB Strategy — Progress Summary

**Generated:** November 17, 2025

---

## ✅ Completed Milestones (24/48 major items)

### Data & Infrastructure
- ✅ M1 — Data layer (Polygon.io integration, 1min/5min/daily bars)
- ✅ M2 — Indicators (ATR, opening range, RVOL)
- ✅ Polygon.io setup (API key, data download scripts)
- ✅ Data storage (Parquet format, organized by timeframe)
- ✅ Timestamp handling (Unix ms → ET datetime)
- ✅ Verified bar timing (both 1-min and 5-min start at 9:30 ET)
- ✅ Survivorship bias handling (delisted tickers accessible)

### Strategy Implementation
- ✅ ATR(14) calculation on daily bars
- ✅ Opening range high/low (first 5-min bar)
- ✅ Opening-range RVOL (14-day rolling average)
- ✅ Top-N selection by RVOL ranking
- ✅ Single-stock ORB strategy logic (entries, stops, exits)
- ✅ Portfolio engine (multi-stock, top-20 selection)
- ✅ Risk sizing (~1% per trade)
- ✅ Commission model ($0.0035/share)
- ✅ Checkpointing (resume long backtests)

### Backtest Results
- ✅ Multi-year portfolio backtests (2021–2025)
- ✅ Yearly results with stats (CAGR, MDD, profit factor, hit rate)
- ✅ Kelly-style fractions (kelly/safe/danger percentages)
- ✅ Combined summary across all years
- ✅ Wealth-from-$1000 calculations
- ✅ Trade logs (CSV with all entries/exits)
- ✅ Daily P&L tracking

---

## 🔄 In Progress (0 items actively being worked on)

Currently between phases — core backtest engine complete, dashboard design ready for implementation.

---

## 📋 Remaining Work (24/48 major items)

### Strategy Refinements
- ⬜ Direction gating validation (long-only on green, short-only on red, skip doji)
- ⬜ Leverage cap enforcement (4x max across portfolio)
- ⬜ Full test suite (synthetic data validation)
- ⬜ Edge case handling (halts, missing bars, small ATR)

### Reporting & Analytics
- ⬜ Equity curve plots (with drawdown shading)
- ⬜ Sharpe ratio calculation
- ⬜ Alpha/Beta vs SPY benchmark
- ⬜ Symbol leaderboard (best/worst performers)
- ⬜ RVOL bucket analysis (<1, 1–2, 2–5, >5)
- ⬜ Trade distribution histograms

### Dashboard (NEW — design complete, implementation pending)
- ⬜ Daily overview page (top-N ranked, trade log, metrics)
- ⬜ TradingView chart integration (with trade annotations)
- ⬜ Multi-day analysis page (equity curve, heatmap, buckets)
- ⬜ Symbol deep-dive page
- ⬜ Backend API (FastAPI endpoints for data)
- ⬜ Frontend (React + TradingView Lightweight Charts OR Streamlit)

### Validation & Polish
- ⬜ Compare vs published stats (sanity check)
- ⬜ Documentation (setup guide, usage examples)
- ⬜ End-to-end test (fresh checkout → results)

### Optional Extensions
- ⬜ 15/30/60-min ORB variants
- ⬜ Slippage model
- ⬜ Live/paper trading adapter (broker API)
- ⬜ Parallel processing (multiprocessing for speed)

---

## 📊 Current Status by Component

| Component | Status | Notes |
|-----------|--------|-------|
| Data Layer | ✅ Complete | Polygon.io, 1min/5min/daily bars stored locally |
| Indicators | ✅ Complete | ATR, OR high/low, RVOL working |
| Strategy Logic | ✅ Complete | Single-stock ORB with entries/stops/exits |
| Portfolio Engine | ✅ Complete | Top-20 selection, risk sizing, checkpointing |
| Backtest Runner | ✅ Complete | Multi-year runs (2021–2025) successful |
| Results Output | ✅ Complete | CSVs with trades, daily P&L, yearly stats |
| Wealth Calculations | ✅ Fixed | Corrected double-counting bug; wealth-from-1000 accurate |
| Performance Metrics | 🔄 Partial | CAGR, MDD, profit factor ✅; Sharpe, alpha/beta pending |
| Visualization | ⬜ Not Started | Dashboard design ready; implementation needed |
| Testing | 🔄 Partial | Manual validation done; automated tests pending |
| Documentation | 🔄 Partial | Plan & design docs exist; user guide pending |

---

## 🎯 Next Recommended Actions

### Immediate (High Value, Low Effort)
1. **Equity curve plot** — Generate PNG/HTML of cumulative P&L over time
   - Libraries: matplotlib or plotly
   - Add drawdown shading
   - Estimated time: 30 min

2. **Sharpe ratio** — Quick calculation from daily returns
   - Already have daily P&L data
   - Formula: `mean(daily_returns) / std(daily_returns) * sqrt(252)`
   - Estimated time: 15 min

3. **Symbol leaderboard** — Top 10 best/worst stocks by cumulative R
   - Group trades by symbol, sum R-multiples
   - Output to CSV or print to console
   - Estimated time: 20 min

### Short-Term (Dashboard MVP)
4. **Streamlit daily overview** — Quick interactive dashboard
   - Read existing CSVs
   - Show trades table, metrics cards
   - Use plotly for basic charts
   - Estimated time: 2–3 hours

5. **TradingView chart modal** — Add price charts with trade markers
   - Integrate TradingView Lightweight Charts
   - Annotate entry/exit/stop levels
   - Estimated time: 3–4 hours

### Medium-Term (Full Dashboard)
6. **FastAPI backend** — RESTful API for dashboard data
   - Endpoints: `/daily-overview`, `/chart-data`, `/multi-day-stats`
   - Estimated time: 1 day

7. **React frontend** — Production-ready UI
   - Replace Streamlit with React + Tailwind
   - TradingView integration for all charts
   - Estimated time: 2–3 days

### Long-Term (Validation & Extensions)
8. **Compare vs published stats** — Sanity-check your results
   - If paper reports ~60% CAGR, are you within 10–15%?
   - Document any differences and hypothesize causes
   - Estimated time: 2–3 hours

9. **15/30/60-min variants** — Test other timeframes
   - Reuse existing code, change opening range window
   - Compare performance across timeframes
   - Estimated time: 1 day

---

## 🐛 Known Issues & Fixes

### Fixed
- ✅ **Wealth calculation bug** (Nov 17, 2025)
  - Issue: `wealth_1000_base` was using wrong starting equity (double-counted first day P&L)
  - Fix: Changed `summarize_portfolio.py` line 212 to always start from 100k
  - Result: Correct wealth-from-1000 now showing (26,181.96 vs previous incorrect 102,373)

### Active
- None currently identified

### Pending Investigation
- None

---

## 📈 Key Metrics (2021–2025 Combined)

From `results_combined_top20/summary.txt`:

| Metric | Value |
|--------|-------|
| Period | 2021-01-25 to 2025-11-03 (1743 days) |
| Total Return | +2,582% (25.82×) |
| CAGR | 98.1% |
| Max Drawdown | -8.76% |
| Total Trades | 4,876 |
| Win Rate | 16.8% |
| Profit Factor | 1.77 |
| Wealth from $1,000 (base) | $26,181.96 |
| Wealth from $1,000 (safe) | $153,673.80 |
| Wealth from $1,000 (Kelly) | $307,347.60 |
| Wealth from $1,000 (danger) | $614,695.20 |

**Kelly Fractions (from 2025):**
- Kelly: 11.74%
- Safe (0.5× Kelly): 5.87%
- Danger (2× Kelly): 23.48%

---

## 📁 File Structure (Current State)

```
opening-range-breakout/
├── config/
│   ├── us_stocks_active.txt         # Universe (5k+ symbols)
│   └── .env                          # API keys
├── data/
│   ├── processed/
│   │   ├── 1min/                    # 1-min bars (parquet)
│   │   ├── 5min/                    # 5-min bars (parquet)
│   │   └── daily/                   # Daily bars for ATR
├── docs/
│   ├── explainer.md                 # Strategy overview
│   ├── plan.md                      # Master plan (this checklist)
│   └── dashboard_design.md          # Dashboard spec (NEW)
├── results_active_2021_top20/       # Yearly backtest results
├── results_active_2022_top20/
├── results_active_2023_top20/
├── results_active_2024_top20/
├── results_active_2025_top20/
├── results_combined_top20/          # Multi-year combined
│   ├── all_daily_pnl.csv
│   ├── all_trades.csv
│   ├── all_yearly_stats.csv
│   └── summary.txt
├── src/
│   ├── strategy_orb.py              # Single-stock ORB logic
│   ├── portfolio_orb.py             # Portfolio runner with checkpointing
│   ├── summarize_portfolio.py       # Combine yearly results
│   └── plot_equity_and_wealth.py    # Visualization helpers
├── fetch_polygon_data.py            # Data download script
├── requirements.txt
└── README.md
```

---

## 💡 Lessons Learned

1. **Checkpointing is essential** — Multi-year, multi-stock backtests take hours; checkpointing allows resume
2. **Double-check equity calculations** — Found and fixed a double-counting bug in combined equity recomputation
3. **Kelly fractions vary by year** — 2022 had 33% Kelly vs 2025 at 12%, showing strategy performance changes
4. **Low win rate (16.8%) but profitable** — Confirms "big wins, many small losses" pattern is working
5. **Data quality matters** — Polygon.io's consistent timestamp format (9:30 ET start) simplifies OR calculation

---

## 🎓 References

- **Strategy Paper:** (Original ORB with RVOL filtering research)
- **Data Source:** Polygon.io (Stocks Advanced plan)
- **Dashboard Inspiration:** TradingView, Interactive Brokers TWS
- **Tech Stack:** Python (pandas, numpy) + FastAPI + React + TradingView Lightweight Charts

---

## ✉️ Quick Links

- [Dashboard Design](./docs/dashboard_design.md) — Full UI/UX spec for visual analytics
- [Master Plan](./plan.md) — Original implementation checklist
- [Combined Summary](../results_combined_top20/summary.txt) — Latest backtest metrics
