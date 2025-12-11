"""
Alpaca data fetcher for ORB pipeline.
Fetches daily + 5-min bars for all symbols in parallel.
Premium Alpaca subscription = no rate limits.
"""
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from .config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    ALPACA_BASE_URL,
    FETCH_CONFIG,
    get_symbol_daily_path,
    get_symbol_5min_path,
)
from .validators import DataValidator

logger = logging.getLogger(__name__)


class AlpacaFetcher:
    """Fetches OHLCV data from Alpaca in parallel."""

    def __init__(self):
        """Initialize Alpaca client."""
        if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
        
        self.client = StockHistoricalDataClient(
            api_key=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
        )
        self.fetch_stats = {
            "total_symbols": 0,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "total_rows_daily": 0,
            "total_rows_5min": 0,
        }

    def get_last_available_date(self) -> str:
        """
        Get the last trading date available from Alpaca.
        Used to avoid fetching future data.
        """
        try:
            # Fetch latest bar for a liquid symbol
            request = StockLatestBarRequest(symbol_or_symbols=["SPY"])
            bars = self.client.get_stock_latest_bar(request)
            
            if "SPY" in bars:
                latest_ts = bars["SPY"].timestamp
                return latest_ts.strftime("%Y-%m-%d")
            else:
                # Fallback: use yesterday
                return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning(f"Could not determine last available date: {e}, using yesterday")
            return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    def get_fetch_range(self, symbol: str, start_date: Optional[str] = None) -> Tuple[str, str]:
        """
        Determine date range to fetch for a symbol.
        If parquet exists, start from last date in file.
        """
        end_date = self.get_last_available_date()
        
        # If parquet exists, start from last date in file
        daily_path = get_symbol_daily_path(symbol)
        if daily_path.exists():
            try:
                df = pd.read_parquet(daily_path, columns=['date'])
                if len(df) > 0:
                    last_date = pd.to_datetime(df['date']).max().date()
                    start_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
                    logger.debug(f"[{symbol}] Resuming from {start_date}")
            except Exception as e:
                logger.warning(f"[{symbol}] Could not determine last date: {e}, fetching full history")
        
        # Use config start_date if provided and no local data
        if start_date is None:
            start_date = FETCH_CONFIG["start_date"]
        
        return start_date, end_date

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch daily bars from Alpaca."""
        try:
            request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame.Day,
                start=start_date,
                end=end_date,
            )
            bars = self.client.get_stock_bars(request)
            
            if not bars.df.empty:
                df = bars.df.reset_index()
            else:
                logger.debug(f"[{symbol}] No data returned for {start_date} to {end_date}")
                return pd.DataFrame()
            
            # Standardize column names
            df.columns = df.columns.str.lower()
            df = df.rename(columns={
                'timestamp': 'date',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume',
            })
            
            # Convert date to naive UTC midnight (datetime64[ns])
            # Alpaca returns datetime64[ns, UTC]; normalize to midnight and remove timezone
            df['date'] = pd.to_datetime(df['date']).dt.normalize()
            
            # Filter to requested symbol only (multi-symbol requests will have multiple)
            df = df[df['symbol'] == symbol].copy()
            
            return df[['date', 'symbol', 'open', 'high', 'low', 'close', 'volume']]
        
        except Exception as e:
            logger.error(f"[{symbol}] Failed to fetch daily bars: {e}")
            return pd.DataFrame()

    def fetch_5min_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch 5-minute bars from Alpaca."""
        try:
            request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame(5, TimeFrameUnit.Minute),  # 5-minute bars
                start=start_date,
                end=end_date,
            )
            bars = self.client.get_stock_bars(request)
            
            if bars.df.empty:
                logger.debug(f"[{symbol}] No 5-min data returned for {start_date} to {end_date}")
                return pd.DataFrame()
            
            df = bars.df.reset_index()
            
            # Standardize column names
            df.columns = df.columns.str.lower()
            df = df.rename(columns={
                'timestamp': 'datetime',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume',
                'trade_count': 'trade_count',
                'vwap': 'vwap',
            })
            
            # Filter to requested symbol only
            df = df[df['symbol'] == symbol].copy()
            
            # Ensure datetime is timezone-aware (America/New_York)
            if df['datetime'].dt.tz is None:
                df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')
            else:
                df['datetime'] = df['datetime'].dt.tz_convert('America/New_York')
            
            # Drop rows with NaN datetime (malformed Alpaca data)
            df = df.dropna(subset=['datetime'])
            
            return df[['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'trade_count', 'vwap']]
        
        except Exception as e:
            logger.error(f"[{symbol}] Failed to fetch 5-min bars: {e}")
            return pd.DataFrame()

    def write_daily_bars(self, symbol: str, df_new: pd.DataFrame) -> bool:
        """Append or create daily bars parquet file."""
        if df_new.empty:
            return True
        
        filepath = get_symbol_daily_path(symbol)
        
        try:
            # Load existing data if exists
            if filepath.exists():
                df_existing = pd.read_parquet(filepath)
                # Deduplicate by date
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                df_combined = df_combined.drop_duplicates(subset=['date'], keep='last')
            else:
                df_combined = df_new
            
            # Ensure consistent datetime format: UTC timezone-aware
            # Do NOT use pd.to_datetime() on already-datetime columns as it strips timezone
            if df_combined['date'].dtype == 'object':
                # Only convert if stored as string
                df_combined['date'] = pd.to_datetime(df_combined['date'], utc=True).dt.normalize()
            elif not str(df_combined['date'].dtype).endswith('UTC]'):
                # If naive datetime, add UTC timezone
                df_combined['date'] = df_combined['date'].dt.tz_localize('UTC')
            
            # Sort by date
            df_combined = df_combined.sort_values('date').reset_index(drop=True)
            
            # Write parquet
            df_combined.to_parquet(filepath, index=False, compression='snappy')
            
            # Validate post-write
            DataValidator.post_write_check(filepath, symbol, frequency='daily')
            
            rows_written = len(df_new)
            logger.debug(f"[{symbol}] Wrote {rows_written} daily bars to {filepath.name}")
            
            self.fetch_stats["total_rows_daily"] += rows_written
            return True
        
        except Exception as e:
            logger.error(f"[{symbol}] Failed to write daily bars: {e}")
            return False

    def write_5min_bars(self, symbol: str, df_new: pd.DataFrame) -> bool:
        """Append or create 5-min bars parquet file."""
        if df_new.empty:
            return True
        
        filepath = get_symbol_5min_path(symbol)
        
        try:
            # Load existing data if exists
            if filepath.exists():
                df_existing = pd.read_parquet(filepath)
                # Deduplicate by datetime
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                df_combined = df_combined.drop_duplicates(subset=['datetime'], keep='last')
            else:
                df_combined = df_new
            
            # Drop rows with NaN datetime (malformed Alpaca data or corrupt parquets)
            df_combined = df_combined.dropna(subset=['datetime'])
            
            # Sort by datetime
            df_combined = df_combined.sort_values('datetime').reset_index(drop=True)
            
            # Write parquet
            df_combined.to_parquet(filepath, index=False, compression='snappy')
            
            # Validate post-write
            DataValidator.post_write_check(filepath, symbol, frequency='5min')
            
            rows_written = len(df_new)
            logger.debug(f"[{symbol}] Wrote {rows_written} 5-min bars to {filepath.name}")
            
            self.fetch_stats["total_rows_5min"] += rows_written
            return True
        
        except Exception as e:
            logger.error(f"[{symbol}] Failed to write 5-min bars: {e}")
            return False

    def fetch_and_write_symbol(self, symbol: str) -> bool:
        """Fetch and write both daily and 5-min bars for one symbol."""
        try:
            start_date, end_date = self.get_fetch_range(symbol)
            
            # Skip if start > end (already up-to-date)
            if start_date > end_date:
                logger.debug(f"[{symbol}] Already up-to-date, skipping")
                self.fetch_stats["skipped"] += 1
                return True
            
            # Fetch daily
            df_daily = self.fetch_daily_bars(symbol, start_date, end_date)
            if not df_daily.empty:
                self.write_daily_bars(symbol, df_daily)
            
            # Fetch 5-min
            df_5min = self.fetch_5min_bars(symbol, start_date, end_date)
            if not df_5min.empty:
                self.write_5min_bars(symbol, df_5min)
            
            self.fetch_stats["successful"] += 1
            return True
        
        except Exception as e:
            logger.error(f"[{symbol}] Fetch failed: {e}")
            self.fetch_stats["failed"] += 1
            return False

    def fetch_all_symbols(self, symbols: List[str], max_workers: Optional[int] = None) -> Dict:
        """
        Fetch all symbols in parallel.
        
        Args:
            symbols: List of symbols to fetch
            max_workers: Number of parallel threads (default: 5 for premium Alpaca)
        """
        if max_workers is None:
            max_workers = 5  # Premium Alpaca can handle 5 parallel requests
        
        self.fetch_stats["total_symbols"] = len(symbols)
        
        logger.info(f"Starting parallel fetch for {len(symbols)} symbols ({max_workers} workers)")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_and_write_symbol, symbol): symbol for symbol in symbols}
            
            for i, future in enumerate(as_completed(futures)):
                symbol = futures[future]
                try:
                    success = future.result()
                    if success:
                        pct = ((i + 1) / len(symbols)) * 100
                        logger.info(f"[{i+1}/{len(symbols)} ({pct:.1f}%)] OK {symbol}")
                except Exception as e:
                    logger.error(f"[{symbol}] Exception during fetch: {e}")
                    self.fetch_stats["failed"] += 1
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Fetch complete: {self.fetch_stats['successful']} successful, "
                   f"{self.fetch_stats['failed']} failed, {self.fetch_stats['skipped']} skipped")
        logger.info(f"Daily rows: {self.fetch_stats['total_rows_daily']:,} | "
                   f"5-min rows: {self.fetch_stats['total_rows_5min']:,}")
        logger.info(f"{'='*80}")
        
        return self.fetch_stats


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )
    
    fetcher = AlpacaFetcher()
    
    # Test with single symbol
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["AAPL", "MSFT"]
    stats = fetcher.fetch_all_symbols(symbols)
    
    print("\nFetch Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
