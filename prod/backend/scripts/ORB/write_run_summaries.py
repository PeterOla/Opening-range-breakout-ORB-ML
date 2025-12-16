"""Backfill summary.md files for existing ORB backtest run directories.

Usage:
  cd prod/backend
  python ORB/write_run_summaries.py

This scans data/backtest/orb/runs/** for directories containing
simulated_trades.parquet and creates/overwrites summary.md.
"""

import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path

from scripts.ORB.analyse_run import write_run_summary_md


DATA_DIR = Path(__file__).resolve().parents[4] / "data"
DEFAULT_RUNS_ROOT = DATA_DIR / "backtest" / "orb" / "runs"


def main() -> None:
    ap = argparse.ArgumentParser(description="Write summary.md for existing run folders")
    ap.add_argument(
        "--runs-root",
        type=str,
        default=str(DEFAULT_RUNS_ROOT),
        help="Root directory to scan (default: data/backtest/orb/runs)",
    )
    args = ap.parse_args()

    runs_root = Path(args.runs_root)
    if not runs_root.exists():
        raise FileNotFoundError(f"Runs root not found: {runs_root}")

    written = 0
    scanned = 0

    for trades_path in runs_root.rglob("simulated_trades.parquet"):
        run_dir = trades_path.parent
        scanned += 1
        out_path = write_run_summary_md(run_dir)
        print(f"Wrote: {out_path}")
        written += 1

    print(f"Done. Scanned {scanned} runs, wrote {written} summaries.")


if __name__ == "__main__":
    main()
