"""
ORB Scanner Service (Hybrid: Polygon DB + Alpaca Live).

1. Uses daily_bars DB (from Polygon) for ATR and avg_volume
2. Uses Alpaca for live 5-min opening range bar
3. Computes RVOL, applies filters, ranks top 20
"""
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import and_

from db.database import SessionLocal
from db.models import DailyBar, OpeningRange
from services.universe import get_data_client, fetch_5min_bars
from services.data_sync import get_universe_with_metrics


ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
OR_END = time(9, 35)


def get_opening_range_from_bars(df: pd.DataFrame, target_date: Optional[datetime] = None) -> Optional[dict]:
    """
    Extract opening range (first 5-min bar 9:30-9:35 ET) from 5min bars DataFrame.
    """
    if df is None or df.empty:
        return None
    
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    
    # Convert to ET
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert(ET)
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert(ET)
    
    df["date"] = df["timestamp"].dt.date
    
    # Get target date
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
        direction = 0  # Doji - skip
    
    return {
        "or_open": float(bar["open"]),
        "or_high": float(bar["high"]),
        "or_low": float(bar["low"]),
        "or_close": float(bar["close"]),
        "or_volume": float(bar["volume"]),
        "direction": direction,
        "timestamp": bar["timestamp"],
    }


def compute_rvol(or_volume: float, avg_volume: float) -> Optional[float]:
    """
    Compute Relative Volume (RVOL).
    
    RVOL = (OR_volume extrapolated to full day) / avg_daily_volume
    
    Approximation: OR (first 5 min) typically ~10% of daily volume for active stocks.
    We extrapolate: full_day_volume ≈ or_volume * 78 (78 five-min bars in trading day).
    """
    if avg_volume is None or avg_volume == 0:
        return None
    
    # Extrapolate OR volume to full day
    extrapolated_daily = or_volume * 78
    return extrapolated_daily / avg_volume


