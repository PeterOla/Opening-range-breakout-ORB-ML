"""Create two-way (LONG + SHORT) test entries for a single ticker.

Goal
- Place TWO entry orders for the same symbol:
  1) LONG entry (stop-entry) with protective stop-loss
  2) SHORT entry (stop-entry) with protective stop-loss

This is intended as an execution-path test (entry placement + stop placement logic).

Important safety notes
- Two opposing entry orders on the same symbol can both trigger. If you intend this
  as an OR test, you should manually cancel the opposite order once one side fills.
- For TradeZero, protective stops are placed via UI automation and may be attached
  after fill by the stop-watcher.

Usage (PowerShell)
- Preview (no orders placed):
  python scripts/test_two_way_entries.py --broker tradezero --symbol GIS \
    --long-entry 0 --long-stop 0 --short-entry 0 --short-stop 0

- Live (actually place orders):
  python scripts/test_two_way_entries.py --broker tradezero --symbol GIS \
    --long-entry <price> --long-stop <price> --short-entry <price> --short-stop <price> \
    --shares-long 1 --shares-short 1 --yes

You MUST supply sensible prices. The script will not guess current price.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

from core.config import settings
from execution.order_executor import OrderExecutor


ET = ZoneInfo("America/New_York")


def _ensure_tradezero_logged_in(executor: Any) -> None:
    if bool(getattr(settings, "TRADEZERO_DRY_RUN", False)):
        return
    # TradeZeroExecutor lazily initialises the client.
    _ = executor._get_client()  # noqa: SLF001


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Place two-way test entries (LONG + SHORT) for one symbol")
    p.add_argument("--broker", choices=["alpaca", "tradezero"], default=(getattr(settings, "EXECUTION_BROKER", "alpaca") or "alpaca").lower().strip())
    p.add_argument("--symbol", default="GIS")

    p.add_argument("--long-entry", type=float, required=True)
    p.add_argument("--long-stop", type=float, required=True)
    p.add_argument("--short-entry", type=float, required=True)
    p.add_argument("--short-stop", type=float, required=True)

    p.add_argument("--shares-long", type=int, default=1)
    p.add_argument("--shares-short", type=int, default=1)

    p.add_argument("--yes", action="store_true", help="Actually place orders")
    args = p.parse_args(argv)

    symbol = (args.symbol or "").upper().strip()
    broker = (args.broker or "alpaca").lower().strip()

    print("========== TWO-WAY ENTRY TEST ==========")
    print(f"Time (ET): {datetime.now(ET).isoformat()}")
    print(f"Broker:   {broker}")
    print(f"Symbol:   {symbol}")
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

    print("\n-- Orders to place --")
    print(f"LONG  stop-entry: {args.shares_long} @ {args.long_entry} | stop-loss {args.long_stop}")
    print(f"SHORT stop-entry: {args.shares_short} @ {args.short_entry} | stop-loss {args.short_stop}")

    if not args.yes:
        print("\nPREVIEW ONLY: No orders placed.")
        return 0

    # Place LONG
    long_res = executor.place_entry_order(
        symbol=symbol,
        side="LONG",
        shares=int(args.shares_long),
        entry_price=float(args.long_entry),
        stop_price=float(args.long_stop),
    )
    print(f"\nLONG result:  {long_res}")

    # Place SHORT
    short_res = executor.place_entry_order(
        symbol=symbol,
        side="SHORT",
        shares=int(args.shares_short),
        entry_price=float(args.short_entry),
        stop_price=float(args.short_stop),
    )
    print(f"SHORT result: {short_res}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
