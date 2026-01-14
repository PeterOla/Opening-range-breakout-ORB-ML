"""
Main orchestrator for ORB data pipeline.
Coordinates: fetch → enrich → validate → database sync
Single entry point for daily data updates.
"""
import logging
import json
import sys
import io
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import argparse
import pandas as pd

from .config import (
    LOGGING_CONFIG,
    FEATURES,
    get_all_symbols,
    DATA_RAW,
)
from .alpaca_fetch import AlpacaFetcher
from .enrichment import EnrichmentPipeline
from .validators import DailySyncValidator
from .universe_builder import UniverseBuilder
from .shares_sync import sync_missing_shares

# Configure logging
logger = logging.getLogger(__name__)

def setup_pipeline_logging():
    LOG_DIR = LOGGING_CONFIG["log_dir"]
    LOG_FORMAT = LOGGING_CONFIG["log_format"]
    LOG_LEVEL = logging.INFO

    # Setup root logger - ONLY if no handlers exist (prevents duplication when imported)
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        return

    root_logger.setLevel(LOG_LEVEL)

    # Console handler with UTF-8 encoding (fixes Windows cp1252 encoding errors)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(LOG_LEVEL)
    console_formatter = logging.Formatter(LOG_FORMAT)
    console_handler.setFormatter(console_formatter)
    
    # Force UTF-8 encoding for console output
    if hasattr(console_handler.stream, 'buffer'):
        console_handler.stream = io.TextIOWrapper(console_handler.stream.buffer, encoding='utf-8', errors='replace')
    root_logger.addHandler(console_handler)

    # File handler
    log_filename = f"orb_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(LOG_DIR / log_filename, encoding='utf-8')
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(console_formatter)
    root_logger.addHandler(file_handler)

if __name__ == "__main__":
    setup_pipeline_logging()


