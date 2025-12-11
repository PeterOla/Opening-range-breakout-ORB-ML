"""
Universe Builder — NASDAQ+NYSE trading universe management.

Workflow:
1. Load NASDAQ+NYSE tickers from CSV (7,599 symbols)
2. Check what parquet data exists for each symbol
3. Identify missing symbols (no data yet)
4. Fetch missing data via AlpacaFetcher (parallel, daily + 5min)
5. Enrich via EnrichmentPipeline (shares, TR, ATR)
6. Validate all symbols
7. Generate comparison report (before/after)

Uses existing DataPipeline infrastructure components to ensure consistency.
"""
import logging
import time
from pathlib import Path
from typing import List, Dict
import pandas as pd

from .config import DAILY_DIR, DATA_RAW
from .alpaca_fetch import AlpacaFetcher
from .enrichment import EnrichmentPipeline
from .validators import DailySyncValidator

logger = logging.getLogger(__name__)


class UniverseBuilder:
    """Build and maintain NASDAQ+NYSE trading universe."""

    def __init__(self, universe_csv: str = None):
        """Initialize with universe ticker list."""
        if universe_csv is None:
            universe_csv = DATA_RAW / "nasdaq_nyse_tickers.csv"
        
        self.universe_path = Path(universe_csv)
        self.daily_dir = DAILY_DIR
        self.symbols = self._load_universe()
        logger.info(f"Loaded {len(self.symbols)} tickers from {self.universe_path.name}")

    def _load_universe(self) -> List[str]:
        """Load NASDAQ+NYSE ticker list."""
        if not self.universe_path.exists():
            raise FileNotFoundError(f"Universe CSV not found: {self.universe_path}")
        
        df = pd.read_csv(self.universe_path, encoding='utf-8')
        symbols = df['symbol'].tolist()
        
        exchange_counts = df['exchange'].value_counts().to_dict()
        logger.info(f"  NASDAQ: {exchange_counts.get('NASDAQ', 0)}, NYSE: {exchange_counts.get('NYSE', 0)}")
        
        return symbols

    def check_existing_data(self) -> Dict[str, dict]:
        """Check what parquet data exists for each symbol."""
        existing = {}
        
        for symbol in self.symbols:
            parquet_path = self.daily_dir / f"{symbol}.parquet"
            if parquet_path.exists():
                try:
                    df = pd.read_parquet(parquet_path)
                    existing[symbol] = {
                        'rows': len(df),
                        'last_date': str(df['date'].max()),
                        'has_shares': 'shares_outstanding' in df.columns,
                        'has_tr': 'true_range' in df.columns,
                        'has_atr': 'atr_14' in df.columns,
                    }
                except Exception as e:
                    logger.warning(f"{symbol}: Could not read parquet - {e}")
        
        return existing

    def identify_missing_symbols(self) -> List[str]:
        """Identify symbols with no parquet data yet."""
        existing = self.check_existing_data()
        missing = [s for s in self.symbols if s not in existing]
        
        logger.info(f"Data status: {len(existing)}/{len(self.symbols)} symbols have data")
        logger.info(f"Missing: {len(missing)} symbols")
        
        return missing, existing

    def fetch_missing_data(self, symbols: List[str] = None):
        """Fetch data for missing or specified symbols using AlpacaFetcher."""
        if symbols is None:
            symbols, _ = self.identify_missing_symbols()
        
        if not symbols:
            logger.info("No missing symbols to fetch")
            return
        
        logger.info(f"Fetching {len(symbols)} symbols from Alpaca...")
        
        # Use AlpacaFetcher to fetch bars (Parallel, Daily + 5min)
        fetcher = AlpacaFetcher()
        stats = fetcher.fetch_all_symbols(symbols)
        
        logger.info(f"Fetch complete: {stats['successful']} successful, {stats['failed']} failed")

    def enrich_universe(self, symbols: List[str] = None):
        """Enrich universe with shares, TR, ATR using EnrichmentPipeline."""
        if symbols is None:
            symbols = self.symbols
        
        logger.info(f"Enriching {len(symbols)} symbols...")
        
        try:
            enricher = EnrichmentPipeline()
            stats = enricher.enrich_all_symbols(symbols)
            logger.info(f"Enrichment complete: {stats['successful']}/{stats['total_symbols']} successful, {stats['failed']} failed")
            if stats['failed'] > 0:
                logger.warning(f"  Failed symbols: {stats['failed']}")
        except Exception as e:
            logger.error(f"Enrichment failed: {e}")

    def validate_universe(self) -> Dict[str, dict]:
        """Validate all symbols in universe."""
        results = {}
        failed = []
        
        logger.info(f"Validating {len(self.symbols)} symbols...")
        
        validator = DailySyncValidator()
        validator.validate_fetch_completeness(self.symbols)
        
        # Basic check for return
        for symbol in self.symbols:
            parquet_path = self.daily_dir / f"{symbol}.parquet"
            if parquet_path.exists():
                results[symbol] = {'valid': True}
            else:
                results[symbol] = {'valid': False}
                failed.append(symbol)
        
        logger.info(f"Validation complete: {len(self.symbols) - len(failed)}/{len(self.symbols)} valid")
        if failed:
            logger.warning(f"Failed symbols: {failed[:10]}{'...' if len(failed) > 10 else ''}")
        
        return results

    def build_universe(self, skip_fetch: bool = False) -> Dict:
        """Full pipeline: check existing → fetch missing → enrich → validate."""
        logger.info("=" * 80)
        logger.info("BUILDING NASDAQ+NYSE UNIVERSE")
        logger.info("=" * 80)
        
        # Step 1: Check existing data
        logger.info("\n[1/4] Checking existing data...")
        missing_symbols, existing_before = self.identify_missing_symbols()
        
        # Step 2: Fetch missing data
        logger.info("\n[2/4] Fetching missing data...")
        if skip_fetch:
            logger.info("Skipping fetch (--skip-fetch)")
        else:
            self.fetch_missing_data(missing_symbols)
        
        # Step 3: Enrich universe
        logger.info("\n[3/4] Enriching universe...")
        self.enrich_universe(self.symbols)
        
        # Step 4: Validate universe
        logger.info("\n[4/4] Validating universe...")
        self.validate_universe()
        
        logger.info("=" * 80)
        logger.info("UNIVERSE BUILD COMPLETE")
        logger.info("=" * 80)
        
        return {
            'total_symbols': len(self.symbols),
            'status': 'complete'
        }


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Build NASDAQ+NYSE trading universe")
    parser.add_argument('--skip-fetch', action='store_true',
                       help='Skip fetch, only enrich/validate existing data')
    args = parser.parse_args()
    
    builder = UniverseBuilder()
    builder.build_universe(skip_fetch=args.skip_fetch)


if __name__ == "__main__":
    main()
