"""
ORB Strategy Scanner Service.

Scans stock universe and ranks by Opening Range Breakout criteria:
- Price > $5
- 14-day avg volume > 1M shares
- ATR > $0.50
- RVOL >= 100% (relative volume)
- Top 20 by RVOL

Direction determined by opening range candle:
- Bullish (close > open): Long only
- Bearish (close < open): Short only
"""
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import pandas as pd

from services.universe import (
    fetch_tradeable_assets,
    fetch_snapshots_batch,
    fetch_daily_bars,
    fetch_5min_bars,
    compute_atr,
    compute_avg_volume,
)


# Trading hours (Eastern Time)
ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
OR_END = time(9, 35)


def get_opening_range(df: pd.DataFrame, target_date: Optional[datetime] = None) -> Optional[dict]:
    """
    Extract opening range (first 5-min bar 9:30-9:35 ET) from 5min bars.
    
    Returns dict with:
    - or_open, or_high, or_low, or_close, or_volume
    - or_direction: +1 (bullish), -1 (bearish), 0 (doji)
    """
    if df is None or df.empty:
        return None
    
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    
    # Convert to ET if needed
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert(ET)
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert(ET)
    
    df["date"] = df["timestamp"].dt.date
    df["time"] = df["timestamp"].dt.time
    
    # Get target date (today if not specified)
    if target_date is None:
        target_date = datetime.now(ET).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()
    
    # Filter to target date's 9:30 bar
    mask = (df["date"] == target_date) & (df["timestamp"].dt.hour == 9) & (df["timestamp"].dt.minute == 30)
    or_bar = df[mask]
    
    if or_bar.empty:
        return None
    
    bar = or_bar.iloc[0]
    
    # Determine direction
    if bar["close"] > bar["open"]:
        direction = 1  # Bullish - long only
    elif bar["close"] < bar["open"]:
        direction = -1  # Bearish - short only
    else:
        direction = 0  # Doji - no trade
    
    return {
        "or_open": bar["open"],
        "or_high": bar["high"],
        "or_low": bar["low"],
        "or_close": bar["close"],
        "or_volume": bar["volume"],
        "or_direction": direction,
        "or_timestamp": bar["timestamp"],
    }


