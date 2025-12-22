"""Close all open orders and positions with a detailed audit.

This is intended for emergency/manual flattening *now*.

Usage (PowerShell):
  python scripts/close_all_trades_today.py --yes

Notes:
- Cancels all open orders first, then closes all open positions.
- Writes a JSON audit file under repo-root logs/.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from zoneinfo import ZoneInfo

from core.config import settings
from execution.order_executor import OrderExecutor


ET = ZoneInfo("America/New_York")


@dataclass
class Snapshot:
    timestamp_et: str
    kill_switch_active: bool
    account: dict[str, Any]
    open_orders: list[dict[str, Any]]
    positions: list[dict[str, Any]]


def _safe_get_account(executor: Any) -> dict[str, Any]:
    try:
        acct = executor.get_account()
        return acct if isinstance(acct, dict) else {"raw": str(acct)}
    except Exception as e:
        return {"error": str(e)}


def _safe_get_positions(executor: Any) -> list[dict[str, Any]]:
    try:
        positions = executor.get_positions()
        return positions if isinstance(positions, list) else []
    except Exception:
        return []


def _safe_get_open_orders(executor: Any) -> list[dict[str, Any]]:
    # Alpaca executor supports get_open_orders(). TradeZero executor does not.
    try:
        if hasattr(executor, "get_open_orders"):
            orders = executor.get_open_orders()
            return orders if isinstance(orders, list) else []
    except Exception:
        pass

    # TradeZero: best-effort conversion from client.get_active_orders() dataframe.
    try:
        client = getattr(executor, "client", None)
        if client is None:
            return []
        df = client.get_active_orders()
        if df is None or getattr(df, "empty", False):
            return []

        out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            out.append({k: (None if v != v else v) for k, v in dict(row).items()})  # NaN-safe
        return out
    except Exception:
        return []


def _snapshot(executor: Any) -> Snapshot:
    now = datetime.now(ET).isoformat()
    kill_switch_active = bool(getattr(executor, "is_kill_switch_active") and executor.is_kill_switch_active())

    return Snapshot(
        timestamp_et=now,
        kill_switch_active=kill_switch_active,
        account=_safe_get_account(executor),
        open_orders=_safe_get_open_orders(executor),
        positions=_safe_get_positions(executor),
    )


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    # .../prod/backend/scripts/<this file>
    return here.parents[4]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Close all open orders and positions with a detailed audit")
    parser.add_argument("--yes", action="store_true", help="Actually execute cancels/closes (otherwise preview only)")
    parser.add_argument(
        "--broker",
        choices=["alpaca", "tradezero"],
        default=(getattr(settings, "EXECUTION_BROKER", "alpaca") or "alpaca").lower().strip(),
        help="Which broker executor to use (default: settings.EXECUTION_BROKER)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed even if account/auth check fails (not recommended; usually indicates bad credentials)",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="Seconds to wait after closing before re-checking state",
    )
    args = parser.parse_args(argv)

    run_id = str(uuid4())
    now_et = datetime.now(ET)

    broker = (args.broker or "alpaca").lower().strip()
    dry_run = bool(getattr(settings, "TRADEZERO_DRY_RUN", False)) if broker == "tradezero" else False

    if broker == "tradezero" and not dry_run:
        tz_user = (getattr(settings, "TRADEZERO_USERNAME", "") or "").strip()
        tz_pass = (getattr(settings, "TRADEZERO_PASSWORD", "") or "").strip()
        if not tz_user or not tz_pass:
            print("ERROR: TradeZero live mode selected but TRADEZERO_USERNAME/PASSWORD not set.")
            print("Either set credentials in prod/backend/.env or run with TRADEZERO_DRY_RUN=true.")
            return 2

    if broker == "tradezero":
        from execution.tradezero.executor import TradeZeroExecutor

        executor = TradeZeroExecutor()

        # Critical: ensure we are logged in before auditing/closing.
        # Otherwise the TradeZero executor will report empty orders/positions.
        if not dry_run:
            try:
                _ = executor._get_client()  # noqa: SLF001
            except Exception as e:
                print(f"ERROR: Failed to initialise TradeZero client/login: {e}")
                return 2
    else:
        executor = OrderExecutor()

    audit: dict[str, Any] = {
        "run_id": run_id,
        "timestamp_et": now_et.isoformat(),
        "date_et": now_et.date().isoformat(),
        "broker": broker,
        "paper_mode": bool(getattr(settings, "PAPER_MODE", False)),
        "dry_run": dry_run,
        "kill_switch_file": getattr(settings, "KILL_SWITCH_FILE", None),
        "preview_only": not args.yes,
        "pre": asdict(_snapshot(executor)),
        "actions": [],
        "post": None,
        "summary": {},
    }

    # Detect obvious auth/permission issues early.
    account_err = str((audit["pre"].get("account") or {}).get("error") or "")
    auth_suspect = False
    if broker == "alpaca" and account_err:
        lowered = account_err.lower()
        auth_suspect = ("401" in lowered) or ("not authorized" in lowered) or ("unauthoriz" in lowered)

    pre_positions = audit["pre"]["positions"]
    pre_orders = audit["pre"]["open_orders"]

    print("========== CLOSE ALL (AUDIT) ==========")
    print(f"Run ID:        {run_id}")
    print(f"Time (ET):     {audit['timestamp_et']}")
    print(f"Broker:        {broker}")
    print(f"Dry-run:       {dry_run}")
    print(f"Kill switch:   {audit['pre']['kill_switch_active']}")
    if account_err:
        print(f"Account error: {account_err}")
    if auth_suspect:
        print("AUTH WARNING: Alpaca account call failed; order/position snapshots may be unreliable.")
    print(f"Open orders:   {len(pre_orders)}")
    print(f"Open positions:{len(pre_positions)}")

    if pre_positions:
        print("\n-- Positions (pre) --")
        for p in pre_positions:
            sym = p.get("symbol")
            qty = p.get("qty")
            side = p.get("side")
            extra = ""
            if "unrealized_pnl" in p:
                extra = f" | uPnL={p.get('unrealized_pnl')} | mv={p.get('market_value')}"
            print(f"{sym:>8} | {side:<5} | qty={qty}{extra}")

    if pre_orders:
        print("\n-- Open orders (pre) --")
        for o in pre_orders[:50]:
            # TradeZero has different fields; print best-effort.
            sym = o.get("symbol") or o.get("Symbol") or o.get("ticker")
            oid = o.get("id") or o.get("ref_number") or o.get("order_id")
            side = o.get("side") or o.get("Side")
            qty = o.get("qty") or o.get("Qty") or o.get("quantity")
            typ = o.get("type") or o.get("Type")
            st = o.get("status") or o.get("Status")
            print(f"{str(sym):>8} | {str(side):<6} | qty={qty} | type={typ} | status={st} | id={oid}")
        if len(pre_orders) > 50:
            print(f"... ({len(pre_orders) - 50} more orders omitted)")

    if not args.yes:
        audit["summary"] = {
            "status": "preview_only",
            "note": "Re-run with --yes to actually cancel orders and close positions.",
            "auth_suspect": auth_suspect,
        }
        _write_audit(audit)
        print("\nPREVIEW ONLY: No actions taken. Audit written.")
        return 0

    if auth_suspect and not args.force:
        audit["summary"] = {
            "status": "blocked",
            "reason": "alpaca_auth_error",
            "account_error": account_err,
            "hint": "Fix Alpaca credentials/permissions, or run with --broker tradezero. Use --force only if you understand the risk.",
        }
        _write_audit(audit)
        print("\nBLOCKED: Alpaca auth looks broken. No actions taken. Audit written.")
        return 1

    # Action 1: cancel all orders
    try:
        cancel_result = executor.cancel_all_orders()
    except Exception as e:
        cancel_result = {"status": "error", "reason": str(e)}
    audit["actions"].append({"action": "cancel_all_orders", "result": cancel_result})
    print(f"\nCancel all orders: {cancel_result}")

    # Action 2: close all positions
    try:
        close_result = executor.close_all_positions()
    except Exception as e:
        close_result = {"status": "error", "reason": str(e)}
    audit["actions"].append({"action": "close_all_positions", "result": close_result})
    print(f"Close all positions: {close_result}")

    # Re-check
    time.sleep(max(0.0, float(args.sleep_seconds)))
    post = asdict(_snapshot(executor))
    audit["post"] = post

    post_positions = post["positions"]
    post_orders = post["open_orders"]

    audit["summary"] = {
        "status": "completed",
        "pre_open_orders": len(pre_orders),
        "post_open_orders": len(post_orders),
        "pre_open_positions": len(pre_positions),
        "post_open_positions": len(post_positions),
        "all_flat": (len(post_positions) == 0),
        "auth_suspect": auth_suspect,
    }

    _write_audit(audit)

    print("\n-- Post-check --")
    print(f"Open orders:    {len(post_orders)}")
    print(f"Open positions: {len(post_positions)}")
    if post_positions:
        print("WARNING: Still have open positions. Check audit + broker UI.")
    else:
        print("All positions appear flat.")

    return 0


def _write_audit(audit: dict[str, Any]) -> None:
    root = _repo_root()
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    ts = audit.get("timestamp_et", "").replace(":", "-")
    fname = f"close_all_trades_audit_{audit.get('date_et','')}_{ts}_{audit.get('run_id','')}.json"
    path = logs_dir / fname

    with path.open("w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, default=str)

    print(f"\nAudit saved: {path}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
