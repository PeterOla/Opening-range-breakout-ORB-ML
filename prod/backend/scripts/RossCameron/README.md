# Ross Cameron Universe Builders & Backtester

Ross Cameron bull flag strategy universe builders and backtester.

## Quick Start

### 1. Build Full Historical Universe
```bash
cd prod/backend
python RossCameron/build_universe.py --start 2021-01-01 --end 2025-12-31
```

### 2. Run Backtest
```bash
python RossCameron/backtest.py \
  --universe universe_rc_20210101_20251205.parquet \
  --run-name rc_bull_flags
```

**Arguments**:
- `--universe` — Universe parquet filename (from data/backtest/)
- `--run-name` — Name for this backtest run

## Output

Single parquet file with Top-50 daily candidates:
- `data/backtest/universe_rc_YYYYMMDD_YYYYMMDD.parquet`

## Strategy Filters

| Filter | Value |
|--------|-------|
| Price | $2–$20 |
| Gap | Open ≥ 2% above previous close |
| RVOL | ≥ 5.0× (50-day average volume) |
| Average Volume | ≥ 1M shares (50-day) |
| Float | < 10M shares |
| Ranking | Top-50 per day by RVOL |

## Columns in Output

- `trade_date` — Trading date
- `ticker` — Stock symbol
- `direction` — Always 1 (bullish) for RC strategy
- `rvol` — Relative volume (78 bars scaled)
- `rvol_rank` — Rank 1-50 by RVOL for the day
- `gap_pct` — Gap percentage at open
- `or_open, or_high, or_low, or_close, or_volume` — Opening range (9:30 ET bar)
- `avg_volume_50d` — 50-day average volume
- `prev_close` — Previous day's close
- `shares_outstanding` — Float (shares outstanding)
- `bars_json` — JSON-serialized 5-minute bars for the day
