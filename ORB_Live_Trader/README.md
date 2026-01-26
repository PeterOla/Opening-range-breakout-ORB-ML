# ORB Live Trader

Self-contained sentiment-driven Opening Range Breakout live trading system for TradeZero.

## Overview

Exact replication of backtest strategy:
- **Sentiment threshold**: 0.90 (highly positive FinBERT)
- **Attribution**: Rolling 24H (market hours news → next business day)
- **Filters**: ATR >= 0.5, Volume >= 100K, LONG only
- **Position sizing**: Equal dollar allocation (equity/5) * 6x leverage
- **Stop**: 5% of ATR-14
- **Exit**: Stop hit or 16:00 ET close

## Folder Structure

```
ORB_Live_Trader/
├── config/
│   └── .env                 # Environment variables (API keys, credentials)
├── data/
│   ├── reference/          # Static universe files
│   │   ├── universe_micro_full.parquet
│   │   └── missing_shares_ignore.json
│   ├── news/               # Raw 24h news (30-day retention)
│   ├── sentiment/          # Scored sentiment candidates (30-day)
│   ├── bars/
│   │   ├── daily/          # Daily bars with ATR/volume (30-day)
│   │   └── 5min/           # Intraday bars with OR metrics (30-day)
│   └── universes/          # Daily Top 5 candidates (30-day)
├── logs/
│   ├── trades/             # Permanent trade audit trail (parquet)
│   └── runs/               # Script execution logs (30-day retention)
├── scripts/
│   ├── init_state_db.py            # Create DuckDB schema
│   ├── sync_daily_data.py          # Nightly daily bars fetch
│   ├── fetch_and_score_news.py     # News → FinBERT sentiment
│   ├── fetch_intraday_bars.py      # 5-min bars with OR calc
│   ├── generate_daily_universe.py  # Top 5 selection
│   └── execute_live_orb.py         # TradeZero execution engine
└── state/
    └── orb_state.duckdb    # Live trading state (universe, orders, positions, trades)
```

## Setup

### 1. Environment Variables

Create `config/.env`:

```bash
# Alpaca API (for news + market data)
ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret

# TradeZero credentials (order execution)
TRADEZERO_USERNAME=your_tz_username
TRADEZERO_PASSWORD=your_tz_password
TRADEZERO_MFA_SECRET=your_totp_secret_base32
TRADEZERO_HEADLESS=false
```

**Getting TRADEZERO_MFA_SECRET:**
- When setting up 2FA in TradeZero, save the base32 secret (usually shown as QR code alternative)
- Format: `ABCD1234EFGH5678` (letters and numbers only, no spaces)
- Used by `pyotp` to generate TOTP codes automatically

### 2. Initialize Database

```bash
cd ORB_Live_Trader
python scripts/init_state_db.py
```

Creates DuckDB with tables:
- `daily_universe` (Top 5 candidates per day)
- `active_orders` (pending/filled orders)
- `filled_positions` (open positions)
- `closed_trades` (permanent audit trail)
- `equity_snapshots` (daily equity tracking)

## Daily Execution Schedule

### 18:00 ET (Previous Night)
**Sync Daily Data**
```bash
python scripts/sync_daily_data.py
```
- Fetches daily bars for all micro-caps (3 retries, 5min backoff)
- Calculates ATR-14 and avg_volume_14
- Saves to `data/bars/daily/{YYYY-MM-DD}.parquet`
- Deletes files older than 30 days

**Logs**:
- Fetched X bars for Y symbols
- ATR/volume calculations complete
- Deleted Z old files

### 06:00 ET (Trading Day)
**Fetch News & Score Sentiment**
```bash
python scripts/fetch_and_score_news.py
```
- Fetches 24h Alpaca news for micro-caps (3 retries, 5min backoff)
- Uses time-based pagination to avoid missing historical items
- Scores headlines with FinBERT (batch 32, GPU if available)
- Applies rolling 24H attribution
- Filters >0.90 positive sentiment
- Saves to `data/sentiment/daily_{YYYY-MM-DD}.parquet`

**Logs**:
- Fetched X news items for Y symbols
- Scoring Z unique headlines
- After threshold: X candidates (Y%)
- After aggregation: X candidates for Y days

### 09:25 ET
**Fetch 5-Min Bars**
```bash
python scripts/fetch_intraday_bars.py
```
- Fetches 5-min bars (04:00-16:00 ET) for sentiment candidates
- Retries 3x per symbol, 2min backoff
- Skips failed symbols, continues with available data
- Calculates OR metrics from the **first 09:30–09:35 ET bar** (or_open, or_high, or_low, or_close, or_volume, rvol)
- Saves to `data/bars/5min/{YYYY-MM-DD}/{symbol}.parquet`

**Logs**:
- Fetching symbol X (Y/Z)
- SYMBOL: Saved N bars with OR metrics
- Fetch complete: X successful, Y failed

