"""
Massive (formerly Polygon.io) API client for historical market data.
Uses official massive Python library for reliability.
"""
import asyncio
import time
from datetime import datetime
from typing import Optional
from massive import RESTClient

from core.config import settings


class PolygonClient:
    """Client for Massive (Polygon.io) REST API using official library."""
    
    def __init__(self):
        self.api_key = settings.POLYGON_API_KEY
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY not configured")
        self._client = RESTClient(api_key=self.api_key)
    
    def get_daily_bars_sync(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict]:
        """
        Fetch daily OHLCV bars for a symbol (synchronous).
        """
        bars = []
        try:
            aggs = self._client.get_aggs(
                ticker=symbol,
                multiplier=1,
                timespan="day",
                from_=start_date.strftime('%Y-%m-%d'),
                to=end_date.strftime('%Y-%m-%d'),
                adjusted=True,
                sort="asc",
                limit=50000,
            )
            
            for bar in aggs:
                bars.append({
                    "timestamp": datetime.fromtimestamp(bar.timestamp / 1000),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "vwap": getattr(bar, 'vwap', None),
                })
        except Exception as e:
            print(f"Error fetching bars for {symbol}: {e}")
        
        return bars
    
    async def get_daily_bars(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict]:
        """Async wrapper for get_daily_bars_sync."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.get_daily_bars_sync, symbol, start_date, end_date
        )
    
    def get_grouped_daily_sync(self, date: datetime) -> dict[str, dict]:
        """
        Get all stock tickers' daily bars for a single date (synchronous).
        More efficient than per-symbol calls for universe-wide scans.
        """
        results = {}
        try:
            aggs = self._client.get_grouped_daily_aggs(
                date=date.strftime('%Y-%m-%d'),
                adjusted=True,
            )
            
            for bar in aggs:
                symbol = bar.ticker
                if symbol:
                    results[symbol] = {
                        "timestamp": datetime.fromtimestamp(bar.timestamp / 1000),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "vwap": getattr(bar, 'vwap', None),
                    }
        except Exception as e:
            print(f"Error fetching grouped daily for {date}: {e}")
        
        return results
    
    async def get_grouped_daily(self, date: datetime) -> dict[str, dict]:
        """Async wrapper for get_grouped_daily_sync."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_grouped_daily_sync, date)
    
    def get_previous_close_sync(self, symbol: str) -> Optional[dict]:
        """Get the previous day's close data for a symbol (synchronous)."""
        try:
            result = self._client.get_previous_close_agg(ticker=symbol, adjusted=True)
            if result:
                # PreviousCloseAgg is a single object, not a list
                return {
                    "timestamp": datetime.fromtimestamp(result.timestamp / 1000) if result.timestamp else None,
                    "open": result.open,
                    "high": result.high,
                    "low": result.low,
                    "close": result.close,
                    "volume": result.volume,
                    "vwap": getattr(result, 'vwap', None),
                }
        except Exception as e:
            print(f"Error fetching previous close for {symbol}: {e}")
        return None
    
    async def get_previous_close(self, symbol: str) -> Optional[dict]:
        """Async wrapper for get_previous_close_sync."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_previous_close_sync, symbol)
    
    def get_active_stock_tickers_sync(self) -> list[dict]:
        """
        Get all ACTIVE stock tickers from NYSE and NASDAQ.
        Uses official polygon library with proper pagination.
        
        Mirrors the logic from data/scripts/fetch_all_tickers.py
        
        Returns:
            List of ticker info dicts (~5,000-6,000 tickers)
        """
        all_tickers = []
        
        print("Fetching ACTIVE stocks (NYSE + NASDAQ)...")
        try:
            # The polygon library's list_tickers returns an iterator
            # that handles pagination internally
            response = self._client.list_tickers(
                market='stocks',
                type='CS',  # Common Stock only
                active=True,
                limit=1000,
            )
            
            page = 1
            page_count = 0
            
            for ticker in response:
                # Filter for NYSE (XNYS) and NASDAQ (XNAS) only
                exchange = getattr(ticker, 'primary_exchange', None)
                if exchange in ['XNYS', 'XNAS']:
                    all_tickers.append({
                        "ticker": ticker.ticker,
                        "name": getattr(ticker, 'name', None),
                        "primary_exchange": exchange,
                        "type": getattr(ticker, 'type', 'CS'),
                        "active": True,
                        "currency": getattr(ticker, 'currency_name', 'USD'),
                        "cik": getattr(ticker, 'cik', None),
                    })
                
                page_count += 1
                
                # Log progress every 1000 tickers processed
                if page_count >= 1000:
                    print(f"  Page {page}: +{page_count} processed, {len(all_tickers)} NYSE/NASDAQ")
                    page += 1
                    page_count = 0
                    time.sleep(0.2)  # Rate limiting
            
            # Log final page
            if page_count > 0:
                print(f"  Page {page}: +{page_count} processed, {len(all_tickers)} NYSE/NASDAQ")
            
            print(f"  ✓ Total active NYSE/NASDAQ: {len(all_tickers)} tickers")
            
        except Exception as e:
            print(f"  ✗ Error fetching tickers: {e}")
            import traceback
            traceback.print_exc()
        
        return all_tickers
    
    async def get_active_stock_tickers(self) -> list[dict]:
        """Async wrapper for get_active_stock_tickers_sync."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_active_stock_tickers_sync)


# Singleton instance
_client = None


def get_polygon_client() -> PolygonClient:
    """Get or create Polygon client singleton."""
    global _client
    if _client is None:
        _client = PolygonClient()
    return _client