async def scan_orb_candidates(
    min_price: float = 5.0,
    min_atr: float = 0.50,
    min_avg_volume: float = 1_000_000,
    min_rvol: float = 1.0,
    top_n: int = 20,
    save_to_db: bool = True,
) -> dict:
    """
    Full ORB scan using hybrid data approach.
    
    Pipeline:
    1. Get universe from daily_bars DB (pre-filtered by price, ATR, avg_volume)
    2. Fetch today's 5-min OR bar from Alpaca for each candidate
    3. Compute RVOL, apply filter
    4. Rank by RVOL, take top N
    5. Optionally save to opening_ranges table
    
    Returns:
        Dict with scan results and candidates
    """
    db = SessionLocal()
    today = datetime.now(ET).date()
    
    try:
        # Step 1: Get universe with pre-computed metrics from DB
        print("Fetching universe from database...")
        universe = get_universe_with_metrics(
            min_price=min_price,
            min_atr=min_atr,
            min_avg_volume=min_avg_volume,
            db=db,
        )
        
        if not universe:
            return {
                "status": "error",
                "error": "No symbols in database pass base filters. Run data sync first.",
                "candidates": [],
            }
        
        symbols = [u["symbol"] for u in universe]
        print(f"Universe size after base filters: {len(symbols)} symbols")
        
        # Create lookup for metrics
        metrics_lookup = {u["symbol"]: u for u in universe}
        
        # Step 2: Fetch today's 5-min bars from Alpaca
        print(f"Fetching 5-min bars from Alpaca for {len(symbols)} symbols...")
        fivemin_bars = await fetch_5min_bars(symbols, lookback_days=1)
        print(f"Got 5-min bars for {len(fivemin_bars)} symbols")
        
        # Step 3 & 4: Extract OR, compute RVOL, filter
        candidates = []
        
        for symbol in symbols:
            if symbol not in fivemin_bars:
                continue
            
            or_data = get_opening_range_from_bars(fivemin_bars[symbol], today)
            if or_data is None:
                continue
            
            # Skip doji candles
            if or_data["direction"] == 0:
                continue
            
            metrics = metrics_lookup[symbol]
            
            # Compute RVOL
            rvol = compute_rvol(or_data["or_volume"], metrics["avg_volume_14"])
            if rvol is None or rvol < min_rvol:
                continue
            
            # Calculate entry and stop
            atr = metrics["atr_14"]
            if or_data["direction"] == 1:  # Long
                entry_price = or_data["or_high"]
                stop_price = entry_price - (0.10 * atr)
            else:  # Short
                entry_price = or_data["or_low"]
                stop_price = entry_price + (0.10 * atr)
            
            candidates.append({
                "symbol": symbol,
                "price": metrics["close"],
                "atr": round(atr, 2),
                "avg_volume": int(metrics["avg_volume_14"]),
                "rvol": round(rvol, 2),
                "or_high": round(or_data["or_high"], 2),
                "or_low": round(or_data["or_low"], 2),
                "or_open": round(or_data["or_open"], 2),
                "or_close": round(or_data["or_close"], 2),
                "or_volume": int(or_data["or_volume"]),
                "direction": or_data["direction"],
                "direction_label": "LONG" if or_data["direction"] == 1 else "SHORT",
                "entry_price": round(entry_price, 2),
                "stop_price": round(stop_price, 2),
                "stop_distance": round(0.10 * atr, 2),
            })
        
        print(f"Candidates after RVOL filter: {len(candidates)}")
        
        # Step 5: Rank by RVOL and take top N
        candidates.sort(key=lambda x: x["rvol"], reverse=True)
        
        # Assign ranks
        for i, c in enumerate(candidates):
            c["rank"] = i + 1
        
        top_candidates = candidates[:top_n]
        
        # Step 6: Save to database if requested
        if save_to_db and top_candidates:
            for c in candidates:  # Save all candidates, not just top N
                or_record = OpeningRange(
                    symbol=c["symbol"],
                    date=today,
                    or_open=c["or_open"],
                    or_high=c["or_high"],
                    or_low=c["or_low"],
                    or_close=c["or_close"],
                    or_volume=c["or_volume"],
                    direction=c["direction"],
                    rvol=c["rvol"],
                    atr=c["atr"],
                    avg_volume=c["avg_volume"],
                    passed_filters=c["rank"] <= top_n,
                    rank=c["rank"] if c["rank"] <= top_n else None,
                    entry_price=c["entry_price"],
                    stop_price=c["stop_price"],
                    signal_generated=False,
                    order_placed=False,
                )
                db.add(or_record)
            
            db.commit()
            print(f"Saved {len(candidates)} candidates to opening_ranges table")
        
        return {
            "status": "success",
            "timestamp": datetime.now(ET).isoformat(),
            "date": str(today),
            "filters": {
                "min_price": min_price,
                "min_atr": min_atr,
                "min_avg_volume": min_avg_volume,
                "min_rvol": min_rvol,
                "top_n": top_n,
            },
            "universe_size": len(symbols),
            "candidates_total": len(candidates),
            "candidates_top_n": len(top_candidates),
            "candidates": top_candidates,
        }
    
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "error": str(e),
            "candidates": [],
        }
    
    finally:
        db.close()


async def get_todays_candidates(top_n: int = 20) -> list[dict]:
    """
    Get today's top N candidates from database (if already scanned).
    """
    db = SessionLocal()
    today = datetime.now(ET).date()
    
    try:
        candidates = db.query(OpeningRange).filter(
            and_(
                OpeningRange.date == today,
                OpeningRange.passed_filters == True,
            )
        ).order_by(OpeningRange.rank.asc()).limit(top_n).all()
        
        return [
            {
                "symbol": c.symbol,
                "rank": c.rank,
                "direction": c.direction,
                "direction_label": "LONG" if c.direction == 1 else "SHORT",
                "rvol": c.rvol,
                "atr": c.atr,
                "entry_price": c.entry_price,
                "stop_price": c.stop_price,
                "or_high": c.or_high,
                "or_low": c.or_low,
                "signal_generated": c.signal_generated,
                "order_placed": c.order_placed,
            }
            for c in candidates
        ]
    
    finally:
        db.close()