def compute_rvol(current_or_volume: float, daily_df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Compute Relative Volume (RVOL) = current OR volume / avg OR volume (past N days).
    
    Note: For live trading, we compare current OR volume against historical avg.
    This requires historical OR volumes, which we approximate using daily volume / bars per day.
    
    Simplified: RVOL = today's first bar volume / avg(first bar volume over past N days)
    
    For production, you'd want to store historical OR volumes.
    """
    # Simplified approach: Use daily volume as proxy
    # In production, you'd track actual OR volumes
    if daily_df is None or len(daily_df) < period:
        return None
    
    avg_volume = compute_avg_volume(daily_df, period)
    if avg_volume is None or avg_volume == 0:
        return None
    
    # Approximate: OR typically has ~10% of daily volume in first 5 mins for active stocks
    # RVOL = (current_or_volume * 78) / avg_daily_volume
    # (78 five-min bars in a trading day: 6.5 hours * 12 bars/hour)
    approx_daily_from_or = current_or_volume * 78  # Extrapolate
    rvol = approx_daily_from_or / avg_volume
    
    return rvol


async def scan_universe(
    min_price: float = 5.0,
    max_price: float = 500.0,
    min_avg_volume: float = 1_000_000,
    min_atr: float = 0.50,
    min_rvol: float = 1.0,
    top_n: int = 20,
    atr_period: int = 14,
    volume_period: int = 14,
) -> list[dict]:
    """
    Full universe scan applying ORB criteria.
    
    Pipeline:
    1. Fetch all tradeable assets
    2. Get current snapshots (price filter)
    3. Fetch daily bars (ATR, avg volume filters)
    4. Fetch 5min bars (opening range calculation)
    5. Compute RVOL and rank
    6. Return top N by RVOL
    
    Returns list of candidate stocks with all metrics.
    """
    results = []
    
    # Step 1: Get all tradeable assets
    print("Fetching tradeable assets...")
    assets = await fetch_tradeable_assets()
    print(f"Found {len(assets)} tradeable assets")
    
    # Step 2: Get snapshots for price filtering
    all_symbols = [a["symbol"] for a in assets]
    print(f"Fetching snapshots for {len(all_symbols)} symbols...")
    snapshots = await fetch_snapshots_batch(all_symbols)
    print(f"Got snapshots for {len(snapshots)} symbols")
    
    # Quick price filter
    price_filtered = [
        sym for sym, snap in snapshots.items()
        if snap and min_price <= snap["price"] <= max_price
    ]
    print(f"Price filter ({min_price}-{max_price}): {len(price_filtered)} symbols")
    
    # Step 3: Fetch daily bars for remaining symbols
    print(f"Fetching daily bars for {len(price_filtered)} symbols...")
    daily_bars = await fetch_daily_bars(price_filtered, lookback_days=atr_period + 5)
    print(f"Got daily bars for {len(daily_bars)} symbols")
    
    # Step 4: Apply ATR and volume filters
    atr_vol_filtered = []
    for sym in price_filtered:
        if sym not in daily_bars:
            continue
        
        df = daily_bars[sym]
        atr = compute_atr(df, atr_period)
        avg_vol = compute_avg_volume(df, volume_period)
        
        if atr is None or avg_vol is None:
            continue
        
        if atr >= min_atr and avg_vol >= min_avg_volume:
            atr_vol_filtered.append({
                "symbol": sym,
                "price": snapshots[sym]["price"],
                "atr": atr,
                "avg_volume": avg_vol,
            })
    
    print(f"ATR/Volume filter: {len(atr_vol_filtered)} symbols")
    
    # Step 5: Fetch 5min bars for opening range
    filtered_symbols = [s["symbol"] for s in atr_vol_filtered]
    print(f"Fetching 5min bars for {len(filtered_symbols)} symbols (prefer local parquet when available)...")
    # For pre-market or testing, prefer local parquet (DuckDB) by using today's date
    target_dt = datetime.combine(datetime.now(ET).date(), time(0, 0))
    fivemin_bars = await fetch_5min_bars(filtered_symbols, lookback_days=1, target_date=target_dt)
    print(f"Got 5min bars for {len(fivemin_bars)} symbols")
    
    # Step 6: Calculate opening range and RVOL
    candidates = []
    for stock in atr_vol_filtered:
        sym = stock["symbol"]
        
        if sym not in fivemin_bars:
            continue
        
        or_data = get_opening_range(fivemin_bars[sym])
        if or_data is None:
            continue
        
        # Skip doji candles (no direction)
        if or_data["or_direction"] == 0:
            continue
        
        # Compute RVOL
        rvol = compute_rvol(or_data["or_volume"], daily_bars.get(sym), volume_period)
        if rvol is None or rvol < min_rvol:
            continue
        
        candidates.append({
            "symbol": sym,
            "price": stock["price"],
            "atr": round(stock["atr"], 2),
            "avg_volume": int(stock["avg_volume"]),
            "rvol": round(rvol, 2),
            "or_high": round(or_data["or_high"], 2),
            "or_low": round(or_data["or_low"], 2),
            "or_direction": or_data["or_direction"],
            "direction_label": "LONG" if or_data["or_direction"] == 1 else "SHORT",
            "or_volume": int(or_data["or_volume"]),
            "entry_level": round(or_data["or_high"], 2) if or_data["or_direction"] == 1 else round(or_data["or_low"], 2),
            "stop_distance": round(0.10 * stock["atr"], 2),  # 10% of ATR
        })
    
    print(f"RVOL filter (>= {min_rvol}): {len(candidates)} candidates")
    
    # Step 7: Rank by RVOL and take top N
    candidates.sort(key=lambda x: x["rvol"], reverse=True)
    top_candidates = candidates[:top_n]
    
    print(f"Top {top_n} by RVOL: {len(top_candidates)} stocks")
    
    return top_candidates


async def get_scanner_results(
    min_price: float = 5.0,
    max_price: float = 500.0,
    min_avg_volume: float = 1_000_000,
    min_atr: float = 0.50,
    min_rvol: float = 1.0,
    top_n: int = 20,
) -> dict:
    """
    Run scanner and return formatted results for API.
    """
    try:
        candidates = await scan_universe(
            min_price=min_price,
            max_price=max_price,
            min_avg_volume=min_avg_volume,
            min_atr=min_atr,
            min_rvol=min_rvol,
            top_n=top_n,
        )
        
        return {
            "status": "success",
            "timestamp": datetime.now(ET).isoformat(),
            "filters": {
                "min_price": min_price,
                "max_price": max_price,
                "min_avg_volume": min_avg_volume,
                "min_atr": min_atr,
                "min_rvol": min_rvol,
                "top_n": top_n,
            },
            "count": len(candidates),
            "candidates": candidates,
        }
    
    except Exception as e:
        return {
            "status": "error",
            "timestamp": datetime.now(ET).isoformat(),
            "error": str(e),
            "candidates": [],
        }
