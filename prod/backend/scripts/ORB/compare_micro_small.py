"""Generate a comparison report for ORB backtest runs.

Usage:
  cd prod/backend
    python scripts/ORB/compare_micro_small.py \
        --runs <RUN_1> <RUN_2> ... \
        --out data/backtest/orb/reports/comparison_summary.md
"""

import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import datetime
import os

from scripts.ORB.analyse_run import summarise_run, run_display_name, write_run_summary_md

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
ORB_RUNS_DIR = DATA_DIR / "backtest" / "orb" / "runs"
ORB_REPORTS_DIR = DATA_DIR / "backtest" / "orb" / "reports"
REPO_ROOT = DATA_DIR.parent


def resolve_run_dir(run_name: str) -> Path:
    candidates = [
        ORB_RUNS_DIR / run_name,  # legacy
        ORB_RUNS_DIR / "compound" / run_name,
        ORB_RUNS_DIR / "atr_stop" / run_name,
        ORB_RUNS_DIR / "experiments" / run_name,
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Run dir not found. Tried: " + ", ".join(str(p) for p in candidates)
    )


def fmt_money(x):
    if x is None:
        return "-"
    return f"${x:,.2f}"


def md_link(text: str, href: str) -> str:
    safe_text = text.replace("|", "\\|")
    safe_href = href.replace(" ", "%20")
    return f"[{safe_text}]({safe_href})"


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare ORB backtest runs")
    ap.add_argument(
        "--runs",
        nargs="+",
        required=True,
        help="Run directory names under data/backtest (e.g. compound_micro_...)",
    )
    ap.add_argument(
        "--out",
        type=str,
        default=str(ORB_REPORTS_DIR / "comparison_micro_small_combo.md"),
        help="Output markdown path (default: data/backtest/orb/reports/comparison_micro_small_combo.md)",
    )
    args = ap.parse_args()

    summaries = []
    for run_name in args.runs:
        run_dir = resolve_run_dir(run_name)
        summaries.append(summarise_run(run_dir))

    # Sort by final equity (if present), else by total leveraged pnl
    summaries.sort(key=lambda s: (s.final_equity if s.final_equity is not None else -1e18, s.total_leveraged_pnl), reverse=True)

    out_path = Path(args.out)
    # If a relative path is provided, interpret it relative to the repository root,
    # not the current working directory (often prod/backend).
    if not out_path.is_absolute():
        out_path = (REPO_ROOT / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append("# ORB Runs — Comparison\n")
    lines.append(f"**Generated:** {generated}\n")
    lines.append("\n")
    lines.append("| Run | Entered | Win Rate | Profit Factor | Total P&L (1x) | Total P&L (5x) | Final Equity |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")

    for s in summaries:
        # Ensure summary exists so the link never 404s
        write_run_summary_md(s.run_dir)
        summary_md = s.run_dir / "summary.md"
        href = Path(os.path.relpath(summary_md, start=out_path.parent)).as_posix()
        label = run_display_name(s.run_name, run_dir=s.run_dir)
        lines.append(
            f"| {md_link(label, href)} | {s.entered_trades:,} | {s.win_rate_pct:.2f}% | {s.profit_factor:.3f} | {fmt_money(s.total_base_pnl)} | {fmt_money(s.total_leveraged_pnl)} | {fmt_money(s.final_equity)} |"
        )

    lines.append("\n")
    lines.append("## Notes\n")
    lines.append("- `Final Equity` is only available for compounding runs (requires `equity_curve.parquet`).\n")
    lines.append("- Profit Factor and Win Rate are computed over entered trades (`exit_reason != NO_ENTRY`).\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report: {out_path}")


if __name__ == "__main__":
    main()
