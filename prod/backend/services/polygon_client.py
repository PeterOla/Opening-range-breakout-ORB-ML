"""
Polygon.io API client for historical market data.
Used for daily bars (ATR, avg volume calculation).
"""
import httpx
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

from core.config import settings


BASE_URL = "https://api.polygon.io"


class PolygonClient:
    """Client for Polygon.io REST API."""
    
    def __init__(self):
        self.api_key = settings.POLYGON_API_KEY
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY not configured")
    
    async def get_daily_bars(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict]:
        """
        Fetch daily OHLCV bars for a symbol.
        
        Args:
            symbol: Stock ticker
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            
        Returns:
            List of bar dicts with: timestamp, open, high, low, close, volume, vwap
        """
        url = f"{BASE_URL}/v2/aggs/ticker/{symbol}/range/1/day/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
        params = {
            "apiKey": self.api_key,
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()
        
        bars = []
        if data.get("results"):
            for bar in data["results"]:
                bars.append({
                    "timestamp": datetime.fromtimestamp(bar["t"] / 1000),
                    "open": bar["o"],
                    "high": bar["h"],
                    "low": bar["l"],
                    "close": bar["c"],
                    "volume": bar["v"],
                    "vwap": bar.get("vw"),
                })
        
        return bars
    
    async def get_daily_bars_batch(
        self,
        symbols: list[str],
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, list[dict]]:
        """
        Fetch daily bars for multiple symbols.
        Rate-limited to respect Polygon Starter tier (5 calls/min).
        
        Returns:
            Dict of symbol -> list of bars
        """
        import asyncio
        
        results = {}
        
        for i, symbol in enumerate(symbols):
            try:
                bars = await self.get_daily_bars(symbol, start_date, end_date)
                results[symbol] = bars
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
                results[symbol] = []
            
            # Rate limiting: 5 calls/min = 1 call every 12 seconds
            # But let's be conservative: 1 call every 15 seconds
            if (i + 1) % 5 == 0:
                await asyncio.sleep(60)  # Wait 1 min after every 5 calls
        
        return results
    
    async def get_grouped_daily(self, date: datetime) -> dict[str, dict]:
        """
        Get all stock tickers' daily bars for a single date.
        More efficient than per-symbol calls for universe-wide scans.
        
        Note: Grouped daily endpoint gives all tickers in one call.
        """
        date_str = date.strftime("%Y-%m-%d")
        url = f"{BASE_URL}/v2/aggs/grouped/locale/us/market/stocks/{date_str}"
        params = {
            "apiKey": self.api_key,
            "adjusted": "true",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=60.0)
            response.raise_for_status()
            data = response.json()
        
        results = {}
        if data.get("results"):
            for bar in data["results"]:
                symbol = bar.get("T")
                if symbol:
                    results[symbol] = {
                        "timestamp": datetime.fromtimestamp(bar["t"] / 1000),
                        "open": bar["o"],
                        "high": bar["h"],
                        "low": bar["l"],
                        "close": bar["c"],
                        "volume": bar["v"],
                        "vwap": bar.get("vw"),
                    }
        
        return results
    
    async def get_previous_close(self, symbol: str) -> Optional[dict]:
        """Get the previous day's close data for a symbol."""
        url = f"{BASE_URL}/v2/aggs/ticker/{symbol}/prev"
        params = {"apiKey": self.api_key, "adjusted": "true"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()
        
        if data.get("results") and len(data["results"]) > 0:
            bar = data["results"][0]
            return {
                "timestamp": datetime.fromtimestamp(bar["t"] / 1000),
                "open": bar["o"],
                "high": bar["h"],
                "low": bar["l"],
                "close": bar["c"],
                "volume": bar["v"],
                "vwap": bar.get("vw"),
            }
        return None
    
    async def get_stock_tickers(
        self,
        min_price: float = 5.0,
        max_price: float = 500.0,
        market: str = "stocks",
        active: bool = True,
    ) -> list[dict]:
        """
        Get list of stock tickers matching criteria.
        
        Returns:
            List of ticker info dicts
        """
        url = f"{BASE_URL}/v3/reference/tickers"
        params = {
            "apiKey": self.api_key,
            "market": market,
            "active": str(active).lower(),
            "limit": 1000,
        }
        
        all_tickers = []
        
        async with httpx.AsyncClient() as client:
            while True:
                response = await client.get(url, params=params, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                
                if data.get("results"):
                    all_tickers.extend(data["results"])
                
                # Check for next page
                next_url = data.get("next_url")
                if not next_url:
                    break
                
                url = next_url
                params = {"apiKey": self.api_key}
        
        return all_tickers


# Singleton instance
_client = None


def get_polygon_client() -> PolygonClient:
    """Get or create Polygon client singleton."""
    global _client
    if _client is None:
        _client = PolygonClient()
    return _client
