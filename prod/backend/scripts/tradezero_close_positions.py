"""Close all open portfolio positions in TradeZero.

Behavior:
- Log into TradeZero (non-headless) using existing settings.
- Fetch portfolio via tz.get_portfolio(). For each position:
  - If qty > 0: try MARKET SELL qty. If rejected with R78 (market orders not allowed), fallback to LIMIT SELL at bid.
  - If qty < 0: try MARKET COVER qty. If rejected with R78, fallback to LIMIT COVER at ask.
- After each attempt, poll notifications and active orders and report status.

Usage:
  .\.venv\Scripts\python.exe prod\backend\scripts\tradezero_close_positions.py
"""
from __future__ import annotations

import os
import time
from typing import Optional

from core.config import settings
from execution.tradezero.client import TradeZero, Order


def _print_df(title: str, df) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    try:
        if df is None:
            print("(none)")
            return
        if getattr(df, "empty", False):
            print("(empty)")
            return
        print(df.to_string(index=False))
    except Exception:
        print(df)


def _recent_r78(notifs) -> bool:
    """Return True if any notification indicates R78 (market orders not allowed)."""
    if notifs is None:
        return False
    for _, row in notifs.iterrows():
        msg = (row.get("message") or "") + " " + (row.get("title") or "")
        if "r78" in msg.lower() or "market orders are not allowed" in msg.lower():
            return True
    return False


def _recent_r78_for_symbol(notifs, symbol: str) -> bool:
    """Return True if any notification indicates R78 for a given symbol."""
    if notifs is None:
        return False
    s = (symbol or "").upper()
    for _, row in notifs.iterrows():
        msg = ((row.get("message") or "") + " " + (row.get("title") or "")).lower()
        if ("r78" in msg or "market orders are not allowed" in msg) and s.lower() in msg:
            return True
    return False


def main() -> int:
    os.environ.setdefault("TZ_DEBUG_DUMP", "1")

    if not settings.TRADEZERO_USERNAME or not settings.TRADEZERO_PASSWORD:
        print("Missing TradeZero credentials. Set TRADEZERO_USERNAME and TRADEZERO_PASSWORD.")
        return 2

    print("Launching TradeZero (headless=False) ...")
    tz = TradeZero(
        user_name=settings.TRADEZERO_USERNAME,
        password=settings.TRADEZERO_PASSWORD,
        headless=False,
        home_url=getattr(settings, "TRADEZERO_HOME_URL", None),
    )

    try:
        portfolio = tz.get_portfolio()
        _print_df("Current Portfolio", portfolio)

        if portfolio is None or getattr(portfolio, "empty", False):
            print("No open positions to close.")
            return 0

        for _, row in portfolio.iterrows():
            symbol = (row.get("symbol") or "").strip().upper()
            qty = float(row.get("qty") or 0.0)
            if not symbol or qty == 0:
                continue
            qty_int = max(1, int(round(abs(qty))))

            print(f"\nAttempting to close {qty_int} {symbol} (qty={qty})")

            # Decide direction
            if qty > 0:
                # Long position -> SELL
                print(f"Placing MARKET SELL for {symbol} qty {qty_int}...")
                ok = tz.market_order(Order.SELL, symbol, qty_int)
                time.sleep(0.8)
                notifs = tz.get_notifications()
                if ok:
                    print(f"Market SELL submitted for {symbol}.")
                    # Even if submission returned True, the order can be immediately rejected (R78). Detect and fallback.
                    if _recent_r78_for_symbol(notifs, symbol):
                        print("Market order was rejected with R78; placing LIMIT SELL at bid...")
                        tz.load_symbol(symbol)
                        try:
                            price = tz.bid
                            print(f"Using bid price {price} for limit SELL")
                            ok2 = tz.limit_order(Order.SELL, symbol, qty_int, price)
                            if ok2:
                                print(f"LIMIT SELL placed for {symbol} @ {price}")
                            else:
                                print(f"LIMIT SELL failed for {symbol}")
                        except Exception as e:
                            print(f"Error fetching bid/placing limit sell: {e}")
                elif _recent_r78(notifs):
                    print("Market order rejected with R78; placing LIMIT SELL at bid...")
                    tz.load_symbol(symbol)
                    try:
                        price = tz.bid
                        print(f"Using bid price {price} for limit SELL")
                        ok2 = tz.limit_order(Order.SELL, symbol, qty_int, price)
                        if ok2:
                            print(f"LIMIT SELL placed for {symbol} @ {price}")
                        else:
                            print(f"LIMIT SELL failed for {symbol}")
                    except Exception as e:
                        print(f"Error fetching bid/placing limit sell: {e}")
                else:
                    print(f"Market SELL failed for {symbol}; see notifications or active orders for details.")

            else:
                # Short position -> COVER
                print(f"Placing MARKET COVER for {symbol} qty {qty_int}...")
                ok = tz.market_order(Order.COVER, symbol, qty_int)
                time.sleep(0.8)
                notifs = tz.get_notifications()
                if ok:
                    print(f"Market COVER submitted for {symbol}.")
                    if _recent_r78_for_symbol(notifs, symbol):
                        print("Market order was rejected with R78; placing LIMIT COVER at ask...")
                        tz.load_symbol(symbol)
                        try:
                            price = tz.ask
                            print(f"Using ask price {price} for limit COVER")
                            ok2 = tz.limit_order(Order.COVER, symbol, qty_int, price)
                            if ok2:
                                print(f"LIMIT COVER placed for {symbol} @ {price}")
                            else:
                                print(f"LIMIT COVER failed for {symbol}")
                        except Exception as e:
                            print(f"Error fetching ask/placing limit cover: {e}")
                elif _recent_r78(notifs):
                    print("Market order rejected with R78; placing LIMIT COVER at ask...")
                    tz.load_symbol(symbol)
                    try:
                        price = tz.ask
                        print(f"Using ask price {price} for limit COVER")
                        ok2 = tz.limit_order(Order.COVER, symbol, qty_int, price)
                        if ok2:
                            print(f"LIMIT COVER placed for {symbol} @ {price}")
                        else:
                            print(f"LIMIT COVER failed for {symbol}")
                    except Exception as e:
                        print(f"Error fetching ask/placing limit cover: {e}")
                else:
                    print(f"Market COVER failed for {symbol}; see notifications or active orders for details.")

            # Short pause then show current active orders and notifications
            time.sleep(0.8)
            print("\nRecent Notifications:")
            notifs = tz.get_notifications()
            _print_df("Notifications", notifs)
            print("\nActive Orders:")
            _print_df("Active Orders", tz.get_active_orders())

        # Final verification
        print("\nVerifying portfolio is closed...")
        time.sleep(1.0)
        final = tz.get_portfolio()
        _print_df("Final Portfolio", final)

    finally:
        try:
            tz.exit()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
