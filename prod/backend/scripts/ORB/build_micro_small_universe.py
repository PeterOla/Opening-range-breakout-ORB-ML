"""Build a combined Micro+Small universe from existing Micro and Small universes.

Rationale
- `build_universe.py` already creates:
  - `data/backtest/universe_micro.parquet` (Top-50 micro per day)
  - `data/backtest/universe_small.parquet` (Top-50 small per day)

A combined Micro+Small Top-50 per day can be derived by concatenating those two
and re-ranking by RVOL per day.

Usage:
  cd prod/backend
  python ORB/build_micro_small_universe.py \
    --micro universe_micro.parquet \
    --small universe_small.parquet \
    --out universe_micro_small.parquet \
    --top-k 50
"""

import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
OUT_DIR = DATA_DIR / "backtest" / "orb" / "universe"


def build_micro_small_universe(micro_path: Path, small_path: Path, out_path: Path, top_k: int) -> pd.DataFrame:
    df_micro = pd.read_parquet(micro_path)
    df_small = pd.read_parquet(small_path)

    df = pd.concat([df_micro, df_small], ignore_index=True)

    # Re-rank per day by RVOL
    df = df.sort_values(["trade_date", "rvol"], ascending=[True, False])
    df = df.groupby("trade_date").head(top_k).reset_index(drop=True)

    # Recompute rvol_rank within the combined universe
    df["rvol_rank"] = df.groupby("trade_date").cumcount() + 1

    df.to_parquet(out_path, index=False)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Build combined Micro+Small universe parquet")
    ap.add_argument("--micro", type=str, default="universe_micro.parquet", help="Micro universe parquet filename under data/backtest")
    ap.add_argument("--small", type=str, default="universe_small.parquet", help="Small universe parquet filename under data/backtest")
    ap.add_argument("--out", type=str, default="universe_micro_small.parquet", help="Output parquet filename under data/backtest")
    ap.add_argument("--top-k", type=int, default=50, help="Max candidates per day to keep")
    args = ap.parse_args()

    micro_path = OUT_DIR / args.micro
    small_path = OUT_DIR / args.small
    out_path = OUT_DIR / args.out

    if not micro_path.exists():
        raise FileNotFoundError(f"Micro universe not found: {micro_path}")
    if not small_path.exists():
        raise FileNotFoundError(f"Small universe not found: {small_path}")

    df = build_micro_small_universe(micro_path, small_path, out_path, args.top_k)
    print(f"Saved combined universe: {out_path}")
    print(f"Rows: {len(df):,}")
    print(f"Days: {df['trade_date'].nunique():,}")


if __name__ == "__main__":
    main()
