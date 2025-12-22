"""Place a single stop-entry order (LONG or SHORT) for one symbol.

Purpose
- Minimal live execution test for: entry placement + protective stop wiring.

TradeZero notes
- Entry is submitted as STOP (Stop-MKT) at the provided entry level.
- Protective stop is best-effort:
  - immediate attempt after fill detection
  - and/or later attachment by the stop-watcher.

Usage (PowerShell)
- Preview:
  python scripts/test_one_way_entry.py --broker tradezero --symbol GIS --side LONG --entry 48.98 --stop 48.92 --shares 1

- Execute:
  python scripts/test_one_way_entry.py --broker tradezero --symbol GIS --side LONG --entry 48.98 --stop 48.92 --shares 1 --yes
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

from core.config import settings
from execution.order_executor import OrderExecutor


ET = ZoneInfo("America/New_York")


def _ensure_tradezero_logged_in(executor: Any) -> None:
    if bool(getattr(settings, "TRADEZERO_DRY_RUN", False)):
        return
    _ = executor._get_client()  # noqa: SLF001


def _best_effort_active_orders(executor: Any) -> int | None:
    try:
        client = getattr(executor, "client", None)
        if client is None:
            return None
        df = client.get_active_orders()
        if df is None or getattr(df, "empty", False):
            return 0
        return int(len(df))
    except Exception:
        return None


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Place a single stop-entry (LONG/SHORT) with stop-loss")
    p.add_argument("--broker", choices=["alpaca", "tradezero"], default=(getattr(settings, "EXECUTION_BROKER", "alpaca") or "alpaca").lower().strip())
    p.add_argument("--symbol", default="GIS")
    p.add_argument("--side", choices=["LONG", "SHORT"], required=True)
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--shares", type=int, default=1)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--post-sleep", type=float, default=2.0, help="Seconds to wait before post-check")
    args = p.parse_args(argv)

    symbol = (args.symbol or "").upper().strip()
    broker = (args.broker or "alpaca").lower().strip()
    side = (args.side or "LONG").upper().strip()

    print("========== ONE-WAY ENTRY TEST ==========")
    print(f"Time (ET): {datetime.now(ET).isoformat()}")
    print(f"Broker:   {broker}")
    print(f"Symbol:   {symbol}")
    print(f"Side:     {side}")
    print(f"Entry:    {args.entry}")
    print(f"Stop:     {args.stop}")
    print(f"Shares:   {args.shares}")
    print(f"Preview:  {not args.yes}")

    if broker == "tradezero":
        from execution.tradezero.executor import TradeZeroExecutor

        executor: Any = TradeZeroExecutor()
        _ensure_tradezero_logged_in(executor)
    else:
        executor = OrderExecutor()

    if hasattr(executor, "is_kill_switch_active") and executor.is_kill_switch_active():
        print("BLOCKED: Kill switch is active.")
        return 1

    pre_positions = executor.get_positions()
    print(f"Pre positions: {len(pre_positions)}")

    if not args.yes:
        print("PREVIEW ONLY: No order placed.")
        return 0

    res = executor.place_entry_order(
        symbol=symbol,
        side=side,
        shares=int(args.shares),
        entry_price=float(args.entry),
        stop_price=float(args.stop),
    )
    print(f"\nEntry submit result: {res}")

    # Quick post-check
    time.sleep(max(0.0, float(args.post_sleep)))
    post_positions = executor.get_positions()
    ao = _best_effort_active_orders(executor)

    print("\n-- Post-check (best-effort) --")
    print(f"Active orders count (if available): {ao}")
    print(f"Positions count: {len(post_positions)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
