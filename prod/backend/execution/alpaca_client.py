"""
Alpaca API client wrapper.
"""
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from core.config import settings

_client = None


def get_alpaca_client() -> TradingClient:
    """Get or create Alpaca trading client singleton."""
    global _client
    
    if _client is None:
        _client = TradingClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_API_SECRET,
            paper=settings.ALPACA_PAPER
        )
    
    return _client


def get_data_client() -> StockHistoricalDataClient:
    """Get Alpaca data client for historical data."""
    return StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_API_SECRET
    )
