"""CLI: sync shares outstanding cache from SEC Company Facts.

This is the fast, focused way to build `data/raw/historical_shares.parquet` without
running the full Alpaca fetch/enrichment pipeline.

Usage (from prod/backend/scripts):
  python -m DataPipeline.run_shares_sync
  python -m DataPipeline.run_shares_sync --symbols AAPL MSFT TSLA

Notes:
- Requires `SEC_USER_AGENT` to be set (see services/sec_shares.py).
- Default behaviour uses NASDAQ+NYSE universe from data/raw/nasdaq_nyse_tickers.csv.
"""

from __future__ import annotations

import argparse
import logging

from .shares_sync import sync_missing_shares


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync shares outstanding from SEC (Company Facts)")
    ap.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Optional list of symbols to sync. If omitted, uses data/raw/nasdaq_nyse_tickers.csv",
    )
    ap.add_argument(
        "--skip-if-recent",
        action="store_true",
        default=False,
        help="Skip if historical_shares.parquet was modified in the last 24h (default: false)",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    missing, fetched = sync_missing_shares(symbols=args.symbols, skip_if_recent=args.skip_if_recent)
    logging.info(f"Shares sync done. Needed: {missing}, fetched: {fetched}")


if __name__ == "__main__":
    main()