### 09:28 ET
**Generate Daily Universe**
```bash
python scripts/generate_daily_universe.py
```
- Joins sentiment candidates with daily bars (ATR/volume)
- Enriches with 5-min OR data
- Applies filters: ATR >= 0.5, Volume >= 100K, Direction == 1 (LONG)
- Ranks by RVOL descending
- Selects Top 5
- Calculates entry/stop prices
- Inserts into DuckDB `daily_universe`
- Saves to `data/universes/candidates_{YYYY-MM-DD}.parquet`

**Logs**:
- Loaded X sentiment candidates
- Enriched X/Y candidates with bars
- After ATR filter: X/Y
- After volume filter: X/Y
- After direction filter: X/Y
- Selected Top 5 by RVOL
- UNIVERSE SUMMARY (symbol, RVOL, entry, stop, sentiment)

### 09:30-16:00 ET
**Execute Live Trading**
```bash
python scripts/execute_live_orb.py
```

**Pipeline**:
1. Connect to TradeZero, validate session
2. Load current equity from `equity_snapshots`
3. Load Top 5 universe from DuckDB
4. Monitor for breakouts above `or_high` (5s polling)
5. Place LIMIT BUY orders at `or_high + $0.01`
6. Poll for fills (0.5s polling TradeZero portfolio)
7. Place protective stops (monitor for stop hits, no bracket orders)
8. Monitor positions until 16:00 ET (1s polling)
9. Flatten all positions at close (MARKET, R78 fallback to LIMIT at bid)
10. Reconcile trades and log to `closed_trades`

**Logs**:
- Starting live execution for YYYY-MM-DD
- TradeZero session established
- Current equity: $X,XXX.XX
- Loaded X candidates from universe
- SYMBOL: BREAKOUT detected! $XX.XX > $XX.XX
- SYMBOL: Placing LIMIT BUY X shares @ $XX.XX
- SYMBOL: Order placed, ID: XXXXX
- SYMBOL: FILLED @ $XX.XX
- SYMBOL: Stop monitoring activated @ $XX.XX
- SYMBOL: STOP HIT @ $XX.XX (stop: $XX.XX)
- SYMBOL: MARKET SELL order placed
- SYMBOL: Flattening X shares via MARKET
- Trade reconciliation complete

## Logging Format

All scripts use consistent logging:

```
[YYYY-MM-DD HH:MM:SS.fff] [LEVEL] [MODULE] message
```

Levels: `INFO`, `WARNING`, `ERROR`

Modules: `INIT_DB`, `SYNC_DAILY`, `FETCH_NEWS`, `FETCH_5MIN`, `GEN_UNIVERSE`, `EXECUTE`

## Error Handling

### News Fetch Failure
- Retries 3x with exponential backoff (5min, 10min, 20min)
- **If all retries fail**: ABORT entire day (no trades)

### OHLC Data Fetch Failure
- Retries 3x with exponential backoff (5min daily, 2min intraday)
- **Daily bars fail**: ABORT entire day
- **5-min bars fail per symbol**: Skip that symbol, continue with others

### TradeZero R78 Error (MARKET orders rejected)
- Fallback to LIMIT order at bid (SELL) or ask (BUY)
- Log warning and proceed

## Data Retention

- **News/Sentiment/Bars**: 30 days rolling window (auto-cleanup)
- **Universes**: 30 days rolling window
- **Closed Trades**: Permanent audit trail (never deleted)
- **Equity Snapshots**: Permanent (never deleted)

## State Persistence (DuckDB)

All execution state stored in `state/orb_state.duckdb`:

**Tables**:
1. `daily_universe` - Top 5 candidates with entry/stop prices
2. `active_orders` - Order lifecycle (SUBMITTED → FILLED)
3. `filled_positions` - Open positions being monitored
4. `closed_trades` - Permanent trade audit trail
5. `equity_snapshots` - Daily equity tracking

**Query Examples**:

```sql
-- View today's universe
SELECT * FROM daily_universe WHERE date = CURRENT_DATE;

-- Check active orders
SELECT * FROM active_orders WHERE status = 'SUBMITTED';

-- View open positions
SELECT * FROM filled_positions;

-- Trade history
SELECT * FROM closed_trades ORDER BY entry_time DESC LIMIT 10;

-- Daily P&L
SELECT snapshot_date, daily_pnl, winners_today, losers_today 
FROM equity_snapshots 
ORDER BY snapshot_date DESC;
```

## Manual Execution

Run individual scripts for testing:

```bash
# Test news fetch only
python scripts/fetch_and_score_news.py

# Test universe generation
python scripts/generate_daily_universe.py

# Dry run execution (set TRADEZERO_DRY_RUN=1 in .env)
python scripts/execute_live_orb.py
```

## Monitoring

### Real-Time Monitoring
Watch terminal output for live updates during trading hours.

### Post-Trade Analysis

```bash
# View today's closed trades
duckdb state/orb_state.duckdb "SELECT * FROM closed_trades WHERE DATE(entry_time) = CURRENT_DATE"

# Daily equity curve
duckdb state/orb_state.duckdb "SELECT * FROM equity_snapshots ORDER BY snapshot_date"

# Check for errors in logs
cat logs/runs/execute_*_$(date +%Y-%m-%d).log | grep ERROR
```

