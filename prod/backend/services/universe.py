"""
Universe service: fetches tradeable stock universe from Alpaca.
Applies pre-filters before detailed scanning.
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from data_access.historical import query_symbol_range, list_available_symbols
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus

from core.config import settings

# Local cache directory for 5-min bars (only used in local dev)
INTRADAY_CACHE_DIR = Path(__file__).parent.parent.parent.parent / "data" / "intraday_cache"


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
            request = StockSnapshotRequest(symbol_or_symbols=batch, feed=DataFeed.SIP)
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
                feed=DataFeed.SIP,
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


def _get_cache_path(target_date: datetime) -> Path:
    """Get cache file path for a specific date."""
    date_str = target_date.strftime("%Y-%m-%d")
    return INTRADAY_CACHE_DIR / f"{date_str}.parquet"


def _load_cached_bars(target_date: datetime) -> Optional[dict[str, pd.DataFrame]]:
    """
    Load 5-min bars from local Parquet cache if available.
    Only loads bars for the specific target date.
    Returns None if cache doesn't exist or we're on cloud (no local storage).
    """
    cache_path = _get_cache_path(target_date)
    
    # Check if cache directory exists (local dev only)
    if not INTRADAY_CACHE_DIR.exists():
        return None
    
    if not cache_path.exists():
        return None
    
    try:
        df = pd.read_parquet(cache_path)
        
        # Convert back to dict of DataFrames per symbol
        result = {}
        for symbol in df["symbol"].unique():
            sym_df = df[df["symbol"] == symbol].drop(columns=["symbol"]).reset_index(drop=True)
            result[symbol] = sym_df
        
        print(f"[Cache] Loaded {len(result)} symbols from cache for {target_date.strftime('%Y-%m-%d')}")
        return result
    except Exception as e:
        print(f"[Cache] WARN: Failed to load cache: {e}")
        return None


def _save_bars_to_cache(bars: dict[str, pd.DataFrame], target_date: datetime) -> None:
    """
    Save 5-min bars to local Parquet cache.
    Only saves bars for the specific target date (filters out other days).
    """
    try:
        # Create cache directory if it doesn't exist
        INTRADAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        target_date_only = target_date.date() if hasattr(target_date, 'date') else target_date
        
        # Combine all DataFrames with symbol column, filtering to target date only
        dfs = []
        for symbol, df in bars.items():
            df_copy = df.copy()
            
            # Filter to only target date's bars
            if "timestamp" in df_copy.columns:
                df_copy["bar_date"] = pd.to_datetime(df_copy["timestamp"]).dt.date
                df_copy = df_copy[df_copy["bar_date"] == target_date_only]
                df_copy = df_copy.drop(columns=["bar_date"])
            
            if not df_copy.empty:
                df_copy["symbol"] = symbol
                dfs.append(df_copy)
        
        if not dfs:
            print(f"[Cache] WARN: No bars for target date {target_date_only}")
            return
        
        combined = pd.concat(dfs, ignore_index=True)
        cache_path = _get_cache_path(target_date)
        combined.to_parquet(cache_path, index=False)
        
        print(f"[Cache] Saved {len(dfs)} symbols to cache for {target_date.strftime('%Y-%m-%d')}")
    except Exception as e:
        # Silently fail on cloud (no local storage)
        print(f"[Cache] WARN: Could not save cache (expected on cloud): {e}")


async def fetch_5min_bars(
    symbols: list[str],
    lookback_days: int = 1,
    target_date: Optional[datetime] = None,
    progress_callback: Optional[callable] = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetch 5-minute OHLCV bars for opening range calculation.
    Returns dict of symbol -> DataFrame with 5min bars.
    
    Uses local Parquet cache when available (dev mode).
    Falls back to Alpaca API on cloud or cache miss.
    
    Args:
        symbols: List of ticker symbols
        lookback_days: Days to look back from target_date
        target_date: The date to fetch bars for. If None, uses now().
        progress_callback: Optional callback(fetched, total) for progress updates
    
    Note: Free Alpaca tier only allows SIP data with 15-minute delay.
    Querying today's data will fail unless you have a paid subscription.
    For historical backtesting, use dates at least 1 day in the past.
    """
    if not symbols:
        return {}
    
    # Try DuckDB/Parquet first when target_date is provided (local development).
    if target_date is not None:
        try:
            # Check which symbols we have parquet for to avoid expensive queries
            parquet_symbols = set(list_available_symbols(interval="5min"))
            matched = [s for s in symbols if s in parquet_symbols]
            parquet_bars = {}
            for s in matched:
                # Query full day and then filter to 5-min interval when needed
                df = query_symbol_range(
                    s,
                    start_ts=target_date.replace(hour=0, minute=0, second=0),
                    end_ts=target_date.replace(hour=23, minute=59, second=59),
                    interval="5min",
                )
                if not df.empty:
                    # normalise column name to timestamp expected by rest of code
                    if 'ts' in df.columns and 'timestamp' not in df.columns:
                        df = df.rename(columns={'ts': 'timestamp'})
                    parquet_bars[s] = df

            if parquet_bars:
                filtered = {s: parquet_bars[s] for s in symbols if s in parquet_bars}
                if len(filtered) >= max(1, int(len(symbols) * 0.9)):
                    print(f"[Parquet] Using parquet data ({len(filtered)}/{len(symbols)} symbols)")
                    return filtered
                else:
                    print(f"[Parquet] Partial hit ({len(filtered)}/{len(symbols)}), fetching rest from API")
                    # continue and fetch the rest from API later
        except Exception as e:
            print(f"[Parquet] Error attempting to load parquet data: {e}")
    
    client = get_data_client()
    
    # Use target_date if provided, otherwise use now
    if target_date is None:
        end_date = datetime.now()
    else:
        # Add 1 day to include the full target date
        end_date = target_date + timedelta(days=1)
    
    start_date = end_date - timedelta(days=lookback_days + 1)
    
    print(f"[fetch_5min_bars] Fetching {len(symbols)} symbols from {start_date} to {end_date}")
    
    batch_size = 50
    all_bars = {}
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                start=start_date,
                end=end_date,
                feed=DataFeed.SIP,  # SIP for full volume data (15-min delay on free tier)
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
            print(f"Error fetching 5min bars for batch {i//batch_size + 1}: {e}")
            continue
        
        # Progress callback for SSE streaming
        fetched_so_far = min(i + batch_size, len(symbols))
        if progress_callback:
            progress_callback(fetched_so_far, len(symbols))
        
        # Progress log every 10 batches
        if (i // batch_size + 1) % 10 == 0:
            print(f"   Fetched {fetched_so_far}/{len(symbols)} symbols...")
    
    print(f"[fetch_5min_bars] Got bars for {len(all_bars)} symbols")
    
    # Save to cache for future use (historical dates only)
    if target_date is not None and all_bars:
        _save_bars_to_cache(all_bars, target_date)
    
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
