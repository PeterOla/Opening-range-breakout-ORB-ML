"""Summarise a fast_backtest run directory into a single metrics dict.

Used for generating comparison markdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from datetime import datetime
import re
import pandas as pd


@dataclass(frozen=True)
class RunSummary:
    run_name: str
    run_dir: Path
    entered_trades: int
    total_trades: int
    win_rate_pct: float
    profit_factor: float
    total_base_pnl: float
    total_leveraged_pnl: float
    final_equity: Optional[float]


def summarise_run(run_dir: Path) -> RunSummary:
    run_name = run_dir.name
    trades_path = run_dir / "simulated_trades.parquet"
    equity_path = run_dir / "equity_curve.parquet"

    if not trades_path.exists():
        raise FileNotFoundError(f"Missing {trades_path}")

    df_trades = pd.read_parquet(trades_path)
    total_trades = len(df_trades)

    entered = df_trades[df_trades["exit_reason"] != "NO_ENTRY"].copy()
    entered_trades = len(entered)

    if entered_trades == 0:
        win_rate_pct = 0.0
        profit_factor = 0.0
        total_base_pnl = 0.0
        total_leveraged_pnl = 0.0
    else:
        winners = entered[entered["pnl_pct"] > 0]
        losers = entered[entered["pnl_pct"] < 0]
        win_rate_pct = (len(winners) / entered_trades) * 100

        gross_profit = float(winners["base_dollar_pnl"].fillna(0).sum()) if not winners.empty else 0.0
        gross_loss = float(losers["base_dollar_pnl"].fillna(0).sum()) if not losers.empty else 0.0
        gross_loss_abs = abs(gross_loss)
        profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else (gross_profit if gross_profit > 0 else 0.0)

        total_base_pnl = float(entered["base_dollar_pnl"].fillna(0).sum())
        total_leveraged_pnl = float(entered["dollar_pnl"].fillna(0).sum())

    final_equity: Optional[float] = None
    if equity_path.exists():
        df_eq = pd.read_parquet(equity_path)
        if not df_eq.empty:
            final_equity = float(df_eq.iloc[-1]["equity"])

    return RunSummary(
        run_name=run_name,
        run_dir=run_dir,
        entered_trades=entered_trades,
        total_trades=total_trades,
        win_rate_pct=round(win_rate_pct, 2),
        profit_factor=round(profit_factor, 3),
        total_base_pnl=round(total_base_pnl, 2),
        total_leveraged_pnl=round(total_leveraged_pnl, 2),
        final_equity=round(final_equity, 2) if final_equity is not None else None,
    )


def _fmt_money(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"${x:,.2f}"


def _title_universe(universe_key: str) -> str:
    key = (universe_key or "").strip().lower()
    if key in {"micro"}:
        return "Micro"
    if key in {"small"}:
        return "Small"
    if key in {"large"}:
        return "Large"
    if key in {"all"}:
        return "All"
    if key in {"unknown"}:
        return "Unknown"
    if key in {"micro_unknown", "micro+unknown", "micro-unknown"}:
        return "Micro+Unknown"
    if key in {"micro_small", "micro+small", "micro-small"}:
        return "Micro+Small"
    if key in {"micro_small_unknown", "micro+small+unknown", "micro-small-unknown"}:
        return "Micro+Small+Unknown"
    if not key:
        return "-"
    return key.replace("_", " ").title()


def describe_run_name(run_name: str) -> dict:
    """Best-effort decoding of run folder naming convention into plain English."""
    name = (run_name or "").strip()
    lowered = name.lower()

    desc: dict = {
        "raw": name,
        "mode": "-",
        "universe": "-",
        "side": "-",
        "min_atr": None,
        "max_pct_volume": None,
    }

    if lowered.startswith("compound_"):
        desc["mode"] = "Compounding"
    elif lowered.startswith("orb_"):
        desc["mode"] = "ATR/Stop backtest"
    else:
        desc["mode"] = "Backtest"

    # Universe: between '<prefix>_' and '_liquidity' (if present)
    m = re.match(r"^(?:compound|orb)_(.+?)(?:_liquidity|_atr|_long|_short|_both|$)", lowered)
    if m:
        desc["universe"] = _title_universe(m.group(1))

    # Side: trailing token
    for side in ("long", "short", "both"):
        if lowered.endswith(f"_{side}") or lowered == side:
            desc["side"] = side.upper()
            break

    # Liquidity cap: liquidity_1pct -> 0.01
    m = re.search(r"liquidity_(\d+)pct", lowered)
    if m:
        pct = float(m.group(1))
        desc["max_pct_volume"] = pct / 100.0

    # ATR: atr050 -> 0.50
    m = re.search(r"atr(\d{3})", lowered)
    if m:
        desc["min_atr"] = float(m.group(1)) / 100.0

    return desc


def _read_run_config(run_dir: Path) -> Optional[dict]:
    cfg_path = Path(run_dir) / "run_config.json"
    if not cfg_path.exists():
        return None
    import json

    return json.loads(cfg_path.read_text(encoding="utf-8"))


def run_display_name(run_name: str, run_dir: Optional[Path] = None) -> str:
    """Human label for reports.

    Default format is: Universe — Side — Top N
    ATR/Vol-cap are only appended when they differ from defaults (0.50 and 1%).
    """
    defaults = {"min_atr": 0.50, "max_pct_volume": 0.01}

    cfg = _read_run_config(run_dir) if run_dir is not None else None
    d = describe_run_name(run_name)

    universe = d.get("universe")
    side = d.get("side")
    top_n = None
    min_atr = d.get("min_atr")
    max_pct_volume = d.get("max_pct_volume")

    if cfg:
        universe_file = str(cfg.get("universe_file", ""))
        universe_file_lowered = universe_file.lower()
        if "universe_micro_small_unknown" in universe_file_lowered:
            universe = "Micro+Small+Unknown"
        elif "universe_micro_unknown" in universe_file_lowered:
            universe = "Micro+Unknown"
        elif "universe_unknown" in universe_file_lowered:
            universe = "Unknown"
        elif "universe_micro_small" in universe_file_lowered:
            universe = "Micro+Small"
        elif "universe_micro" in universe_file_lowered:
            universe = "Micro"
        elif "universe_small" in universe_file_lowered:
            universe = "Small"
        elif "universe_large" in universe_file_lowered:
            universe = "Large"
        elif "universe_all" in universe_file_lowered:
            universe = "All"

        if cfg.get("side"):
            side = str(cfg["side"]).upper()
        if cfg.get("top_n") is not None:
            top_n = int(cfg["top_n"])
        if cfg.get("min_atr") is not None:
            min_atr = float(cfg["min_atr"])
        if cfg.get("max_pct_volume") is not None:
            max_pct_volume = float(cfg["max_pct_volume"])

    bits = []
    if universe and universe != "-":
        bits.append(universe)
    if side and side != "-":
        bits.append(side.title())
    if top_n is not None:
        bits.append(f"Top {top_n}")

    # Only show these when they differ from defaults
    if min_atr is not None and abs(min_atr - defaults["min_atr"]) > 1e-9:
        bits.append(f"ATR≥{min_atr:.2f}")
    if max_pct_volume is not None and abs(max_pct_volume - defaults["max_pct_volume"]) > 1e-12:
        bits.append(f"Vol cap {max_pct_volume*100:.0f}%")

    return " — ".join(bits) if bits else run_name


def write_run_summary_md(run_dir: Path) -> Path:
    """Create/overwrite summary.md inside a run directory.

    This is intentionally derived only from saved artefacts, so it can be
    regenerated at any time.
    """
    run_dir = Path(run_dir)
    trades_path = run_dir / "simulated_trades.parquet"
    if not trades_path.exists():
        raise FileNotFoundError(f"Missing {trades_path}")

    summary = summarise_run(run_dir)
    df_trades = pd.read_parquet(trades_path)
    entered = df_trades[df_trades["exit_reason"] != "NO_ENTRY"].copy()

    capped_count = 0
    capped_pct = 0.0
    mean_cap_ratio: Optional[float] = None
    if not entered.empty and "is_capped" in entered.columns:
        capped_count = int(entered["is_capped"].fillna(False).sum())
        capped_pct = (capped_count / len(entered)) * 100
        if "cap_ratio" in entered.columns:
            cap_series = entered["cap_ratio"].astype(float)
            if not cap_series.empty:
                mean_cap_ratio = float(cap_series.mean())

    yearly_path = run_dir / "yearly_results.parquet"
    yearly_rows = []
    if yearly_path.exists():
        df_yearly = pd.read_parquet(yearly_path)
        for _, row in df_yearly.iterrows():
            yearly_rows.append(
                {
                    "year": int(row["year"]),
                    "start_equity": float(row["start_equity"]),
                    "end_equity": float(row["end_equity"]),
                    "year_return_pct": float(row["year_return_pct"]),
                }
            )

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append(f"# Run Summary — {summary.run_name}\n")
    lines.append(f"**Generated:** {generated}\n")
    lines.append(f"**Run Dir:** {run_dir.resolve()}\n")
    lines.append("\n")

    decoded = describe_run_name(summary.run_name)
    cfg = _read_run_config(run_dir) or {}
    cfg_top_n = cfg.get("top_n")
    cfg_min_atr = cfg.get("min_atr")
    cfg_max_pct_volume = cfg.get("max_pct_volume")

    lines.append("## Run Name (Decoded)\n")
    lines.append("| Part | Meaning |")
    lines.append("|---|---|")
    lines.append(f"| Folder name | `{decoded['raw']}` |")
    lines.append(f"| Display name | {run_display_name(summary.run_name, run_dir=run_dir)} |")
    lines.append(f"| Mode | {decoded['mode']} |")
    lines.append(f"| Universe | {decoded['universe']} |")
    lines.append(f"| Side | {decoded['side']} |")
    lines.append(f"| Top N | {cfg_top_n} |" if cfg_top_n is not None else "| Top N | - |")
    lines.append(
        f"| Min ATR | {float(cfg_min_atr):.2f} |" if cfg_min_atr is not None else (f"| Min ATR | {decoded['min_atr']:.2f} |" if decoded.get("min_atr") is not None else "| Min ATR | - |")
    )
    lines.append(
        f"| Liquidity cap | {float(cfg_max_pct_volume)*100:.0f}% of daily volume |"
        if cfg_max_pct_volume is not None
        else (
            f"| Liquidity cap | {decoded['max_pct_volume']*100:.0f}% of daily volume |"
            if decoded.get("max_pct_volume") is not None
            else "| Liquidity cap | - |"
        )
    )
    lines.append("\n")

    lines.append("## Headline Metrics\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Total trades (candidates) | {summary.total_trades:,} |")
    lines.append(f"| Entered trades | {summary.entered_trades:,} |")
    lines.append(f"| Win rate | {summary.win_rate_pct:.2f}% |")
    lines.append(f"| Profit factor | {summary.profit_factor:.3f} |")
    lines.append(f"| Total P&L (1x base) | {_fmt_money(summary.total_base_pnl)} |")
    lines.append(f"| Total P&L (5x leveraged) | {_fmt_money(summary.total_leveraged_pnl)} |")
    lines.append(f"| Final equity (compounding) | {_fmt_money(summary.final_equity)} |")
    lines.append("\n")

    lines.append("## Liquidity Cap Diagnostics\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Capped trades | {capped_count:,} |")
    lines.append(f"| Capped % (of entered) | {capped_pct:.2f}% |")
    lines.append(f"| Mean cap ratio | {mean_cap_ratio:.3f} |" if mean_cap_ratio is not None else "| Mean cap ratio | - |")
    lines.append("\n")

    if yearly_rows:
        lines.append("## Yearly Results (Compounding)\n")
        lines.append("| Year | Start | End | Return |")
        lines.append("|---:|---:|---:|---:|")
        for yr in yearly_rows:
            lines.append(
                f"| {yr['year']} | {_fmt_money(yr['start_equity'])} | {_fmt_money(yr['end_equity'])} | {yr['year_return_pct']:+.1f}% |"
            )
        lines.append("\n")

    lines.append("## Artefacts\n")
    for name in [
        "simulated_trades.parquet",
        "daily_performance.parquet",
        "equity_curve.parquet",
        "yearly_results.parquet",
    ]:
        if (run_dir / name).exists():
            lines.append(f"- `{name}`")

    out_path = run_dir / "summary.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
