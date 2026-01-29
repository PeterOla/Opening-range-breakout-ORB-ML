"""
Data Sync Script for ORB Backtest Pipeline.
Fetches missing data from Alpaca and enriches with metrics.

Usage:
    # Sync all symbols (append new data)
    python sync_data.py
    
    # Sync specific symbols
    python sync_data.py --symbols AAPL MSFT TSLA
    
    # Force refetch from specific date
    python sync_data.py --start-date 2026-01-01
    
    # Skip fetch, only enrich existing
    python sync_data.py --skip-fetch
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from pipeline import (
    AlpacaFetcher,
    EnrichmentPipeline,
    get_all_symbols,
    DAILY_DIR,
    FIVE_MIN_DIR,
)


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def sync_data(
    symbols: list = None,
    start_date: str = None,
    skip_fetch: bool = False,
    skip_enrich: bool = False,
    max_workers: int = 5,
):
    """
    Main data sync pipeline.
    
    1. Fetch daily + 5min bars from Alpaca
    2. Enrich with ATR, TR, shares_outstanding
    """
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("ORB BACKTEST DATA SYNC")
    logger.info("=" * 80)
    
    # Determine symbols to sync
    if symbols is None or len(symbols) == 0:
        symbols = get_all_symbols()
        if len(symbols) == 0:
            logger.warning("No existing symbols found. Provide --symbols to fetch new data.")
            return
    
    logger.info(f"Syncing {len(symbols)} symbols")
    logger.info(f"  Daily Dir: {DAILY_DIR}")
    logger.info(f"  5min Dir: {FIVE_MIN_DIR}")
    
    # Step 1: Fetch from Alpaca
    if not skip_fetch:
        logger.info("\n[1/2] FETCHING DATA FROM ALPACA")
        try:
            fetcher = AlpacaFetcher()
            if start_date:
                # Override fetch range for all symbols
                fetcher.FETCH_CONFIG = {"start_date": start_date}
            fetch_stats = fetcher.fetch_all_symbols(symbols, max_workers=max_workers)
            logger.info(f"Fetch complete: {fetch_stats['successful']} successful")
        except Exception as e:
            logger.error(f"Fetch failed: {e}")
            return
    else:
        logger.info("\n[1/2] SKIPPING FETCH (--skip-fetch)")
    
    # Step 2: Enrich data
    if not skip_enrich:
        logger.info("\n[2/2] ENRICHING DATA")
        try:
            enricher = EnrichmentPipeline()
            enrich_stats = enricher.enrich_all_symbols(symbols)
            logger.info(f"Enrichment complete: {enrich_stats['successful']} successful")
        except Exception as e:
            logger.error(f"Enrichment failed: {e}")
            return
    else:
        logger.info("\n[2/2] SKIPPING ENRICH (--skip-enrich)")
    
    logger.info("\n" + "=" * 80)
    logger.info("DATA SYNC COMPLETE")
    logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Sync data for ORB backtest")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to sync")
    parser.add_argument("--start-date", type=str, help="Force start date (YYYY-MM-DD)")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip Alpaca fetch")
    parser.add_argument("--skip-enrich", action="store_true", help="Skip enrichment")
    parser.add_argument("--workers", type=int, default=5, help="Parallel workers")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    sync_data(
        symbols=args.symbols,
        start_date=args.start_date,
        skip_fetch=args.skip_fetch,
        skip_enrich=args.skip_enrich,
        max_workers=args.workers,
    )


if __name__ == "__main__":
    main()
