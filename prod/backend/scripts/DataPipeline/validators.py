"""
Data validation module for ORB pipeline.
Validates schemas, continuity, and data quality before/after writes.
"""
import logging
from pathlib import Path
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from .config import (
    VALIDATION_CONFIG,
    ENRICHMENT_CONFIG,
    get_symbol_daily_path,
    get_symbol_5min_path,
)

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


class DataValidator:
    """Validates data schemas, continuity, and quality."""

    @staticmethod
    def validate_daily_schema(df: pd.DataFrame) -> bool:
        """Check daily data has required columns and types."""
        required = VALIDATION_CONFIG["required_daily_columns"]
        missing = [col for col in required if col not in df.columns]
        
        if missing:
            raise ValidationError(f"Daily data missing columns: {missing}")
        
        # Check types
        if not pd.api.types.is_object_dtype(df['date']) and not pd.api.types.is_datetime64_any_dtype(df['date']):
            raise ValidationError(f"Column 'date' should be object or datetime, got {df['date'].dtype}")
        
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
                raise ValidationError(f"Column '{col}' should be numeric, got {df[col].dtype}")
        
        return True

    @staticmethod
    def validate_5min_schema(df: pd.DataFrame) -> bool:
        """Check 5-min data has required columns and types."""
        required = VALIDATION_CONFIG["required_5min_columns"]
        missing = [col for col in required if col not in df.columns]
        
        if missing:
            raise ValidationError(f"5-min data missing columns: {missing}")
        
        # Check datetime is timezone-aware
        if not pd.api.types.is_datetime64_any_dtype(df['datetime']):
            raise ValidationError(f"Column 'datetime' should be datetime64, got {df['datetime'].dtype}")
        
        if df['datetime'].dt.tz is None:
            logger.warning("5-min datetime is timezone-naive, should be America/New_York")
        
        return True

    @staticmethod
    def validate_no_critical_nans(df: pd.DataFrame, critical_cols: List[str]) -> bool:
        """Ensure critical columns have no NaNs."""
        for col in critical_cols:
            if col in df.columns and df[col].isna().any():
                nan_count = df[col].isna().sum()
                raise ValidationError(f"Column '{col}' has {nan_count} NaN values")
        
        return True

    @staticmethod
    def validate_file_size(filepath: Path) -> bool:
        """Check file size is within bounds."""
        size = filepath.stat().st_size
        min_size = VALIDATION_CONFIG["min_file_size_bytes"]
        max_size = VALIDATION_CONFIG["max_file_size_bytes"]
        
        if size < min_size:
            raise ValidationError(f"File {filepath.name} too small: {size} bytes < {min_size}")
        
        if size > max_size:
            raise ValidationError(f"File {filepath.name} too large: {size} bytes > {max_size}")
        
        return True

    @staticmethod
    def validate_date_continuity(df: pd.DataFrame, symbol: str, allow_gaps: bool = True) -> Tuple[bool, List[str]]:
        """
        Check if dates are consecutive (no missing trading days).
        Returns (is_valid, list_of_warnings).
        """
        if 'date' not in df.columns:
            return True, []
        
        warnings = []
        dates = pd.to_datetime(df['date'])
        dates = dates.sort_values()
        
        # Check for duplicates
        dups = dates[dates.duplicated()].unique()
        if len(dups) > 0:
            warnings.append(f"Symbol {symbol} has duplicate dates: {dups}")
        
        if not allow_gaps:
            # Check for gaps (skip weekends/holidays if configured)
            date_diffs = dates.diff()
            gaps = date_diffs[date_diffs > timedelta(days=1)]
            
            if len(gaps) > 0:
                warnings.append(f"Symbol {symbol} has {len(gaps)} date gaps")
        
        return len(warnings) == 0, warnings

    @staticmethod
    def validate_numeric_ranges(df: pd.DataFrame, symbol: str) -> Tuple[bool, List[str]]:
        """Check numeric columns are in reasonable ranges."""
        warnings = []
        
        if 'close' in df.columns:
            if (df['close'] <= 0).any():
                warnings.append(f"Symbol {symbol} has non-positive close prices")
            
            # if (df['close'] < ENRICHMENT_CONFIG['min_price']).any():
            #     warnings.append(f"Symbol {symbol} has prices below ${ENRICHMENT_CONFIG['min_price']}")
        
        if 'volume' in df.columns:
            if (df['volume'] < 0).any():
                warnings.append(f"Symbol {symbol} has negative volumes")
        
        return len(warnings) == 0, warnings

    @staticmethod
    def post_write_check(filepath: Path, symbol: str, frequency: str = "daily") -> bool:
        """Validate after writing to parquet."""
        try:
            # Check file exists and has size
            if not filepath.exists():
                raise ValidationError(f"File {filepath} not created after write")
            
            DataValidator.validate_file_size(filepath)
            
            # Load and validate schema
            df = pd.read_parquet(filepath)
            
            if frequency == "daily":
                DataValidator.validate_daily_schema(df)
                DataValidator.validate_no_critical_nans(df, ['date', 'close', 'volume'])
            elif frequency == "5min":
                DataValidator.validate_5min_schema(df)
                DataValidator.validate_no_critical_nans(df, ['datetime', 'close', 'volume'])
            
            # Check numeric ranges
            is_valid, warnings = DataValidator.validate_numeric_ranges(df, symbol)
            for warning in warnings:
                logger.warning(f"[{symbol}] {warning}")
            
            # logger.debug(f"[{symbol}] OK Validation passed for {symbol}.parquet ({frequency})")
            return True
        
        except Exception as e:
            logger.error(f"[{symbol}] FAIL Validation failed for {symbol}.parquet: {e}")
            raise


