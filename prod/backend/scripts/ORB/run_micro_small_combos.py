"""Run backtests for Micro, Small, and Micro+Small universes and generate a comparison report.

This is a convenience wrapper around `fast_backtest.run_strategy`.

Usage:
  cd prod/backend

  # 1) Build combined universe
  python ORB/build_micro_small_universe.py --out universe_micro_small.parquet

  # 2) Run backtests
  python ORB/run_micro_small_combos.py --top-n 20 --side long --compound --max-pct-volume 0.01

  # 3) Write comparison markdown
  python ORB/compare_micro_small.py --runs \
    compound_micro_liquidity_1pct_atr050_long \
    compound_small_liquidity_1pct_atr050_long \
    compound_micro_small_liquidity_1pct_atr050_long
"""

import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path

from scripts.ORB.fast_backtest import run_strategy

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
ORB_UNIVERSE_DIR = DATA_DIR / "backtest" / "orb" / "universe"


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Micro/Small/Micro+Small backtest combos")
    ap.add_argument("--top-n", type=int, default=20)
    ap.add_argument("--side", choices=["long", "short", "both"], default="long")
    ap.add_argument("--compound", action="store_true")
    ap.add_argument("--daily-risk", type=float, default=0.10)
    ap.add_argument("--max-pct-volume", type=float, default=0.01)

    ap.add_argument("--universe-micro", type=str, default="universe_micro.parquet")
    ap.add_argument("--universe-small", type=str, default="universe_small.parquet")
    ap.add_argument("--universe-micro-small", type=str, default="universe_micro_small.parquet")

    ap.add_argument("--run-micro", type=str, default="compound_micro_liquidity_1pct_atr050_long")
    ap.add_argument("--run-small", type=str, default="compound_small_liquidity_1pct_atr050_long")
    ap.add_argument("--run-micro-small", type=str, default="compound_micro_small_liquidity_1pct_atr050_long")

    args = ap.parse_args()

    # Keep consistent with fast_backtest.py hardcoded filters
    MIN_ATR = 0.50
    MIN_VOLUME = 100_000

    risk_per_trade = args.daily_risk / args.top_n

    runs = [
        (args.universe_micro, args.run_micro),
        (args.universe_small, args.run_small),
        (args.universe_micro_small, args.run_micro_small),
    ]

    for universe_file, run_name in runs:
        universe_path = ORB_UNIVERSE_DIR / universe_file
        if not universe_path.exists():
            raise FileNotFoundError(f"Universe not found: {universe_path}")

        print("\n" + "=" * 80)
        print(f"Universe: {universe_file}")
        print(f"Run name: {run_name}")
        print("=" * 80)

        run_strategy(
            universe_path=universe_path,
            min_atr=MIN_ATR,
            min_volume=MIN_VOLUME,
            top_n=args.top_n,
            side_filter=args.side,
            run_name=run_name,
            compound=args.compound,
            risk_per_trade=risk_per_trade,
            verbose=False,
            max_pct_volume=args.max_pct_volume,
        )


if __name__ == "__main__":
    main()
