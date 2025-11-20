import argparse
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


def load_daily_pnl(paths: List[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for p in paths:
        f = p / "portfolio_daily_pnl.csv"
        if not f.exists():
            print(f"[WARN] Missing daily PnL file: {f}")
            continue
        df = pd.read_csv(f, parse_dates=["date"])
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    daily = pd.concat(frames, ignore_index=True)
    daily = daily.sort_values("date").reset_index(drop=True)
    return daily


def load_trades(paths: List[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for p in paths:
        f = p / "portfolio_trades.csv"
        if not f.exists():
            print(f"[WARN] Missing trades file: {f}")
            continue
        df = pd.read_csv(f, parse_dates=["date", "entry_time", "exit_time"])
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    trades = pd.concat(frames, ignore_index=True)
    trades = trades.sort_values(["date", "symbol"]).reset_index(drop=True)
    return trades


def load_yearly_stats(paths: List[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for p in paths:
        f = p / "portfolio_per_year_overall_stats.csv"
        if not f.exists():
            print(f"[WARN] Missing yearly stats file: {f}")
            continue
        df = pd.read_csv(f)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    yearly = pd.concat(frames, ignore_index=True)
    if "year" in yearly.columns:
        yearly = yearly.sort_values("year").reset_index(drop=True)
    return yearly


def compute_overall_metrics(daily: pd.DataFrame, trades: pd.DataFrame) -> dict:
    if daily.empty:
        return {}

    daily = daily.sort_values("date").reset_index(drop=True)
    start_eq = float(daily["equity"].iloc[0])
    end_eq = float(daily["equity"].iloc[-1])
    start_date = daily["date"].iloc[0]
    end_date = daily["date"].iloc[-1]
    days = (end_date - start_date).days
    years = days / 365.0 if days > 0 else 1.0

    total_return = (end_eq / start_eq) - 1.0 if start_eq > 0 else np.nan
    cagr = (end_eq / start_eq) ** (1.0 / years) - 1.0 if start_eq > 0 and end_eq > 0 else np.nan

    # max drawdown
    eq = daily["equity"].astype(float)
    peak = eq.cummax()
    dd = (eq - peak) / peak
    max_dd = float(dd.min()) if not dd.empty else np.nan

    # trade metrics
    if trades.empty or "net_pnl" not in trades.columns:
        hit_rate = np.nan
        profit_factor = np.nan
        n_trades = 0
        n_no_trade_days = int(daily.shape[0])  # if no trades at all, every day is a no-trade day
    else:
        pnl = trades["net_pnl"].astype(float)
        n_trades = int(len(pnl))
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        gross_profit = wins.sum()
        gross_loss = -losses.sum()
        hit_rate = len(wins) / len(pnl) if len(pnl) > 0 else np.nan
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.nan

        # days with at least one trade vs total days in equity curve
        traded_days = trades["date"].dt.normalize().unique()
        all_days = daily["date"].dt.normalize().unique()
        n_no_trade_days = int(len(all_days) - len(traded_days))

    # Sharpe ratio (annualized)
    # Compute daily returns from equity changes
    if not daily.empty and len(daily) > 1:
        daily_sorted = daily.sort_values("date").reset_index(drop=True)
        equity_vals = daily_sorted["equity"].astype(float)
        daily_returns = equity_vals.pct_change().dropna()
        
        if len(daily_returns) > 0 and daily_returns.std() > 0:
            # Annualized Sharpe: mean daily return / std daily return * sqrt(252 trading days)
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        else:
            sharpe = np.nan
    else:
        sharpe = np.nan

    return {
        "start_date": start_date.date().isoformat(),
        "end_date": end_date.date().isoformat(),
        "start_equity": start_eq,
        "end_equity": end_eq,
        "days": days,
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
    "n_trades": n_trades,
    "n_no_trade_days": n_no_trade_days,
        "hit_rate": hit_rate,
        "profit_factor": profit_factor,
        "sharpe_ratio": sharpe,
    }


def _compute_wealth_paths(daily: pd.DataFrame, kelly_info: dict | None) -> dict:
    """Compute wealth paths starting from 1000 for base, Kelly, safe, and danger fractions.

    We scale the equity curve so that the initial equity maps to 1000 and report
    the final wealth. This mirrors what we did in plot_equity_and_wealth.py.
    """
    if daily.empty:
        return {}

    daily = daily.sort_values("date").reset_index(drop=True)
    if "equity" not in daily.columns:
        return {}

    start_eq = float(daily["equity"].iloc[0])
    end_eq = float(daily["equity"].iloc[-1])
    if start_eq <= 0:
        return {}

    total_return = end_eq / start_eq

    # Baseline: 1000 scaled by total_return at current risk (1% per trade in the runs)
    wealth_base = 1000.0 * total_return

    wealth = {"wealth_1000_base": wealth_base}

    # If we have Kelly-style fractions from the most recent year, approximate
    # what 1000 would grow to at those risk levels by linear scaling vs current risk.
    # Current risk_per_trade_frac is 0.01 => treat that as 1.0x.
    if kelly_info:
        # Fractions are in percent terms (e.g. 6.59 means 6.59%)
        base_risk_pct = 1.0
        kelly_pct = float(kelly_info.get("kelly_fraction_pct", base_risk_pct))
        safe_pct = float(kelly_info.get("safe_fraction_pct", base_risk_pct))
        danger_pct = float(kelly_info.get("danger_fraction_pct", base_risk_pct))

        wealth["wealth_1000_at_safe"] = wealth_base * (safe_pct / base_risk_pct)
        wealth["wealth_1000_at_kelly"] = wealth_base * (kelly_pct / base_risk_pct)
        wealth["wealth_1000_at_danger"] = wealth_base * (danger_pct / base_risk_pct)

    return wealth


def write_summary(output_dir: Path, metrics: dict, wealth_info: dict | None = None, kelly_info: dict | None = None) -> None:
    summary_path = output_dir / "summary.txt"
    if not metrics:
        summary_path.write_text("No data available to compute summary.\n", encoding="utf-8")
        return

    lines = ["=== Combined Portfolio Summary ===", ""]
    lines.append("Core metrics:")
    for k, v in metrics.items():
        lines.append(f"  {k}: {v}")

    # Wealth summaries based on combined equity curve (starting from 1000)
    if wealth_info:
        lines.append("")
        lines.append("Wealth summary (start 1000, using combined equity curve):")
        for k, v in wealth_info.items():
            lines.append(f"  {k}: {v}")

    # Kelly-style fractions (if we have them from yearly stats)
    if kelly_info:
        lines.append("")
        lines.append("Kelly-style fraction summary (from yearly stats, using most recent year):")
        for k, v in kelly_info.items():
            lines.append(f"  {k}: {v}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine yearly ORB portfolio results into a single summary.")
    parser.add_argument(
        "--results-dirs",
        nargs="+",
        required=True,
        help="List of yearly results directories, e.g. results_active_2021_top20 results_active_2022_top20",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results_combined_top20",
        help="Output directory for combined results.",
    )
    args = parser.parse_args()

    result_paths = [Path(p) for p in args.results_dirs]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    daily = load_daily_pnl(result_paths)
    trades = load_trades(result_paths)
    yearly = load_yearly_stats(result_paths)

    # Recompute continuous equity from net_pnl starting from initial 100k
    # (Each yearly backtest starts at 100k; we concat their daily PnLs and rebuild equity from scratch)
    if not daily.empty and "net_pnl" in daily.columns:
        daily = daily.sort_values("date").reset_index(drop=True)
        start_eq = 100_000.0  # Always start from the standard initial equity
        daily["equity"] = start_eq + daily["net_pnl"].astype(float).cumsum()

    # Save combined CSVs
    if not daily.empty:
        daily.to_csv(output_dir / "all_daily_pnl.csv", index=False)
    if not trades.empty:
        trades.to_csv(output_dir / "all_trades.csv", index=False)
    if not yearly.empty:
        yearly.to_csv(output_dir / "all_yearly_stats.csv", index=False)

    metrics = compute_overall_metrics(daily, trades)

    # Kelly-style fractions: take from the most recent year if available
    kelly_info: dict | None = None
    if not yearly.empty:
        last = yearly.iloc[-1]
        for key in ("kelly_fraction_pct", "safe_fraction_pct", "danger_fraction_pct"):
            if key in last:
                if kelly_info is None:
                    kelly_info = {}
                kelly_info[key] = float(last[key])

    # Wealth info from combined equity curve (base + Kelly/safe/danger scenarios)
    wealth_info = _compute_wealth_paths(daily, kelly_info)

    write_summary(output_dir, metrics, wealth_info=wealth_info, kelly_info=kelly_info)


if __name__ == "__main__":
    main()
