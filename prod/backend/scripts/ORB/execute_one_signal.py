"""Execute a single pending signal for today (TradeZero/Alpaca).

This is a debugging helper to place orders one-by-one.

Usage (from prod/backend):
  python scripts/ORB/execute_one_signal.py --symbol OMER --dry-run

Safety:
- Refuses to submit if today's signal already has an order_id (unless --force).
- Use --dry-run first to validate sizing and logging without placing orders.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute a single ORB signal (one-by-one debug).")
    parser.add_argument("--symbol", required=True, help="Ticker symbol, e.g. OMER")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force TRADEZERO_DRY_RUN=true for this run (recommended for debugging).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force execution even if today's signal already has an order_id.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    # Ensure env is set before importing Settings.
    if args.dry_run:
        os.environ["TRADEZERO_DRY_RUN"] = "true"

    from core.config import get_strategy_config
    from execution.order_executor import get_executor
    from services.signal_engine import calculate_position_size
    from state.duckdb_store import DuckDBStateStore

    symbol = str(args.symbol or "").upper().strip()
    if not symbol:
        print("ERROR: --symbol is required")
        return 2

    today = datetime.now(ET).date()
    store = DuckDBStateStore()
    sig = store.get_latest_signal_for_symbol(today, symbol)
    if not sig:
        print(f"No signal found for {symbol} on {today}.")
        return 1

    status = str(sig.get("status") or "").upper().strip()
    order_id = sig.get("order_id")
    if (not args.force) and order_id:
        print(
            "Refusing to submit: today's signal already has order_id="
            f"{order_id} (status={status}). Use --force to override."
        )
        return 1

    executor = get_executor()
    account = executor.get_account()
    equity = float(account.get("equity", 0.0) or 0.0)
    buying_power = float(account.get("buying_power", equity) or equity)

    strategy = get_strategy_config()
    top_n = int(strategy["top_n"])
    max_position_value = buying_power / float(top_n)

    entry_price = float(sig["entry_price"])
    stop_price = float(sig["stop_price"])

    shares = calculate_position_size(
        entry_price=entry_price,
        stop_price=stop_price,
        account_equity=equity,
        max_position_value=max_position_value,
        leverage=1.0,
    )

    print("\n=== EXECUTE ONE SIGNAL ===")
    print(f"Date (ET):      {today}")
    print(f"Symbol:         {symbol}")
    print(f"Side:           {sig['side']}")
    print(f"Entry / Stop:   {entry_price} / {stop_price}")
    print(f"Equity:         {equity:,.2f}")
    print(f"Buying Power:   {buying_power:,.2f}")
    print(f"Top-N:          {top_n}")
    print(f"BP/Position:    {max_position_value:,.2f}")
    print(f"Shares:         {shares}")
    print(f"Dry Run:        {bool(args.dry_run)}")

    if shares <= 0:
        print("ERROR: Calculated shares <= 0, refusing to submit.")
        return 1

    res = executor.place_entry_order(
        symbol=symbol,
        side=str(sig["side"]).upper().strip(),
        shares=int(shares),
        entry_price=entry_price,
        stop_price=stop_price,
        signal_id=int(sig["id"]),
    )

    print("\nResult:")
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
