"""End-to-end daily run: fetch data → scan → generate signals → execute top-5 one-by-one.

This is an operational helper for a new trading day.
It produces a markdown report under repo-root logs/ documenting:
- today's top-5 candidates (entry/stop)
- computed share sizing per candidate
- per-symbol TradeZero execution results and any UI snapshot folders

Usage (from prod/backend):
  python scripts/ORB/run_today_top5_one_by_one.py

Notes:
- Data sync uses the unified DataPipeline (incremental fetch) and defaults to the
  configured ORB universe when available.
- To avoid placing real orders, use --dry-run.
- Set TZ_DEBUG_DUMP=1 (recommended) to save HTML/CSS/screenshot snapshots.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")


@dataclass
class Candidate:
    symbol: str
    side: str
    rank: int | None
    entry_price: float
    stop_price: float
    rvol: float | None


@dataclass
class AttemptResult:
    symbol: str
    side: str
    shares: int
    entry_price: float
    stop_price: float
    status: str
    reason: str | None
    raw_output: str
    ui_snapshots: list[str]


def _repo_root() -> Path:
    # prod/backend/scripts/ORB/<this file> -> repo_root
    return Path(__file__).resolve().parents[4]


def _logs_dir() -> Path:
    p = _repo_root() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Fetch data, generate today top-5, execute one-by-one, and write a report")
    ap.add_argument("--no-sync", action="store_true", help="Skip DataPipeline data sync step")
    ap.add_argument(
        "--skip-fetch",
        action="store_true",
        help="During DataPipeline sync: skip the Alpaca fetch step (use existing local parquet).",
    )
    ap.add_argument(
        "--skip-enrich",
        action="store_true",
        help="During DataPipeline sync: skip enrichment (includes SEC shares sync).",
    )
    ap.add_argument("--no-flatten", action="store_true", help="Skip cancel+flatten preflight")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Force TRADEZERO_DRY_RUN=true for this run (recommended for debugging).",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Force execution even if today's signal already has an order_id.",
    )
    ap.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="How many candidates/signals to execute (default: 5)",
    )
    return ap.parse_args()


def _find_ui_snapshots(stdout: str) -> list[str]:
    # Matches the print from TradeZero client: "TZ DEBUG: UI snapshot saved to <path>"
    out: list[str] = []
    for line in (stdout or "").splitlines():
        m = re.search(r"TZ DEBUG: UI snapshot saved to\s+(.*)$", line.strip())
        if m:
            out.append(m.group(1).strip())
    return out


def _write_report(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _Tee(io.TextIOBase):
    def __init__(self, *streams: io.TextIOBase):
        self._streams = streams

    def write(self, s: str) -> int:  # type: ignore[override]
        written = 0
        for stream in self._streams:
            try:
                written = stream.write(s)
            except Exception:
                # Best-effort only.
                pass
        return written

    def flush(self) -> None:  # type: ignore[override]
        for stream in self._streams:
            try:
                stream.flush()
            except Exception:
                pass


def _sync_data_for_orb_universe(*, skip_fetch: bool, skip_enrich: bool) -> dict[str, Any]:
    """Run DataPipeline daily sync (incremental).

    Default behaviour:
    - If ORB_UNIVERSE is not 'all', sync only symbols in the configured universe parquet.
    - Otherwise, sync all symbols that already have local parquet files.
    """
    import sys

    # Make DataPipeline importable (package lives under prod/backend/scripts)
    sys.path.insert(0, str(Path("scripts").resolve()))

    from DataPipeline.daily_sync import DailySyncOrchestrator  # type: ignore[import-not-found]
    from services.orb_scanner import _allowed_symbols_from_universe_setting  # noqa: SLF001

    allowed = _allowed_symbols_from_universe_setting()
    symbols = sorted(list(allowed)) if allowed else None

    orchestrator = DailySyncOrchestrator(symbols=symbols, skip_fetch=bool(skip_fetch), skip_enrich=bool(skip_enrich))
    return orchestrator.run()


def _scan_and_generate(top_n: int, account_equity: float) -> dict[str, Any]:
    from core.config import get_strategy_config
    from services.orb_scanner import scan_orb_candidates
    from services.signal_engine import run_signal_generation

    strategy = get_strategy_config()

    async def _run() -> dict[str, Any]:
        scan_res = await scan_orb_candidates(top_n=int(top_n), save_to_db=True)
        gen_res = await run_signal_generation(
            account_equity=float(account_equity),
            risk_per_trade_pct=float(strategy["risk_per_trade"]),
            max_positions=int(top_n),
            direction=str(strategy["direction"]),
        )
        return {"scan": scan_res, "generate": gen_res}

    import asyncio

    return asyncio.run(_run())


def main() -> int:
    args = _parse_args()

    # Ensure env is set before importing Settings.
    if args.dry_run:
        os.environ["TRADEZERO_DRY_RUN"] = "true"

    # Suggested default when debugging UI automation.
    os.environ.setdefault("TZ_DEBUG_DUMP", "1")

    from core.config import get_strategy_config
    from execution.order_executor import get_executor
    from services.signal_engine import calculate_position_size
    from state.duckdb_store import DuckDBStateStore

    today = datetime.now(ET).date()
    strategy = get_strategy_config()

    report_path = _logs_dir() / f"orb_daily_run_{today.isoformat()}.md"
    print(f"[ORB Daily Runner] Report path: {report_path}")

    report_lines: list[str] = []
    report_lines.append(f"# Daily ORB Run Report ({today} ET)")
    report_lines.append("")
    report_lines.append("## Config")
    report_lines.append(f"- ORB_UNIVERSE: {os.getenv('ORB_UNIVERSE', '') or getattr(strategy, 'universe', '') or ''}")
    report_lines.append(f"- ORB_STRATEGY: {os.getenv('ORB_STRATEGY', '')}")
    report_lines.append(f"- EXECUTION_BROKER: {os.getenv('EXECUTION_BROKER', '')}")
    report_lines.append(f"- Dry-run: {bool(args.dry_run)}")
    report_lines.append(f"- TZ_DEBUG_DUMP: {os.getenv('TZ_DEBUG_DUMP', '')}")
    report_lines.append(f"- DataPipeline skip_fetch: {bool(args.skip_fetch)}")
    report_lines.append(f"- DataPipeline skip_enrich: {bool(args.skip_enrich)}")
    report_lines.append("")

    # Step 1: Fetch/sync market data
    if args.no_sync:
        report_lines.append("## Data Sync")
        report_lines.append("- Skipped (--no-sync)")
        report_lines.append("")
        sync_res: dict[str, Any] | None = None
    else:
        report_lines.append("## Data Sync")
        buf = io.StringIO()
        with contextlib.redirect_stdout(_Tee(sys.stdout, buf)):
            sync_res = _sync_data_for_orb_universe(skip_fetch=bool(args.skip_fetch), skip_enrich=bool(args.skip_enrich))
        sync_out = buf.getvalue()
        report_lines.append("- Ran DataPipeline daily sync (incremental)")
        report_lines.append(f"- Status: {sync_res.get('status') if isinstance(sync_res, dict) else 'unknown'}")
        report_lines.append("")
        if sync_out.strip():
            report_lines.append("<details><summary>Sync output</summary>")
            report_lines.append("")
            report_lines.append("```text")
            report_lines.extend(sync_out.strip().splitlines())
            report_lines.append("```")
            report_lines.append("</details>")
            report_lines.append("")

    # Step 2: scan + generate signals (no execute)
    report_lines.append("## Scan + Signal Generation")
    # Use the configured broker account for equity/buying power.
    executor = get_executor()
    account = executor.get_account()
    equity = float(account.get("equity", 0.0) or 0.0)

    scan_gen_out_buf = io.StringIO()
    with contextlib.redirect_stdout(_Tee(sys.stdout, scan_gen_out_buf)):
        scan_gen = _scan_and_generate(top_n=int(args.top_n), account_equity=equity)
    scan_gen_out = scan_gen_out_buf.getvalue()

    scan_status = (scan_gen.get("scan") or {}).get("status") if isinstance(scan_gen, dict) else None
    gen_status = (scan_gen.get("generate") or {}).get("status") if isinstance(scan_gen, dict) else None
    report_lines.append(f"- Scan status: {scan_status}")
    report_lines.append(f"- Generate status: {gen_status}")
    report_lines.append("")
    if scan_gen_out.strip():
        report_lines.append("<details><summary>Scan/generate output</summary>")
        report_lines.append("")
        report_lines.append("```text")
        report_lines.extend(scan_gen_out.strip().splitlines())
        report_lines.append("```")
        report_lines.append("</details>")
        report_lines.append("")

    # Step 3: pull today’s candidates from state store
    store = DuckDBStateStore()
    candidates_raw = store.get_todays_candidates(top_n=int(args.top_n), direction=str(strategy["direction"]))
    if not candidates_raw:
        report_lines.append("## Candidates")
        report_lines.append("- No candidates found in state store.")
        _write_report(report_path, report_lines)
        print(f"Report written: {report_path}")
        return 1

    # Step 4: preflight cancel+flatten (recommended)
    if args.no_flatten:
        report_lines.append("## Preflight Flatten")
        report_lines.append("- Skipped (--no-flatten)")
        report_lines.append("")
    else:
        report_lines.append("## Preflight Flatten")
        try:
            cancel_res = executor.cancel_all_orders()
        except Exception as e:
            cancel_res = {"status": "error", "error": str(e)}
        try:
            close_res = executor.close_all_positions()
        except Exception as e:
            close_res = {"status": "error", "error": str(e)}
        report_lines.append(f"- Cancel all orders: {cancel_res}")
        report_lines.append(f"- Close all positions: {close_res}")
        report_lines.append("")

    # Fetch account for sizing
    buying_power = float(account.get("buying_power", equity) or equity)
    max_position_value = buying_power / float(int(args.top_n))

    # Normalise candidate list
    candidates: list[Candidate] = []
    for row in candidates_raw:
        candidates.append(
            Candidate(
                symbol=str(row.get("symbol") or "").upper().strip(),
                side=("LONG" if int(row.get("direction") or 0) >= 0 else "SHORT"),
                rank=(int(row.get("rank")) if row.get("rank") is not None else None),
                entry_price=float(row.get("entry_price")),
                stop_price=float(row.get("stop_price")),
                rvol=(float(row.get("rvol")) if row.get("rvol") is not None else None),
            )
        )

    report_lines.append("## Candidates + Sizing")
    report_lines.append(f"- Equity: {equity:,.2f}")
    report_lines.append(f"- Buying Power: {buying_power:,.2f}")
    report_lines.append(f"- BP/Position (Top-{int(args.top_n)}): {max_position_value:,.2f}")
    report_lines.append("")
    report_lines.append("| Rank | Symbol | Side | Entry | Stop | Shares | RVOL |")
    report_lines.append("|---:|---|---|---:|---:|---:|---:|")

    shares_map: dict[str, int] = {}
    for c in candidates:
        shares = calculate_position_size(
            entry_price=float(c.entry_price),
            stop_price=float(c.stop_price),
            account_equity=equity,
            max_position_value=max_position_value,
            leverage=1.0,
        )
        shares_i = int(shares)
        shares_map[c.symbol] = shares_i
        rvol_txt = f"{c.rvol:.2f}" if c.rvol is not None else ""
        report_lines.append(
            f"| {c.rank if c.rank is not None else ''} | {c.symbol} | {c.side} | {c.entry_price:.2f} | {c.stop_price:.2f} | {shares_i} | {rvol_txt} |"
        )

    report_lines.append("")

    # Step 5: execute one-by-one and capture findings
    report_lines.append("## Execution Findings")

    attempts: list[AttemptResult] = []

    for c in candidates:
        print(f"[Execute] {c.symbol} {c.side} starting...")
        # Safety: honour order_id unless --force.
        sig = store.get_latest_signal_for_symbol(today, c.symbol)
        if sig and sig.get("order_id") and not args.force:
            out = f"Refusing: signal already has order_id={sig.get('order_id')} (use --force)"
            print(f"[Execute] {c.symbol} skipped: existing order_id")
            attempts.append(
                AttemptResult(
                    symbol=c.symbol,
                    side=c.side,
                    shares=shares_map[c.symbol],
                    entry_price=c.entry_price,
                    stop_price=c.stop_price,
                    status="skipped",
                    reason=out,
                    raw_output=out,
                    ui_snapshots=[],
                )
            )
            continue

        buf = io.StringIO()
        status = "unknown"
        reason: str | None = None
        res: dict[str, Any] | None = None
        with contextlib.redirect_stdout(_Tee(sys.stdout, buf)):
            try:
                res = executor.place_entry_order(
                    symbol=c.symbol,
                    side=str(c.side).upper().strip(),
                    shares=int(shares_map[c.symbol]),
                    entry_price=float(c.entry_price),
                    stop_price=float(c.stop_price),
                    signal_id=int(sig["id"]) if sig and sig.get("id") is not None else None,
                )
                if isinstance(res, dict):
                    status = str(res.get("status") or "").strip() or "unknown"
                    reason = res.get("reason") or res.get("rejection_reason")
            except Exception as e:
                status = "exception"
                reason = str(e)

        print(f"[Execute] {c.symbol} done: {status}{' (' + str(reason) + ')' if reason else ''}")

        raw = buf.getvalue()
        snaps = _find_ui_snapshots(raw)

        attempts.append(
            AttemptResult(
                symbol=c.symbol,
                side=c.side,
                shares=int(shares_map[c.symbol]),
                entry_price=float(c.entry_price),
                stop_price=float(c.stop_price),
                status=status,
                reason=reason,
                raw_output=raw,
                ui_snapshots=snaps,
            )
        )

    for a in attempts:
        report_lines.append(f"### {a.symbol} ({a.side})")
        report_lines.append(f"- Shares: {a.shares}")
        report_lines.append(f"- Entry/Stop: {a.entry_price:.2f} / {a.stop_price:.2f}")
        report_lines.append(f"- Result status: {a.status}")
        if a.reason:
            report_lines.append(f"- Reason: {a.reason}")
        if a.ui_snapshots:
            report_lines.append("- UI snapshots:")
            for p in a.ui_snapshots:
                report_lines.append(f"  - {p}")
        report_lines.append("")
        if (a.raw_output or "").strip():
            report_lines.append("```text")
            report_lines.extend((a.raw_output or "").strip().splitlines())
            report_lines.append("```")
            report_lines.append("")

    report_path = _logs_dir() / f"orb_daily_run_{today.isoformat()}_{datetime.now().strftime('%H%M%S')}.md"
    _write_report(report_path, report_lines)

    print(f"Report written: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
