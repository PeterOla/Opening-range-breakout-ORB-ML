"""
Data enrichment for ORB backtest pipeline.
Adds shares_outstanding, computes TR/ATR14.
Self-contained - no dependencies on prod/backend.
"""
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from .config import (
    DAILY_DIR,
    SHARES_CONFIG,
    ENRICHMENT_CONFIG,
    FILTER_THRESHOLDS,
    get_symbol_daily_path,
)
from .validators import DataValidator

logger = logging.getLogger(__name__)


class SharesEnricher:
    """Adds shares_outstanding from historical shares data."""

    def __init__(self):
        """Load historical shares data."""
        shares_file = SHARES_CONFIG["raw_file"]
        if not shares_file.exists():
            logger.warning(f"Shares file not found: {shares_file}")
            self.df_shares = pd.DataFrame()
        else:
            self.df_shares = pd.read_parquet(shares_file)
            logger.info(f"Loaded {len(self.df_shares)} share records")

    def enrich_symbol(self, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        """Add shares_outstanding to daily data for a symbol."""
        if self.df_shares.empty:
            return df
        
        if 'shares_outstanding' in df.columns:
            if not df['shares_outstanding'].isnull().any():
                fill_pct = (1 - df['shares_outstanding'].isnull().sum() / len(df)) * 100
                if fill_pct > 80:
                    return df
            df = df.drop(columns=['shares_outstanding'])
        
        try:
            df_sym_shares = self.df_shares[self.df_shares['symbol'] == symbol].copy()
            if df_sym_shares.empty:
                logger.debug(f"[{symbol}] No shares data found, skipping enrichment")
                df['shares_outstanding'] = np.nan
                return df
            
            df['date_dt'] = pd.to_datetime(df['date']).dt.normalize().dt.tz_localize(None)
            df_sym_shares['date_dt'] = pd.to_datetime(df_sym_shares['date']).dt.normalize().dt.tz_localize(None)
            
            df = df.sort_values('date_dt')
            df_sym_shares = df_sym_shares.sort_values('date_dt')
            
            df = pd.merge_asof(df, df_sym_shares[['date_dt', 'shares_outstanding']], 
                              on='date_dt', direction='backward')
            
            if df['shares_outstanding'].isna().any():
                earliest_shares = df_sym_shares.iloc[0]['shares_outstanding']
                df['shares_outstanding'] = df['shares_outstanding'].fillna(earliest_shares)
            
            df = df.drop(columns=['date_dt'])
            
            logger.debug(f"[{symbol}] Enriched with shares data ({df['shares_outstanding'].notna().sum()} non-null)")
            return df
        
        except Exception as e:
            logger.error(f"[{symbol}] Failed to enrich shares: {e}")
            df['shares_outstanding'] = np.nan
            return df


class MetricsComputer:
    """Computes ATR, TR, filter flags."""

    @staticmethod
    def compute_true_range(df: pd.DataFrame) -> pd.Series:
        """Compute True Range (TR). TR = max(H-L, |H-PC|, |L-PC|)"""
        if len(df) < 2:
            return pd.Series(np.nan, index=df.index)
        
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        
        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        tr.iloc[0] = high.iloc[0] - low.iloc[0]
        
        return tr

    @staticmethod
    def compute_atr(tr: pd.Series, period: int = 14) -> pd.Series:
        """Compute Average True Range (ATR) using SMA."""
        return tr.rolling(window=period).mean()

    @staticmethod
    def compute_avg_volume(volume: pd.Series, period: int = 14) -> pd.Series:
        """Compute rolling average volume."""
        return volume.rolling(window=period).mean()

    @staticmethod
    def enrich_daily_data(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        """Compute enrichment metrics for daily data. Adds: tr, atr_14, avg_volume_14."""
        if df.empty:
            return df
        
        df = df.sort_values('date').reset_index(drop=True)
        df['tr'] = MetricsComputer.compute_true_range(df)
        df['atr_14'] = MetricsComputer.compute_atr(df['tr'], period=ENRICHMENT_CONFIG['atr_period'])
        df['avg_volume_14'] = MetricsComputer.compute_avg_volume(df['volume'], period=14)
        
        return df


class EnrichmentPipeline:
    """End-to-end enrichment pipeline."""

    def __init__(self):
        self.shares_enricher = SharesEnricher()
        self.metrics_computer = MetricsComputer()
        self.stats = {
            "total_symbols": 0,
            "successful": 0,
            "failed": 0,
            "total_rows_processed": 0,
        }

    def enrich_symbol(self, symbol: str) -> bool:
        """Enrich daily data for one symbol."""
        filepath = get_symbol_daily_path(symbol)
        
        if not filepath.exists():
            logger.debug(f"[{symbol}] Daily file not found, skipping")
            return True
        
        try:
            df = pd.read_parquet(filepath)
            original_rows = len(df)
            
            df = self.shares_enricher.enrich_symbol(symbol, df)
            df = self.metrics_computer.enrich_daily_data(symbol, df)
            
            DataValidator.validate_daily_schema(df)
            DataValidator.validate_no_critical_nans(df, ['date', 'close', 'volume'])
            
            df.to_parquet(filepath, index=False, compression='snappy')
            DataValidator.post_write_check(filepath, symbol, frequency='daily')
            
            logger.debug(f"[{symbol}] Enriched {original_rows} rows")
            self.stats["successful"] += 1
            self.stats["total_rows_processed"] += original_rows
            
            return True
        
        except Exception as e:
            logger.error(f"[{symbol}] Enrichment failed: {e}")
            self.stats["failed"] += 1
            return False

    def enrich_all_symbols(self, symbols: Optional[List[str]] = None) -> Dict:
        """Enrich all symbols."""
        if symbols is None:
            symbols = sorted([f.stem.upper() for f in DAILY_DIR.glob("*.parquet")])
        
        self.stats["total_symbols"] = len(symbols)
        
        logger.info(f"Starting enrichment for {len(symbols)} symbols")
        
        for i, symbol in enumerate(symbols):
            if (i + 1) % 100 == 0:
                logger.info(f"Progress: {i+1}/{len(symbols)} ({100*(i+1)/len(symbols):.1f}%)")
            
            self.enrich_symbol(symbol)
        
        logger.info(f"Enrichment complete: {self.stats['successful']} successful, "
                   f"{self.stats['failed']} failed")
        
        return self.stats


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )
    
    pipeline = EnrichmentPipeline()
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["AAPL", "MSFT"]
    
    stats = pipeline.enrich_all_symbols(symbols)
    print("\nEnrichment Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