## Troubleshooting

### No trades executed
1. Check sentiment pipeline: `data/sentiment/daily_YYYY-MM-DD.parquet` has candidates?
2. Check universe: `data/universes/candidates_YYYY-MM-DD.parquet` has Top 5?
3. Check breakouts: Did any symbol break above `or_high`?

### TradeZero connection fails
1. Verify credentials in `config/.env`
2. Check TradeZero web login manually
3. Ensure ChromeDriver installed and accessible

### Missing bars data
1. Check Alpaca API key validity
2. Verify market open (no data on holidays/weekends)
3. Check retry logs for fetch failures

## Production Checklist

Before live deployment:

- [ ] `.env` file configured with valid API keys
- [ ] DuckDB initialized (`init_state_db.py`)
- [ ] Reference files copied (`universe_micro_full.parquet`, `missing_shares_ignore.json`)
- [ ] Test daily data sync in paper trading
- [ ] Test news/sentiment pipeline with real data
- [ ] Validate universe generation produces Top 5
- [ ] Test TradeZero connection and order placement
- [ ] Verify logging output to terminal
- [ ] Set up backup/monitoring for `state/orb_state.duckdb`
- [ ] Document kill switch procedure (manual exit from execution script)

## Performance Expectations

Based on backtest (2021 results):
- **Final Equity**: $1,717,206 from $1,500 seed
- **Return**: +114,380%
- **Win Rate**: 12.7%
- **Profit Factor**: 2.51
- **Trades/Year**: ~428

**Live Degradation**: Expect 50-70% of backtest due to slippage, partial fills, latency.

**Conservative Estimate**: $500K-$1.2M from $1,500 over 1 year.

## Critical Notes

1. **Outlier Dependency**: System requires CAR-like mega-winners (89.7% of profits from 1 trade). Must trade large sample size.

2. **Losing Streaks**: Expect 45-trade losing streaks, 15-day drawdown periods. Iron discipline required.

3. **TradeZero Limitations**: No bracket orders, Selenium fragility, R78 market order rejections.

4. **Execution Speed**: TradeZero orders take 1-3s (Selenium DOM waits). Breakouts may move fast.

5. **Position Sizing**: Equal dollar allocation, not risk-based. Each position gets `(equity/5) * 6x leverage`.

---

## Maintenance & Verification

### Monthly Universe Update

Micro-cap universe needs refreshing as companies issue/buyback shares:

```bash
python scripts/update_micro_universe.py
```

**What it does:**
- Fetches latest shares outstanding from SEC Company Facts (free)
- Falls back to AlphaVantage if SEC fails (requires `ALPHAVANTAGE_API_KEY` in .env)
- Filters to <50M shares
- Updates `data/reference/universe_micro_full.parquet`
- Backs up old universe to `data/reference/backups/`

**Frequency:** Monthly (or after major market events)

**Options:**
```bash
# Force refresh all symbols (slow, ~2-4 hours with AlphaVantage rate limits)
python scripts/update_micro_universe.py --force-refresh

# Skip SEC, use AlphaVantage only (faster but rate limited: 5 calls/min)
python scripts/update_micro_universe.py --no-sec

# Use custom AlphaVantage key
python scripts/update_micro_universe.py --av-api-key YOUR_KEY
```

### Self-Verification System

**Critical:** Verify live system matches backtest 100% before going live.

```bash
python scripts/verify_against_backtest.py \
    --trades-file PATH_TO_BACKTEST_TRADES.parquet \
    --num-dates 10
```

**What it does:**
1. Picks random dates from historical backtest trades
2. Fetches ALL data using live pipeline (news, bars, sentiment)
3. Generates universe using live logic
4. Compares with known backtest trades
5. Reports mismatches (symbols, entry prices, RVOL)

**Exit codes:**
- `0` = 100% match (PASS)
- `1` = Mismatches found (FAIL)

**When to run:**
- Before going live (mandatory)
- After code changes to data pipeline
- Monthly as regression test
- After API changes (Alpaca, AlphaVantage, SEC)

**Example output:**
```
[2026-01-20 10:30:15] Verifying 2021-05-12
  Found 5 sentiment candidates (>0.90 threshold)
  Generated Top 5 universe
  Match: True
  Live: ['AACG', 'CAR', 'MVIS', 'OCGN', 'RKDA']
  Backtest: ['AACG', 'CAR', 'MVIS', 'OCGN', 'RKDA']

VERIFICATION SUMMARY
Dates verified: 10
Perfect matches: 10/10 (100.0%)

✅ VERIFICATION PASSED - 100% match with backtest
```

**Troubleshooting mismatches:**
- News attribution timing (rolling 24H vs pre-market)
- FinBERT model version differences
- Bar data granularity (5-min alignment)
- RVOL calculation rounding errors
- Universe update lag (run monthly update first)

---

**Built**: 20 Jan 2026  
**Strategy**: Sentiment-Driven ORB (5% ATR, Top 5, 0.90 threshold)  
**Broker**: TradeZero (Selenium automation)  
**Status**: Ready for paper trading validation
