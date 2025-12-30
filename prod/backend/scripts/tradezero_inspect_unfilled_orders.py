r"""Inspect active (unfilled) TradeZero orders and infer why they haven't filled.

What it does:
- Logs into TradeZero Web
- Reads the Active Orders table (including all visible columns)
- For each order, loads the symbol and pulls bid/ask/last
- Heuristically checks whether a STOP entry looks "triggered" or simply pending

Usage (from prod/backend):
    $env:TZ_DEBUG_DUMP="1"  # optional UI snapshots
    .venv\Scripts\python.exe scripts\tradezero_inspect_unfilled_orders.py

Notes:
- This can only diagnose what the UI exposes (e.g., status/message columns) + current quotes.
- If the order is a STOP and price hasn't crossed the trigger, it's expected to remain unfilled.
- Shorts may require locates/borrows; if the UI shows a message, it will be printed.
"""

from __future__ import annotations

import os
from typing import Any


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _pick(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        if k in d and d[k] is not None:
            txt = str(d[k]).strip()
            if txt:
                return txt
    # Try case-insensitive
    lowered = {str(k).lower(): k for k in d.keys()}
    for k in keys:
        kk = str(k).lower()
        if kk in lowered:
            txt = str(d[lowered[kk]]).strip()
            if txt:
                return txt
    return ""


def _to_float(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except Exception:
        return None


def main() -> int:
    os.environ.setdefault("TZ_DEBUG_DUMP", "1")

    from core.config import settings
    from execution.tradezero.client import TradeZero

    if not settings.TRADEZERO_USERNAME or not settings.TRADEZERO_PASSWORD:
        print("Missing TradeZero credentials. Set TRADEZERO_USERNAME and TRADEZERO_PASSWORD.")
        return 2

    print("Logging into TradeZero (headless=True) ...")
    tz = TradeZero(
        user_name=settings.TRADEZERO_USERNAME,
        password=settings.TRADEZERO_PASSWORD,
        headless=True,
        home_url=getattr(settings, "TRADEZERO_HOME_URL", None),
    )

    try:
        notes = tz.get_notifications(max_items=25)
        if notes is None:
            print("Recent notifications: unavailable")
        elif getattr(notes, "empty", True):
            print("Recent notifications: (none)")
        else:
            print("Recent notifications (up to 25):")
            try:
                print(notes.to_string(index=False))
            except Exception:
                print(notes)
            print("")

        df = tz.get_active_orders()
        if df is None or df.empty:
            print("No active (unfilled) orders.")

            if os.getenv("TZ_DEBUG_DUMP", "0").strip().lower() in {"1", "true", "yes"}:
                try:
                    tz._dump_ui_snapshot("active_orders_empty")
                except Exception:
                    pass

            inactive = tz.get_inactive_orders()
            if inactive is None:
                print("\nInactive orders: unavailable (scrape failed)")
            elif getattr(inactive, "empty", True):
                print("\nInactive orders: none visible")

                if os.getenv("TZ_DEBUG_DUMP", "0").strip().lower() in {"1", "true", "yes"}:
                    try:
                        tz._dump_ui_snapshot("inactive_orders_empty")
                    except Exception:
                        pass
            else:
                print(f"\nInactive orders snapshot (most recent {min(25, len(inactive))}):")
                try:
                    # Show tail so we see the latest outcomes.
                    print(inactive.tail(25).to_string(index=False))
                except Exception:
                    print(inactive)

            portfolio = tz.get_portfolio()
            if portfolio is not None:
                print("\nPortfolio snapshot:")
                try:
                    if getattr(portfolio, "empty", False):
                        print("(no open positions)")
                    else:
                        print(portfolio.to_string(index=False))
                except Exception:
                    print(portfolio)
            return 0

        orders = df.to_dict(orient="records")
        print(f"Found {len(orders)} active orders.\n")

        for i, row in enumerate(orders, start=1):
            symbol = str(_pick(row, "symbol")).upper().strip()
            ref = _pick(row, "ref_number", "ref", "id", "order-id")

            # Best-effort: discover useful UI columns
            side = _pick(row, "side", "action", "buy/sell", "b/s")
            order_type = _pick(row, "type", "order type")
            status = _pick(row, "status", "state")
            message = _pick(row, "message", "msg", "reason", "reject", "notes")
            stop_txt = _pick(row, "stop", "stop price", "stp")
            limit_txt = _pick(row, "limit", "limit price", "lmt", "price")
            qty_txt = _pick(row, "qty", "quantity", "shares")

            stop = _to_float(stop_txt)
            limit = _to_float(limit_txt)
            qty = _to_float(qty_txt)

            print("=" * 90)
            print(f"#{i} {symbol} | ref={ref}")
            if side or order_type or status:
                print(f"UI: side={side or '?'} | type={order_type or '?'} | status={status or '?'}")
            if qty is not None or stop is not None or limit is not None:
                print(f"UI: qty={qty if qty is not None else '?'} | stop={stop if stop is not None else '?'} | limit={limit if limit is not None else '?'}")
            if message:
                print(f"UI message: {message}")

            if not symbol:
                print("Cannot analyse (missing symbol in row).")
                continue

            md = tz.get_market_data(symbol)
            if md is None:
                print("Market data: unavailable (symbol load failed)")
                continue

            last = float(md.last)
            bid = float(md.bid)
            ask = float(md.ask)
            print(f"Quote: last={last:.4f} bid={bid:.4f} ask={ask:.4f}")

            # Heuristic trigger checks
            if stop is None:
                print("Inference: no stop price visible; cannot infer trigger condition.")
                continue

            side_n = _norm(side)
            type_n = _norm(order_type)

            if "stop" not in type_n and "stop" not in side_n:
                # Still may be stop, but UI header might differ.
                pass

            # Common interpretations:
            # - STOP BUY triggers when price >= stop
            # - STOP SHORT (sell stop) triggers when price <= stop (breakdown)
            # - STOP SELL triggers when price <= stop
            # - STOP COVER triggers when price >= stop
            triggered = None
            if "buy" in side_n and "cover" not in side_n:
                triggered = last >= stop
                direction = ">="
            elif "cover" in side_n:
                triggered = last >= stop
                direction = ">="
            elif "short" in side_n or "sell" in side_n:
                triggered = last <= stop
                direction = "<="
            else:
                triggered = None
                direction = "?"

            if triggered is None:
                print("Inference: cannot determine trigger direction from UI side.")
                continue

            if triggered:
                print(f"Inference: stop condition likely MET (last {last:.4f} {direction} stop {stop:.4f}).")
                print("If still unfilled, likely blocked (locate/borrow, halt, rejection, routing), or queued/partial.")
            else:
                print(f"Inference: stop condition NOT met yet (last {last:.4f} not {direction} stop {stop:.4f}).")
                print("This is the most common reason a STOP entry remains unfilled.")

        return 0
    finally:
        try:
            tz.exit()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
