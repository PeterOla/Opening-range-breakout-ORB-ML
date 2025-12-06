# Plan: Ross Cameron Strategy Backtest (Final)

**TL;DR:** Build a complete backtesting pipeline for Ross Cameron's bull flag day trading strategy. Extend the `Ticker` table with float data, create a universe builder filtered by gap/RVOL/float, implement bull flag detection with dual exits (2:1 target + EOD), and generate comparable performance reports.

## Steps

### 1. Extend Database Schema
- Add `float` column to `prod/backend/db/models.py` → `Ticker` model (integer, nullable).
- Run migration to alter `tickers` table.

### 2. Populate Float Data (`services/ticker_float_sync.py`)
- Fetch float from YahooFinance API for all tickers in universe.
- Cache locally to avoid re-fetching.
- Run on-demand or as part of daily sync.

### 3. Build Ross Cameron Universe (`scripts/build_ross_cameron_universe.py`)
- Adapt `build_universe.py` with RC-specific filters:
  - **Price**: $2–$20
  - **Gap**: Open ≥ 2% above previous close
  - **RVOL**: ≥ 5.0 (50-day average)
  - **Float**: < 10M shares
  - Skip catalyst (manual review required in live trading)
- Save Top-50 per day ranked by RVOL.
- Output: `universe_rc_20210101_20251231.parquet` with serialized 5-min bars.

### 4. Implement Bull Flag Detection (`scripts/backtest_ross_cameron.py`)
- For each candidate, scan intraday 5-min bars for pattern:
  - **Impulse**: +4% move within 6 bars (30 mins)
  - **Flag**: Pullback that holds above 65% of impulse high
  - **Breakout**: First bar above flag high = Entry
- **Entries**: Breakout price + $0.01
- **Stop**: Low of the flag (pullback)
- **Risk**: Entry − Stop
- **Dual Exits**:
  - Exit 1: Target = Entry + (2 × Risk) — triggered if price hits target
  - Exit 2: EOD close at 16:00 — fallback if target not reached
- Output: `simulated_trades.parquet`, `daily_performance.parquet`, `equity_curve.parquet`

### 5. Generate Backtest Report (reuse existing `generate_backtest_report.py`)
- Create `backtest_report.md` with:
  - Win rate, profit factor, Sharpe ratio, max drawdown
  - Yearly/monthly breakdown
  - Best/worst trades
  - Equity curve visualization
- Compare metrics vs. ORB strategy benchmark.

### 6. Run & Analyse
- Execute: `python scripts/build_ross_cameron_universe.py --start 2021-01-01 --end 2025-12-31`
- Execute: `python scripts/backtest_ross_cameron.py --universe universe_rc_*.parquet --run-name rc_top20_compound`
- Document findings in `PLAN.md` (or similar).

## Further Considerations

1. **Float Data API Choice**: YahooFinance (no auth) vs. AlphaVantage (stable). Recommend YahooFinance for speed.
2. **Bull Flag Thresholds**: Tune impulse % (3%/4%/5%) and flag retracement % (60%/65%/70%) post-backtest.
3. **Catalyst Handling**: Current backtest ignores catalyst filtering. In production, add manual news screening before live trading.
4. **Performance vs. ORB**: Expect lower win rate (RC is shorter-hold intraday pattern) but potentially higher avg winner due to 2:1 discipline.

## Implementation Notes

### Bull Flag Pattern Definition
- **Impulse Move**: Stock rallies 4% in ≤ 30 minutes (6 five-minute bars).
  - Example: Opens at $10.00, rises to $10.40 within 30 mins.
- **Flag/Consolidation**: Price pulls back but holds above 65% of impulse.
  - Impulse range: $0.40
  - 65% threshold: $0.40 × 0.65 = $0.26
  - Support level: $10.40 − $0.26 = $10.14 (must hold above this)
  - If price breaks below → pattern fails, trade cancelled.
- **Breakout/Entry**: Price breaks above flag high = BUY signal.
  - Entry price: Flag high + $0.01

### Risk/Reward Calculation
| Component | Value | Example |
|-----------|-------|---------|
| Entry Price | Breakout high + $0.01 | $10.36 |
| Stop Loss | Low of flag | $10.14 |
| Risk | Entry − Stop | $10.36 − $10.14 = $0.22 |
| Target (2:1) | Entry + (2 × Risk) | $10.36 + $0.44 = $10.80 |

### Data Flow
1. **Universe Build**: Scan all 5-year historical data, apply RC filters (price, gap, RVOL, float).
2. **Pattern Detection**: For each day's Top-50 candidates, scan 5-min bars for bull flags.
3. **Trade Simulation**: Execute entry, check stop/target, record exit reason (STOP, TARGET, EOD).
4. **Performance Analysis**: Aggregate to daily/monthly/yearly stats, generate equity curve.

## Success Criteria

- Win rate ≥ 50% (conservative; RC claims ~71% in live trading).
- Profit factor ≥ 1.5 (gross profit / gross loss).
- Sharpe ratio ≥ 1.0 (risk-adjusted returns).
- Max drawdown ≤ 20% (volatility tolerance).
- Comparable to ORB strategy or better (current ORB: 15.3% win, 1.96 PF, 2.04 Sharpe).
