"""One-shot ORB run (scan -> signals -> execute) using the configured broker.

Intended for manual local runs when moving from backtests to TradeZero.

Typical .env for your chosen configuration:
  EXECUTION_BROKER=tradezero
  ORB_UNIVERSE=micro_small
  ORB_STRATEGY=top5_both
  TRADEZERO_DRY_RUN=true

Usage (from prod/backend):
  python scripts/ORB/run_live_tradezero_once.py

Set TRADEZERO_DRY_RUN=false only when you're satisfied with behaviour.
"""

from __future__ import annotations

import argparse
import asyncio

from core.config import get_strategy_config
from execution.order_executor import get_executor
from services.orb_scanner import scan_orb_candidates
from services.signal_engine import (
    run_signal_generation,
    get_pending_signals,
    calculate_position_size,
)


async def main_async(scan: bool, generate: bool, execute: bool) -> int:
    strategy = get_strategy_config()
    executor = get_executor()

    if scan:
        await scan_orb_candidates(
            top_n=int(strategy["top_n"]),
            save_to_db=True,
        )

    account = executor.get_account()
    equity = float(account.get("equity", 100000))
    buying_power = float(account.get("buying_power", equity))

    if generate:
        await run_signal_generation(
            account_equity=equity,
            risk_per_trade_pct=float(strategy["risk_per_trade"]),
            max_positions=int(strategy["top_n"]),
            direction=strategy["direction"],
        )

    if execute:
        pending = get_pending_signals()
        if not pending:
            print("No pending signals to execute.")
            return 0

        max_position_value = buying_power / float(strategy["top_n"])

        submitted = 0
        failed = 0
        for signal in pending:
            shares = calculate_position_size(
                entry_price=float(signal["entry_price"]),
                stop_price=float(signal["stop_price"]),
                account_equity=equity,
                risk_per_trade_pct=float(strategy["risk_per_trade"]),
                max_position_value=max_position_value,
            )
            if shares <= 0:
                failed += 1
                continue

            res = executor.place_entry_order(
                symbol=signal["symbol"],
                side=signal["side"],
                shares=int(shares),
                entry_price=float(signal["entry_price"]),
                stop_price=float(signal["stop_price"]),
                signal_id=signal.get("id"),
            )
            if res.get("status") in {"submitted", "dry_run"}:
                submitted += 1
            else:
                failed += 1

        print(f"Done. submitted={submitted} failed={failed}")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-scan", action="store_true", help="Skip ORB scan step")
    ap.add_argument("--no-generate", action="store_true", help="Skip signal generation step")
    ap.add_argument("--no-execute", action="store_true", help="Skip execution step")
    args = ap.parse_args()

    return asyncio.run(
        main_async(
            scan=not args.no_scan,
            generate=not args.no_generate,
            execute=not args.no_execute,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
