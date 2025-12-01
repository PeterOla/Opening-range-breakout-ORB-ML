# Plan: ORB Strategy Historical Backtest & Analytics System

**TL;DR**: Build a comprehensive backtesting pipeline that processes 5+ years of parquet data (5000+ stocks), stores simulated trades in the database, and creates an analytics dashboard showing weekly/monthly/yearly P&L, drawdowns, win/loss streaks, and filtering capabilities.

---

## Steps

### 1. Create daily metrics pre-computation script
- Read all daily parquet files from `data/processed/daily/`
- Compute ATR (14-day), avg volume (14-day), prev close for each symbol × date
- Store in new `daily_metrics_historical` table
- ~5 years × 250 days × 5000 symbols = 6.25M rows

### 2. Build bulk backtest orchestrator
- New script `prod/backend/services/bulk_backtest.py`
- For each trading day (2021→2025):
  - Load daily metrics for that date
  - Filter universe (price ≥ $5, ATR ≥ $0.50, avg_vol ≥ 1M)
  - Load 5-min parquets for qualified symbols only
  - Extract OR bar (9:30-9:35), compute RVOL
  - Rank top 20, determine direction, simulate trades
  - Save to `simulated_trades` table
- Process ~1,250 trading days total

### 3. Extend database schema for analytics
- Add `backtest_runs` table (run_id, start_date, end_date, params, created_at)
- Add `daily_performance` table (date, total_pnl, trades_taken, winners, losers, best_trade, worst_trade)
- Index `simulated_trades` by date for fast aggregation

### 4. Create analytics API endpoints
- `GET /analytics/performance?period=weekly|monthly|yearly&start=&end=`
- `GET /analytics/drawdown` - max drawdown, current drawdown, recovery days
- `GET /analytics/streaks` - winning days streak, losing days streak
- `GET /analytics/summary` - all-time stats, best/worst periods

### 5. Build analytics dashboard page
- New page at `/analytics` with:
  - Period selector (weekly/monthly/yearly/custom range)
  - Equity curve chart
  - Monthly returns heatmap
  - Performance table with P&L per period
  - Drawdown chart
  - Win/loss streak indicators
  - Key stats cards (total P&L, win rate, avg trade, Sharpe, etc.)

---

## Further Considerations

1. **Processing time**: ~1,250 days × 100+ symbols/day = hours of processing. Parallelise by date chunks? Use multiprocessing?

2. **Survivorship bias**: Use only symbols that existed at each historical date, or backtest current universe only? *Recommend*: Current universe for simplicity, note limitation.

3. **Storage**: Should simulated trades include a `backtest_run_id` to allow multiple strategy variants (e.g., top 10 vs top 20, different stop levels)?

---

## Data Sources

| Source | Location | Format |
|--------|----------|--------|
| 5-min bars | `data/processed/5min/*.parquet` | ~5000 files, 2021+ |
| Daily bars | `data/processed/daily/*.parquet` | ~5000 files, 2021+ |

## Database Tables (Existing)

| Table | Purpose |
|-------|---------|
| `simulated_trades` | Store backtest trade results |
| `opening_ranges` | OR data per symbol/day |
| `daily_bars` | Rolling 30-day window (Polygon) |

## Database Tables (New)

| Table | Purpose |
|-------|---------|
| `daily_metrics_historical` | Pre-computed ATR, avg_vol for all dates |
| `backtest_runs` | Track different backtest configurations |
| `daily_performance` | Aggregated daily P&L for fast queries |

---

## Trade Simulation Logic (Reference)

```python
# Position sizing
CAPITAL = 1000.0
LEVERAGE = 2.0
position_value = CAPITAL * LEVERAGE  # $2000

# Entry
entry_price = or_high if direction == 1 else or_low  # Long/Short

# Stop
stop_price = or_low if direction == 1 else or_high

# Exit triggers
- STOP_LOSS: price hits stop_price
- EOD: close at last bar of day

# P&L
pnl_pct = (exit - entry) / entry * 100  # for long
base_dollar_pnl = (CAPITAL / entry) * price_move  # 1x
dollar_pnl = base_dollar_pnl * LEVERAGE  # 2x
```

---

## Analytics Metrics to Track

### Performance
- Total P&L ($, %)
- Win rate (%)
- Average winner / loser
- Profit factor
- Sharpe ratio
- Sortino ratio

### Risk
- Max drawdown ($, %)
- Average drawdown duration
- Recovery factor
- Ulcer index

### Streaks
- Longest winning days streak
- Longest losing days streak
- Current streak
- Best week/month/year
- Worst week/month/year

### Filtering
- By date range
- By period (weekly/monthly/yearly)
- By direction (long/short)
- By symbol
- By win/loss
