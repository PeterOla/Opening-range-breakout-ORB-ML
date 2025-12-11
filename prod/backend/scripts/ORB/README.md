# ORB Universe Builders & Backtester

Opening Range Breakout strategy universe builders and backtester.

## Quick Start

### 1. Build Full Historical Universe
```bash
cd prod/backend
python ORB/build_universe.py --start 2021-01-01 --end 2025-12-31 --workers 4
```

**Arguments**:
- `--start` — Start date (YYYY-MM-DD)
- `--end` — End date (YYYY-MM-DD)
- `--min-price` — Minimum stock price filter (default: $5.00)
- `--min-volume` — Minimum average volume filter (default: 1,000,000)
- `--workers` — Parallel workers (default: CPU count - 1)

### 2. Run Backtest
```bash
python ORB/fast_backtest.py \
  --universe universe_050_20210101_20251205.parquet \
  --stop-mode or \
  --top-n 20 \
  --side long \
  --run-name orb_long_top20
```

**Arguments**:
- `--universe` — Universe parquet filename (from data/backtest/)
- `--stop-mode` — `or` (opening range) or `atr` (ATR-based)
- `--min-atr` — Minimum ATR filter (default: 0.50)
- `--min-volume` — Minimum volume filter (default: 1M)
- `--top-n` — Top N candidates per day (default: 20)
- `--side` — `long`, `short`, or `both` (default: both)
- `--run-name` — Name for this backtest run
- `--compound` — Enable compounding with yearly reset
- `--daily-risk` — Daily risk target (default: 0.10 = 10%)

## Output

Two parquet files with Top-50 daily candidates:
- `data/backtest/universe_020_YYYYMMDD_YYYYMMDD.parquet` — ATR ≥ 0.20
- `data/backtest/universe_050_YYYYMMDD_YYYYMMDD.parquet` — ATR ≥ 0.50

## Strategy Filters

| Filter | Value |
|--------|-------|
| Price | ≥ $5.00 |
| Average Volume | ≥ 1M shares |
| RVOL | ≥ 1.0× (relative to 14-day avg) |
| ATR Tiers | 0.20 and 0.50 |
| Ranking | Top-50 per day by RVOL |

## Columns in Output

- `trade_date` — Trading date
- `ticker` — Stock symbol
- `direction` — 1 (up), -1 (down)
- `rvol` — Relative volume (78 bars scaled)
- `rvol_rank` — Rank 1-50 by RVOL for the day
- `or_open, or_high, or_low, or_close, or_volume` — Opening range (9:30 ET bar)
- `atr_14` — 14-day ATR
- `avg_volume_14` — 14-day average volume
- `prev_close` — Previous day's close
- `bars_json` — JSON-serialized 5-minute bars for the day