class DailySyncOrchestrator:
    """Orchestrates the complete daily data sync pipeline."""

    def __init__(self, symbols: Optional[list] = None, skip_fetch: bool = False, 
                 skip_enrich: bool = False):
        """
        Initialize orchestrator.
        
        Args:
            symbols: List of symbols to sync. If None, sync all.
            skip_fetch: Skip Alpaca fetch step
            skip_enrich: Skip enrichment step
        """
        self.symbols = symbols or get_all_symbols()
        
        # Bootstrap: If no local data, load from CSV
        if not self.symbols:
            csv_path = DATA_RAW / "nasdaq_nyse_tickers.csv"
            if csv_path.exists():
                logger.info(f"No local data found. Bootstrapping from {csv_path.name}")
                df = pd.read_csv(csv_path)
                self.symbols = df['symbol'].tolist()
        
        self.skip_fetch = skip_fetch
        self.skip_enrich = skip_enrich
        
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "total_symbols": len(self.symbols),
            "fetch": None,
            "enrich": None,
            "validation": None,
            "total_duration_seconds": 0,
            "status": "pending",
            "errors": [],
        }
        
        logger.info("="*80)
        logger.info("ORB DATA PIPELINE - DAILY SYNC")
        logger.info("="*80)
        logger.info(f"Symbols to sync: {len(self.symbols)}")
        logger.info(f"Skip fetch: {skip_fetch}, Skip enrich: {skip_enrich}")

    def run_fetch(self) -> bool:
        """Step 1: Fetch data from Alpaca."""
        if self.skip_fetch:
            logger.info("[SKIP] Skipping fetch (--skip-fetch)")
            return True
        
        try:
            logger.info("\n" + "="*80)
            logger.info("STEP 1: FETCH DATA FROM ALPACA")
            logger.info("="*80)
            
            start_time = datetime.now()
            fetcher = AlpacaFetcher()
            
            stats = fetcher.fetch_all_symbols(self.symbols)
            
            duration = (datetime.now() - start_time).total_seconds()
            self.results["fetch"] = {
                "status": "success",
                "duration_seconds": duration,
                "total_symbols": stats["total_symbols"],
                "successful": stats["successful"],
                "failed": stats["failed"],
                "skipped": stats["skipped"],
                "rows_daily": stats["total_rows_daily"],
                "rows_5min": stats["total_rows_5min"],
            }
            
            logger.info(f"\n[OK] Fetch complete ({duration:.1f}s)")
            logger.info(f"  Successful: {stats['successful']}")
            logger.info(f"  Failed: {stats['failed']}")
            logger.info(f"  Skipped: {stats['skipped']}")
            logger.info(f"  Daily rows: {stats['total_rows_daily']:,}")
            logger.info(f"  5-min rows: {stats['total_rows_5min']:,}")
            
            return True
        
        except Exception as e:
            logger.error(f"\n[ERROR] Fetch failed: {e}")
            self.results["fetch"] = {"status": "failed", "error": str(e)}
            self.results["errors"].append(f"Fetch: {e}")
            return False

    def run_enrich(self) -> bool:
        """Step 2: Enrich data with metrics and shares."""
        if self.skip_enrich:
            logger.info("[SKIP] Skipping enrichment (--skip-enrich)")
            return True
        
        try:
            logger.info("\n" + "="*80)
            logger.info("STEP 2A: SYNC SHARES DATA")
            logger.info("="*80)
            
            missing, fetched = sync_missing_shares(symbols=self.symbols)
            if missing > 0:
                logger.info(f"Missing shares: {missing} symbols")
                logger.info(f"Fetched: {fetched} symbols")
                if fetched == 0:
                    logger.warning("No new shares data fetched — enrichment will proceed with incomplete data")
            
            logger.info("\n" + "="*80)
            logger.info("STEP 2B: ENRICH DATA")
            logger.info("="*80)
            
            start_time = datetime.now()
            pipeline = EnrichmentPipeline()
            
            stats = pipeline.enrich_all_symbols(self.symbols)
            
            duration = (datetime.now() - start_time).total_seconds()
            self.results["enrich"] = {
                "status": "success",
                "duration_seconds": duration,
                "total_symbols": stats["total_symbols"],
                "successful": stats["successful"],
                "failed": stats["failed"],
                "rows_processed": stats["total_rows_processed"],
            }
            
            logger.info(f"\n[OK] Enrichment complete ({duration:.1f}s)")
            logger.info(f"  Successful: {stats['successful']}")
            logger.info(f"  Failed: {stats['failed']}")
            logger.info(f"  Rows processed: {stats['total_rows_processed']:,}")
            
            return True
        
        except Exception as e:
            logger.error(f"\n[ERROR] Enrichment failed: {e}")
            self.results["enrich"] = {"status": "failed", "error": str(e)}
            self.results["errors"].append(f"Enrich: {e}")
            return False

    def run_validation(self) -> bool:
        """Step 3: Validate data quality and completeness."""
        try:
            logger.info("\n" + "="*80)
            logger.info("STEP 3: VALIDATE DATA")
            logger.info("="*80)
            
            start_time = datetime.now()
            validator = DailySyncValidator()
            
            # Check freshness
            validator.check_data_freshness(self.symbols, lookback_days=14)
            
            # Check completeness
            validator.validate_fetch_completeness(self.symbols, expected_min_rows=1200)
            
            duration = (datetime.now() - start_time).total_seconds()
            validation_summary = validator.summary()
            
            self.results["validation"] = {
                "status": "passed" if validation_summary["passed"] else "failed",
                "duration_seconds": duration,
                "errors": validation_summary["errors"],
                "warnings": validation_summary["warnings"],
            }
            
            logger.info(f"\n[OK] Validation complete ({duration:.1f}s)")
            logger.info(f"  Errors: {len(validation_summary['errors'])}")
            logger.info(f"  Warnings: {len(validation_summary['warnings'])}")
            
            for warning in validation_summary['warnings']:
                logger.warning(f"  [WARN] {warning}")
            
            return validation_summary["passed"]
        
        except Exception as e:
            logger.error(f"\n[ERROR] Validation failed: {e}")
            self.results["validation"] = {"status": "failed", "error": str(e)}
            self.results["errors"].append(f"Validation: {e}")
            return False

    def run(self) -> Dict:
        """Execute the complete pipeline."""
        start_time = datetime.now()
        
        try:
            # Execute each step
            success = True
            success = self.run_fetch() and success
            success = self.run_enrich() and success
            success = self.run_validation() and success
            
            # Set overall status
            duration = (datetime.now() - start_time).total_seconds()
            self.results["total_duration_seconds"] = duration
            self.results["status"] = "success" if success else "failed"
            
            # Print summary
            logger.info("\n" + "="*80)
            logger.info("SUMMARY")
            logger.info("="*80)
            logger.info(f"Status: {self.results['status'].upper()}")
            logger.info(f"Total duration: {duration:.1f}s ({duration/60:.1f} minutes)")
            logger.info(f"Errors: {len(self.results['errors'])}")
            
            if self.results['errors']:
                for error in self.results['errors']:
                    logger.error(f"  - {error}")
            
            # Save results to JSON
            results_file = LOG_DIR / f"orb_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(results_file, 'w') as f:
                json.dump(self.results, f, indent=2)
            
            logger.info(f"\nResults saved to: {results_file}")
            logger.info("="*80 + "\n")
            
            return self.results
        
        except Exception as e:
            logger.error(f"\n✗ Pipeline failed: {e}")
            self.results["status"] = "failed"
            self.results["errors"].append(f"Pipeline: {e}")
            
            duration = (datetime.now() - start_time).total_seconds()
            self.results["total_duration_seconds"] = duration
            
            return self.results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="ORB Data Pipeline - Fetch, enrich, and sync market data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full sync for all symbols
  python daily_sync.py
  
  # Sync specific symbols
  python daily_sync.py --symbols AAPL MSFT TSLA
  
  # Skip expensive steps
  python daily_sync.py --skip-fetch --skip-db-sync
  
  # Enrich only
  python daily_sync.py --skip-fetch --skip-validation --skip-db-sync
        """
    )
    
    parser.add_argument(
        '--symbols',
        nargs='+',
        help='Symbols to sync (default: all)',
        default=None
    )
    
    parser.add_argument(
        '--skip-fetch',
        action='store_true',
        help='Skip Alpaca fetch step'
    )
    
    parser.add_argument(
        '--skip-enrich',
        action='store_true',
        help='Skip enrichment step'
    )
    
    parser.add_argument(
        '--build-universe',
        action='store_true',
        help='Also build NASDAQ+NYSE universe (fetch missing, enrich, validate)'
    )
    
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level'
    )
    
    args = parser.parse_args()
    
    # Adjust log level
    if args.log_level != 'INFO':
        root_logger.setLevel(getattr(logging, args.log_level))
        for handler in root_logger.handlers:
            handler.setLevel(getattr(logging, args.log_level))
    
    # Run orchestrator
    orchestrator = DailySyncOrchestrator(
        symbols=args.symbols,
        skip_fetch=args.skip_fetch,
        skip_enrich=args.skip_enrich,
    )
    
    results = orchestrator.run()
    
    # Optionally build universe after main sync
    if args.build_universe:
        logger.info("\n" + "="*80)
        logger.info("BUILDING NASDAQ+NYSE UNIVERSE...")
        logger.info("="*80)
        # builder.build_universe is synchronous
        builder = UniverseBuilder()
        universe_results = builder.build_universe(skip_fetch=False)
        results["universe"] = universe_results
        logger.info(f"Universe build complete: {universe_results['total_symbols']} symbols")
    
    # Exit with appropriate code
    sys.exit(0 if results["status"] == "success" else 1)


if __name__ == "__main__":
    main()
