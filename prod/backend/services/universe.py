"""
Universe service: fetches tradeable stock universe from Alpaca.
Applies pre-filters before detailed scanning.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus

from core.config import settings


def get_trading_client() -> TradingClient:
    """Get Alpaca trading client."""
    return TradingClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_API_SECRET,
        paper=settings.ALPACA_PAPER
    )


def get_data_client() -> StockHistoricalDataClient:
    """Get Alpaca data client for historical data."""
    return StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_API_SECRET
    )


async def fetch_tradeable_assets(
    min_price: float = 5.0,
    max_price: float = 500.0,
) -> list[dict]:
    """
    Fetch all tradeable US equities from Alpaca.
    Returns basic asset info - detailed filtering done separately.
    """
    client = get_trading_client()
    
    # Get all active, tradeable US equities
    request = GetAssetsRequest(
        asset_class=AssetClass.US_EQUITY,
        status=AssetStatus.ACTIVE,
    )
    
    assets = client.get_all_assets(request)
    
    # Filter to only tradeable, non-OTC stocks
    tradeable = [
        {
            "symbol": a.symbol,
            "name": a.name,
            "exchange": a.exchange,
            "tradeable": a.tradable,
            "shortable": a.shortable,
            "fractionable": a.fractionable,
        }
        for a in assets
        if a.tradable and not a.symbol.isdigit() and "." not in a.symbol
    ]
    
    return tradeable


async def fetch_snapshots_batch(symbols: list[str]) -> dict:
    """
    Fetch latest snapshots for a batch of symbols.
    Returns dict of symbol -> snapshot data.
    """
    if not symbols:
        return {}
    
    client = get_data_client()
    
    # Alpaca limits snapshot requests - batch if needed
    batch_size = 100
    all_snapshots = {}
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            request = StockSnapshotRequest(symbol_or_symbols=batch, feed=DataFeed.IEX)
            snapshots = client.get_stock_snapshot(request)
            
            for sym, snap in snapshots.items():
                if snap and snap.latest_trade and snap.daily_bar:
                    all_snapshots[sym] = {
                        "symbol": sym,
                        "price": snap.latest_trade.price,
                        "volume": snap.daily_bar.volume,
                        "open": snap.daily_bar.open,
                        "high": snap.daily_bar.high,
                        "low": snap.daily_bar.low,
                        "close": snap.daily_bar.close,
                        "vwap": snap.daily_bar.vwap,
                    }
        except Exception as e:
            print(f"Error fetching snapshots for batch: {e}")
            continue
    
    return all_snapshots


async def fetch_daily_bars(
    symbols: list[str],
    lookback_days: int = 20,
) -> dict[str, pd.DataFrame]:
    """
    Fetch daily OHLCV bars for calculating ATR and avg volume.
    Returns dict of symbol -> DataFrame with daily bars.
    """
    if not symbols:
        return {}
    
    client = get_data_client()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days + 10)  # Extra buffer for weekends
    
    # Alpaca allows multi-symbol requests
    batch_size = 50
    all_bars = {}
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Day,
                start=start_date,
                end=end_date,
                feed=DataFeed.IEX,
            )
            bars = client.get_stock_bars(request)
            
            # Convert to dict of DataFrames
            for sym in batch:
                if sym in bars.data and bars.data[sym]:
                    df = pd.DataFrame([
                        {
                            "timestamp": b.timestamp,
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                            "vwap": b.vwap,
                        }
                        for b in bars.data[sym]
                    ])
                    if not df.empty:
                        all_bars[sym] = df
        except Exception as e:
            print(f"Error fetching daily bars for batch: {e}")
            continue
    
    return all_bars


async def fetch_5min_bars(
    symbols: list[str],
    lookback_days: int = 1,
) -> dict[str, pd.DataFrame]:
    """
    Fetch 5-minute OHLCV bars for opening range calculation.
    Returns dict of symbol -> DataFrame with 5min bars.
    """
    if not symbols:
        return {}
    
    client = get_data_client()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days + 1)
    
    batch_size = 50
    all_bars = {}
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame(5, "Min"),
                start=start_date,
                end=end_date,
                feed=DataFeed.IEX,
            )
            bars = client.get_stock_bars(request)
            
            for sym in batch:
                if sym in bars.data and bars.data[sym]:
                    df = pd.DataFrame([
                        {
                            "timestamp": b.timestamp,
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                        }
                        for b in bars.data[sym]
                    ])
                    if not df.empty:
                        all_bars[sym] = df
        except Exception as e:
            print(f"Error fetching 5min bars for batch: {e}")
            continue
    
    return all_bars


def compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Compute ATR from daily OHLCV DataFrame.
    Returns latest ATR value or None if insufficient data.
    """
    if df is None or len(df) < period:
        return None
    
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    # True Range calculation
    prev_close = df["close"].shift(1)
    high_low = df["high"] - df["low"]
    high_prev_close = (df["high"] - prev_close).abs()
    low_prev_close = (df["low"] - prev_close).abs()
    
    tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    
    latest_atr = atr.iloc[-1] if not atr.empty else None
    return latest_atr if pd.notna(latest_atr) else None


def compute_avg_volume(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Compute average daily volume.
    Returns latest avg volume or None if insufficient data.
    """
    if df is None or len(df) < period:
        return None
    
    df = df.sort_values("timestamp").reset_index(drop=True)
    avg_vol = df["volume"].rolling(window=period, min_periods=period).mean()
    
    latest = avg_vol.iloc[-1] if not avg_vol.empty else None
    return latest if pd.notna(latest) else None