class DailySyncValidator:
    """High-level validation for entire sync operation."""

    def __init__(self):
        self.errors = []
        self.warnings = []

    def add_error(self, msg: str):
        """Log error."""
        self.errors.append(msg)
        logger.error(f"[ERROR] {msg}")

    def add_warning(self, msg: str):
        """Log warning."""
        self.warnings.append(msg)
        logger.warning(f"[WARN] {msg}")

    def check_data_freshness(self, symbols: List[str], lookback_days: int = 14) -> bool:
        """Verify latest data is recent (not stale)."""
        cutoff_date = pd.Timestamp.now().date() - timedelta(days=lookback_days)
        stale_symbols = []
        
        for symbol in symbols:
            filepath = get_symbol_daily_path(symbol)
            if not filepath.exists():
                continue
            
            try:
                df = pd.read_parquet(filepath, columns=['date'])
                if len(df) == 0:
                    continue
                
                max_date = pd.to_datetime(df['date']).max().date()
                if max_date < cutoff_date:
                    stale_symbols.append((symbol, str(max_date)))
            except Exception as e:
                self.add_warning(f"Could not check freshness for {symbol}: {e}")
        
        if len(stale_symbols) > 0:
            self.add_warning(f"Stale data for {len(stale_symbols)} symbols (>14 days old)")
            return False
        
        return True

    def validate_fetch_completeness(self, symbols: List[str], expected_min_rows: int = 1200) -> bool:
        """Check all symbols have sufficient historical data."""
        incomplete = []
        
        for symbol in symbols:
            filepath = get_symbol_daily_path(symbol)
            if not filepath.exists():
                incomplete.append((symbol, "missing"))
                continue
            
            try:
                df = pd.read_parquet(filepath)
                if len(df) < expected_min_rows:
                    incomplete.append((symbol, f"{len(df)} rows < {expected_min_rows}"))
            except Exception as e:
                incomplete.append((symbol, str(e)))
        
        if len(incomplete) > 0:
            self.add_warning(f"{len(incomplete)} symbols have incomplete data")
            return False
        
        return True

    def summary(self) -> Dict:
        """Return validation summary."""
        return {
            "timestamp": datetime.now().isoformat(),
            "errors": self.errors,
            "warnings": self.warnings,
            "passed": len(self.errors) == 0,
        }


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    validator = DailySyncValidator()
    
    # Test with sample file
    test_file = Path("data/processed/daily/A.parquet")
    if test_file.exists():
        df = pd.read_parquet(test_file)
        DataValidator.validate_daily_schema(df)
        print(f"✓ Schema validation passed for {test_file.name}")
