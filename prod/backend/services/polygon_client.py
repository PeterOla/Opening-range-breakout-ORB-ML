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
        active: bool = True,
        ticker_type: str = "CS",
        exchanges: list[str] = None,
    ) -> list[dict]:
        """
        Get all stock tickers from Polygon with pagination.
        
        Args:
            active: True for active, False for delisted
            ticker_type: CS = Common Stock, ETF, etc.
            exchanges: Filter by exchange codes (XNYS, XNAS)
            
        Returns:
            List of ticker info dicts with: ticker, name, primary_exchange, type, active, cik
        """
        import asyncio
        
        if exchanges is None:
            exchanges = ["XNYS", "XNAS"]  # NYSE and NASDAQ
        
        url = f"{BASE_URL}/v3/reference/tickers"
        params = {
            "apiKey": self.api_key,
            "market": "stocks",
            "type": ticker_type,
            "active": str(active).lower(),
            "limit": 1000,
        }
        
        all_tickers = []
        page = 1
        
        async with httpx.AsyncClient() as client:
            while True:
                response = await client.get(url, params=params, timeout=60.0)
                response.raise_for_status()
                data = response.json()
                
                if data.get("results"):
                    # Filter by exchange
                    for ticker in data["results"]:
                        exchange = ticker.get("primary_exchange")
                        if exchange in exchanges:
                            all_tickers.append({
                                "ticker": ticker.get("ticker"),
                                "name": ticker.get("name"),
                                "primary_exchange": exchange,
                                "type": ticker.get("type"),
                                "active": active,
                                "currency": ticker.get("currency_name", "USD"),
                                "cik": ticker.get("cik"),
                                "delisted_utc": ticker.get("delisted_utc"),
                            })
                
                print(f"  Page {page}: fetched {len(data.get('results', []))} tickers, {len(all_tickers)} total NYSE/NASDAQ")
                
                # Check for next page
                next_url = data.get("next_url")
                if not next_url:
                    break
                
                url = next_url
                params = {"apiKey": self.api_key}
                page += 1
                
                # Rate limiting: be gentle
                await asyncio.sleep(0.5)
        
        return all_tickers
    
    async def get_all_us_stocks(self) -> list[dict]:
        """
        Get all US stocks (NYSE + NASDAQ), both active and delisted.
        For survivorship-bias-free data.
        
        Returns:
            Combined list of active and delisted tickers
        """
        print("Fetching ACTIVE stocks...")
        active = await self.get_stock_tickers(active=True)
        print(f"  ✓ {len(active)} active tickers")
        
        print("Fetching DELISTED stocks...")
        delisted = await self.get_stock_tickers(active=False)
        print(f"  ✓ {len(delisted)} delisted tickers")
        
        # Combine and dedupe by ticker symbol
        combined = {t["ticker"]: t for t in active}
        for t in delisted:
            if t["ticker"] not in combined:
                combined[t["ticker"]] = t
        
        print(f"  ✓ Total unique: {len(combined)} tickers")
        return list(combined.values())


# Singleton instance
_client = None


def get_polygon_client() -> PolygonClient:
    """Get or create Polygon client singleton."""
    global _client
    if _client is None:
        _client = PolygonClient()
    return _client
