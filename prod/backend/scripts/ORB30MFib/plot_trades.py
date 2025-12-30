"""Plot a small sample of ORB30MFib trades for visual inspection.

Reads:
- Run artefacts: `data/backtest/orb_30m_fib/runs/**/<run-name>/simulated_trades.parquet`
- Universe parquet (for `bars_json`): `data/backtest/orb/universe/<universe>.parquet`

Writes:
- PNGs into: `<run_dir>/trade_charts/`

Usage:
    cd prod/backend
    python scripts/ORB30MFib/plot_trades.py --run-name <RUN> --universe universe_micro.parquet

Notes:
- Uses matplotlib only (no mplfinance dependency).
- Charts include OR levels, Fib levels, entry/stop/target, breakout and entry markers.
"""

import sys

sys.path.insert(0, ".")

import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


DATA_DIR = Path(__file__).resolve().parents[4] / "data"
ORB_UNIVERSE_DIR = DATA_DIR / "backtest" / "orb" / "universe"
FIB_RUNS_DIR = DATA_DIR / "backtest" / "orb_30m_fib" / "runs"


def _deserialize_bars(bars_data) -> pd.DataFrame:
    if isinstance(bars_data, str):
        data = json.loads(bars_data)
        df = pd.DataFrame(data)
        df["datetime"] = pd.to_datetime(df["datetime"])
    else:
        df = pd.DataFrame(bars_data, columns=["datetime", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["datetime"])

    df = df.sort_values("datetime").copy()
    df = df.set_index("datetime")
    return df


def _find_run_dir(run_name: str, run_dir: Optional[str] = None) -> Path:
    if run_dir:
        p = Path(run_dir)
        if not p.exists():
            raise FileNotFoundError(f"Run dir not found: {p}")
        return p

    matches = [p for p in FIB_RUNS_DIR.rglob(run_name) if p.is_dir()]
    if not matches:
        raise FileNotFoundError(f"Run dir not found under {FIB_RUNS_DIR}: {run_name}")
    if len(matches) > 1:
        # Prefer exact leaf match
        exact = [m for m in matches if m.name == run_name]
        if len(exact) == 1:
            return exact[0]
        raise RuntimeError(f"Multiple run dirs found for {run_name}: {matches}")
    return matches[0]


def _compute_opening_range(day_bars: pd.DataFrame, *, or_minutes: int) -> Optional[dict]:
    if day_bars.empty:
        return None

    # Day bars are in ET; OR is 09:30 onward.
    start_dt = day_bars.between_time("09:30", "09:30").index
    if len(start_dt) == 0:
        # fallback to first bar
        start = day_bars.index.min()
    else:
        start = start_dt[0]

    end = start + pd.Timedelta(minutes=or_minutes)
    or_bars = day_bars[(day_bars.index >= start) & (day_bars.index < end)]
    if or_bars.empty:
        return None

    return {
        "start": start,
        "end": end,
        "high": float(or_bars["high"].max()),
        "low": float(or_bars["low"].min()),
    }


def _pick_trades(df: pd.DataFrame, n_each: int, seed: int) -> pd.DataFrame:
    entered = df[df["exit_reason"] != "NO_ENTRY"].copy()
    if entered.empty:
        return entered

    # Prefer base PnL for comparability across caps.
    pnl_col = "base_dollar_pnl" if "base_dollar_pnl" in entered.columns else "dollar_pnl"
    entered[pnl_col] = pd.to_numeric(entered[pnl_col], errors="coerce").fillna(0.0)

    winners = entered.nlargest(n_each, pnl_col)
    losers = entered.nsmallest(n_each, pnl_col)

    eod = entered[entered["exit_reason"] == "EOD"]
    if not eod.empty:
        eod = eod.sample(n=min(n_each, len(eod)), random_state=seed)

    picked = pd.concat([winners, losers, eod], ignore_index=True).drop_duplicates(subset=["trade_date", "ticker"]).reset_index(drop=True)
    return picked


def plot_trade(
    *,
    trade: pd.Series,
    day_bars: pd.DataFrame,
    out_path: Path,
    or_minutes: int,
):
    plt.close("all")

    fig, ax = plt.subplots(figsize=(14, 7))

    # Price: close + high/low range.
    x = np.arange(len(day_bars))
    close = day_bars["close"].astype(float).to_numpy()
    high = day_bars["high"].astype(float).to_numpy()
    low = day_bars["low"].astype(float).to_numpy()

    ax.vlines(x, low, high, color="black", linewidth=0.5, alpha=0.6)
    ax.plot(x, close, color="black", linewidth=1.0, label="Close")

    # Map datetimes to x for markers
    index = day_bars.index

    def x_of(ts: Optional[pd.Timestamp]) -> Optional[int]:
        if ts is None:
            return None
        # pick nearest bar
        pos = int(index.searchsorted(ts))
        if pos <= 0:
            return 0
        if pos >= len(index):
            return len(index) - 1
        return pos

    trade_date = pd.to_datetime(trade["trade_date"]).date()
    ticker = str(trade["ticker"])

    entry_time = None
    if pd.notna(trade.get("entry_time")):
        entry_time = pd.to_datetime(f"{trade_date} {trade['entry_time']}")

    breakout_time = None
    if pd.notna(trade.get("breakout_time")):
        breakout_time = pd.to_datetime(f"{trade_date} {trade['breakout_time']}")

    # Opening range box
    or_info = _compute_opening_range(day_bars, or_minutes=or_minutes)
    if or_info:
        or_start_x = x_of(or_info["start"])
        or_end_x = x_of(or_info["end"])
        ax.axhline(or_info["high"], color="grey", linestyle="--", linewidth=1.0, alpha=0.7, label="OR High")
        ax.axhline(or_info["low"], color="grey", linestyle="--", linewidth=1.0, alpha=0.7, label="OR Low")
        if or_start_x is not None and or_end_x is not None:
            ax.axvspan(or_start_x, or_end_x, color="grey", alpha=0.08)

    # Fib levels
    for key, colour in [("fib_50", "#1f77b4"), ("fib_618", "#ff7f0e"), ("fib_786", "#d62728")]:
        val = trade.get(key)
        if val is None or pd.isna(val):
            continue
        ax.axhline(float(val), color=colour, linestyle=":", linewidth=1.2, alpha=0.9, label=key)

    # Entry/stop/target
    entry_px = trade.get("entry_price")
    stop_px = trade.get("stop_price")
    target_px = trade.get("target_price")

    if entry_px is not None and pd.notna(entry_px):
        ax.axhline(float(entry_px), color="green", linestyle="--", linewidth=1.2, label="Entry")
    if stop_px is not None and pd.notna(stop_px):
        ax.axhline(float(stop_px), color="red", linestyle="--", linewidth=1.2, label="Stop")
    if target_px is not None and pd.notna(target_px):
        ax.axhline(float(target_px), color="purple", linestyle="--", linewidth=1.2, label="Target")

    # Breakout + entry markers
    bx = x_of(breakout_time)
    if bx is not None:
        ax.axvline(bx, color="orange", linestyle="-", linewidth=1.0, alpha=0.8, label="Breakout")

    ex = x_of(entry_time)
    if ex is not None and entry_px is not None and pd.notna(entry_px):
        ax.scatter([ex], [float(entry_px)], color="green", s=60, marker="^", zorder=5)

    # Title and legend
    pnl = trade.get("base_dollar_pnl")
    pnl_pct = trade.get("pnl_pct")
    exit_reason = trade.get("exit_reason")

    title_bits = [f"{ticker} {trade_date}"]
    if exit_reason:
        title_bits.append(str(exit_reason))
    if pnl is not None and pd.notna(pnl):
        title_bits.append(f"PnL={float(pnl):+.2f}")
    if pnl_pct is not None and pd.notna(pnl_pct):
        title_bits.append(f"({float(pnl_pct):+.2f}%)")

    ax.set_title(" | ".join(title_bits))
    ax.set_ylabel("Price")

    # Clean x-axis with time labels every ~12 bars
    step = max(1, len(index) // 12)
    ticks = list(range(0, len(index), step))
    labels = [index[i].strftime("%H:%M") for i in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=0)

    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--run-dir", default=None, help="Optional explicit run directory")
    ap.add_argument("--universe", required=True, help="Universe parquet filename from data/backtest/orb/universe/")
    ap.add_argument("--n", type=int, default=3, help="How many winners/losers/EOD trades to plot")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    run_dir = _find_run_dir(args.run_name, run_dir=args.run_dir)
    trades_path = run_dir / "simulated_trades.parquet"
    cfg_path = run_dir / "run_config.json"

    if not trades_path.exists():
        raise FileNotFoundError(f"Missing trades parquet: {trades_path}")

    if not cfg_path.exists():
        raise FileNotFoundError(f"Missing run config: {cfg_path}")

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    or_minutes = int(cfg.get("opening_range_minutes", 30))

    universe_path = ORB_UNIVERSE_DIR / args.universe
    if not universe_path.exists():
        legacy = DATA_DIR / "backtest" / args.universe
        if legacy.exists():
            universe_path = legacy
        else:
            raise FileNotFoundError(f"Universe not found: {universe_path}")

    print(f"Loading trades: {trades_path}")
    df_trades = pd.read_parquet(trades_path)
    picked = _pick_trades(df_trades, n_each=args.n, seed=args.seed)
    if picked.empty:
        print("No entered trades found to plot.")
        return

    print(f"Loading universe: {universe_path}")
    df_universe = pd.read_parquet(universe_path)

    if not pd.api.types.is_datetime64_any_dtype(df_universe["trade_date"]):
        df_universe["trade_date"] = pd.to_datetime(df_universe["trade_date"])

    out_dir = run_dir / "trade_charts"
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    for _, trade in picked.iterrows():
        ticker = str(trade["ticker"])
        trade_date = pd.to_datetime(trade["trade_date"]).date()

        candidate = df_universe[(df_universe["ticker"] == ticker) & (df_universe["trade_date"].dt.date == trade_date)]
        if candidate.empty:
            print(f"No universe row for {ticker} {trade_date}")
            continue

        bars = _deserialize_bars(candidate.iloc[0]["bars_json"])
        day_bars = bars.copy()

        fname = f"{ticker}_{trade_date}_{trade.get('exit_reason','NA')}.png"
        out_path = out_dir / fname

        plot_trade(trade=trade, day_bars=day_bars, out_path=out_path, or_minutes=or_minutes)
        saved += 1
        print(f"Saved: {out_path}")

    print(f"\nDone. Saved {saved} charts to: {out_dir}")


if __name__ == "__main__":
    main()
