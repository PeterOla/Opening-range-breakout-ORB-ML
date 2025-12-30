# ORB 30M Fibonacci (Fast Backtest)

Fast backtester for the **ORB + Fibonacci pullback** strategy described in:
- `strategies/ORB 30M Fib/docs/readme.md`

This is intentionally modelled after `scripts/ORB/fast_backtest.py`:
- Reads an existing ORB **universe parquet** (Top candidates per day)
- Re-ranks by `rvol` and selects Top-N per day
- Simulates trades quickly from stored 5-min bars (`bars_json`)
- Applies **share sizing with a liquidity cap** (`--max-pct-volume`)
- Writes parquet artefacts + a `summary.md` in a per-run folder

## Location

This strategy is intentionally in its own folder (not under `scripts/ORB/`).

- Script: `prod/backend/scripts/ORB30MFib/fast_backtest.py`
- Outputs: `data/backtest/orb_30m_fib/runs/<group>/<run-name>/...`

## Quick Start

From `prod/backend`:

```bash
python scripts/ORB30MFib/fast_backtest.py \
  --universe universe_micro.parquet \
  --top-n 20 \
  --side long \
  --run-name fib_micro_long_top20 \
  --or-minutes 30 \
  --max-entry-minutes 120 \
  --fib-entry either \
  --osc macd \
  --stop-mode fib_786 \
  --target-mode session_extreme
```

## Arguments

- `--universe` (required): Universe parquet filename from `data/backtest/orb/universe/`
- `--run-name` (required): Output folder name
- `--top-n`: Candidates per day (default: 20)
- `--side`: `long|short|both` (default: both)
- `--compound`: Enable compounding mode (equal split across Top-N)
- `--max-pct-volume`: Liquidity cap as % of daily volume (default: 0.01 = 1%)

Strategy parameters:
- `--or-minutes`: Opening range window in minutes (default: 30)
- `--max-entry-minutes`: Only allow breakouts/entries in the first N minutes after 09:30 (default: 120)
- `--fib-entry`: `50|618|either` (default: either)
- `--osc`: `macd|rsi|none` (default: macd)
- `--rsi-threshold`: RSI threshold (default: 50)
- `--stop-mode`: `fib_786|swing` (default: fib_786)
- `--swing-buffer-pct`: Buffer applied to swing stop (default: 0.001 = 0.1%)
- `--stop-buffer-pct`: Extra buffer for stops to represent “just below/above” (default: 0.0005 = 0.05%)
- `--target-mode`: `session_extreme|rr` (default: session_extreme)
- `--rr`: R-multiple used when `--target-mode=rr` (default: 2.0)

## Outputs

Written per run directory:
- `run_config.json` — full parameter dump
- `simulated_trades.parquet` — per-trade results including `actual_shares`, `target_shares`, `max_allowed_shares`, `is_capped`, `cap_ratio`
- `daily_performance.parquet` — grouped daily P&L
- `equity_curve.parquet` — only when `--compound`
- `yearly_results.parquet` — only when `--compound`
- `summary.md` — human-readable metrics and liquidity cap diagnostics

## Plot Trades (Visual Inspection)

Generate a small set of PNG charts (top winners, top losers, and a few EOD exits):

```bash
cd prod/backend
python scripts/ORB30MFib/plot_trades.py \
  --run-name test_strict_fib_micro_long_top3 \
  --universe universe_micro.parquet \
  --n 3
```

This writes:
- `data/backtest/orb_30m_fib/runs/**/<run-name>/trade_charts/*.png`
