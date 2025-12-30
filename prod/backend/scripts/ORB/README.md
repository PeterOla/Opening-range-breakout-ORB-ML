# ORB Universe Builders & Backtester

Opening Range Breakout strategy universe builders and backtester.

## Quick Start

### Live (TradeZero) One-Shot Run

Runs `scan → signals → execute` using the configured broker.

```bash
cd prod/backend
python scripts/ORB/run_live_tradezero_once.py --no-execute
```

Notes:
- Trading state (opening ranges + signals) is stored in DuckDB (default: `prod/backend/data/trading_state.duckdb`).
- Override the state path with `DUCKDB_STATE_PATH=...` and ensure `STATE_STORE=duckdb` in your `.env`.

### Live (TradeZero) One-By-One Debug

Execute a single symbol for today's signal (useful for debugging sizing / broker errors):

```bash
cd prod/backend
python scripts/ORB/execute_one_signal.py --symbol OMER --dry-run
```

Notes:
- The script refuses to submit if today's signal already has an `order_id` (use `--force` to override).
- Start with `--dry-run` to avoid placing real orders.

### Daily Top-5 (Fetch → Scan → Execute One-by-One)

Runs the full daily flow and writes a markdown report under repo-root `logs/`.

```bash
cd prod/backend
python scripts/ORB/run_today_top5_one_by_one.py --dry-run
```

Useful flags:
- `--no-sync` — skip the data sync step
- `--skip-fetch` — during sync, skip Alpaca fetch (use existing local parquet)
- `--skip-enrich` — during sync, skip enrichment (includes slow SEC shares sync)
- `--no-flatten` — skip cancel+flatten preflight

### Live (TradeZero) Daily Top-5 Runner (Fetch → Scan → Signals → Execute + Report)

Runs the full daily flow and writes a markdown report under repo-root `logs/` documenting
today’s top-5 candidates, share sizing, and per-symbol execution outcomes.

```bash
cd prod/backend
python scripts/ORB/run_today_top5_one_by_one.py
```

Recommended for UI debugging (saves HTML/CSS/screenshot snapshots under `logs/`):

```bash
cd prod/backend
TZ_DEBUG_DUMP=1 python scripts/ORB/run_today_top5_one_by_one.py
```

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
  --top-n 20 \
  --side long \
  --run-name orb_long_top20
```

### 3. Build Micro+Small Combined Universe (Optional)
If you already have `universe_micro.parquet` and `universe_small.parquet`, you can derive a combined Micro+Small universe (Top-50/day by RVOL across both):

```bash
cd prod/backend
python ORB/build_micro_small_universe.py --out universe_micro_small.parquet
```

### 3b. Build Micro+Small+Unknown Universe (from scratch)
If you want a fresh universe that includes Micro + Small + "Unknown" (missing `shares_outstanding`) candidates, build it **from the raw scan** using the canonical builder so it can still reach Top-50/day:

```bash
cd prod/backend
python ORB/build_universe.py --start 2021-01-01 --end 2025-12-31 --workers 4 --categories micro_small_unknown
```

This writes:
- `data/backtest/orb/universe/universe_micro_small_unknown.parquet`

### 3c. Build Micro+Unknown / Unknown Universes (from scratch)
To run the additional baseline matrix cases, build these universes from the raw scan (so they remain Top-50/day *within that category*):

```bash
cd prod/backend
python ORB/build_universe.py --start 2021-01-01 --end 2025-12-31 --workers 4 --categories micro_unknown unknown
```

This writes:
- `data/backtest/orb/universe/universe_micro_unknown.parquet`
- `data/backtest/orb/universe/universe_unknown.parquet`

### 4. Backtest Micro vs Small vs Micro+Small (Comparison)
Run the three configurations and generate a comparison markdown:

```bash
cd prod/backend
python ORB/run_micro_small_combos.py --top-n 20 --side long --compound --max-pct-volume 0.01
python ORB/compare_micro_small.py --runs \
  compound_micro_liquidity_1pct_atr050_long \
  compound_small_liquidity_1pct_atr050_long \
  compound_micro_small_liquidity_1pct_atr050_long
```

Outputs:
- `data/backtest/orb/universe/universe_micro_small.parquet`
- `data/backtest/orb/runs/compound/compound_micro_small_liquidity_1pct_atr050_long/`
- `data/backtest/orb/reports/comparison_micro_small_combo.md`

### 5. Generate `summary.md` for Each Run (Backfill)
Each run directory contains parquet artefacts; you can generate a human-readable `summary.md` for every run on disk:

```bash
cd prod/backend
python ORB/write_run_summaries.py
```

**Arguments**:
- `--universe` — Universe parquet filename (from `data/backtest/orb/universe/`)
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
Saved under `data/backtest/orb/universe/`:
- `universe_020_YYYYMMDD_YYYYMMDD.parquet` — ATR ≥ 0.20
- `universe_050_YYYYMMDD_YYYYMMDD.parquet` — ATR ≥ 0.50

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
