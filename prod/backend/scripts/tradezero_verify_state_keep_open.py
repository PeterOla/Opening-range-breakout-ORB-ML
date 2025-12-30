"""TradeZero state verification (keeps browser open).

Purpose:
- Log into TradeZero Web
- Print current open orders and portfolio positions
- Keep the Chrome window open so you can inspect it manually

Usage (from prod/backend):
  $env:TZ_DEBUG_DUMP="1"  # optional
  .\.venv\Scripts\python.exe scripts\tradezero_verify_state_keep_open.py

Exit:
- Press Enter in the terminal to close the browser and exit.

Notes:
- Requires TRADEZERO_USERNAME and TRADEZERO_PASSWORD in your environment/.env
- Forces non-headless Chrome so you can see the UI.
"""

from __future__ import annotations

import os
import sys
from pprint import pprint


def _print_df(title: str, df) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

    if df is None:
        print("(none)")
        return

    try:
        if getattr(df, "empty", False):
            print("(empty)")
            return
        # Avoid huge spam: show up to 50 rows.
        with _pd_option_context():
            print(df.head(50).to_string(index=False))
            if len(df) > 50:
                print(f"... ({len(df) - 50} more rows)")
    except Exception:
        pprint(df)


def _pd_option_context():
    # Lazy import to avoid requiring pandas if something is off.
    import contextlib

    try:
        import pandas as pd

        return pd.option_context(
            "display.width",
            200,
            "display.max_columns",
            50,
            "display.max_colwidth",
            80,
        )
    except Exception:
        return contextlib.nullcontext()


def main() -> int:
    # Ensure any TradeZero UI debug snapshots go to repo-root logs/.
    os.environ.setdefault("TZ_DEBUG_DUMP", "1")

    from core.config import settings
    from execution.tradezero.client import TradeZero

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
        orders = tz.get_active_orders()
        portfolio = tz.get_portfolio()

        _print_df("Active Orders", orders)
        _print_df("Portfolio", portfolio)

        print("\nBrowser is left OPEN for you to inspect.")
        input("Press Enter to close the browser and exit... ")
    finally:
        # Only close when the user explicitly confirms.
        try:
            tz.exit()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
