"""
Data synchronisation service.

- Nightly job: Fetch 14-day daily bars from Polygon → daily_bars table
- Calculate ATR(14) and avg_volume(14) for each symbol
- Delete bars older than 30 days
"""
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import and_, delete

from db.database import SessionLocal
from db.models import DailyBar
from services.polygon_client import get_polygon_client


ET = ZoneInfo("America/New_York")


def compute_atr(bars: list[dict], period: int = 14) -> Optional[float]:
    """
    Compute ATR from list of daily bar dicts.
    Returns latest ATR value.
    """
    if len(bars) < period + 1:
        return None
    
    df = pd.DataFrame(bars).sort_values("timestamp").reset_index(drop=True)
    
    prev_close = df["close"].shift(1)
    high_low = df["high"] - df["low"]
    high_prev_close = (df["high"] - prev_close).abs()
    low_prev_close = (df["low"] - prev_close).abs()
    
    tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    
    latest = atr.iloc[-1] if not atr.empty else None
    return float(latest) if pd.notna(latest) else None


def compute_avg_volume(bars: list[dict], period: int = 14) -> Optional[float]:
    """
    Compute average volume from list of daily bar dicts.
    Returns latest avg volume value.
    """
    if len(bars) < period:
        return None
    
    df = pd.DataFrame(bars).sort_values("timestamp").reset_index(drop=True)
    avg_vol = df["volume"].rolling(window=period, min_periods=period).mean()
    
    latest = avg_vol.iloc[-1] if not avg_vol.empty else None
    return float(latest) if pd.notna(latest) else None


async def sync_daily_bars_for_symbol(
    symbol: str,
    lookback_days: int = 30,
    db: Optional[Session] = None,
) -> int:
    """
    Sync daily bars for a single symbol from Polygon to database.
    
    Returns:
        Number of bars synced
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        client = get_polygon_client()
        
        end_date = datetime.now(ET)
        start_date = end_date - timedelta(days=lookback_days + 10)  # Buffer for weekends
        
        bars = await client.get_daily_bars(symbol, start_date, end_date)
        
        if not bars:
            return 0
        
        # Compute metrics
        atr_14 = compute_atr(bars, 14)
        avg_vol_14 = compute_avg_volume(bars, 14)
        
        # Delete existing bars for this symbol within date range
        db.execute(
            delete(DailyBar).where(
                and_(
                    DailyBar.symbol == symbol,
                    DailyBar.date >= start_date,
                )
            )
        )
        
        # Insert new bars
        for bar in bars:
            db_bar = DailyBar(
                symbol=symbol,
                date=bar["timestamp"],
                open=bar["open"],
                high=bar["high"],
                low=bar["low"],
                close=bar["close"],
                volume=bar["volume"],
                vwap=bar.get("vwap"),
                atr_14=atr_14 if bar == bars[-1] else None,  # Only store on latest
                avg_volume_14=avg_vol_14 if bar == bars[-1] else None,
            )
            db.add(db_bar)
        
        db.commit()
        return len(bars)
    
    except Exception as e:
        db.rollback()
        print(f"Error syncing {symbol}: {e}")
        return 0
    
    finally:
        if close_session:
            db.close()


async def sync_universe_daily_bars(
    symbols: list[str],
    lookback_days: int = 30,
) -> dict:
    """
    Sync daily bars for entire universe from Polygon.
    Uses grouped daily endpoint for efficiency.
    
    Returns:
        Dict with sync stats
    """
    import asyncio
    
    db = SessionLocal()
    client = get_polygon_client()
    
    try:
        end_date = datetime.now(ET).date()
        start_date = end_date - timedelta(days=lookback_days)
        
        synced = 0
        failed = 0
        
        # Fetch each day's grouped data
        current_date = start_date
        while current_date <= end_date:
            # Skip weekends
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue
            
            print(f"Fetching grouped daily for {current_date}...")
            
            try:
                grouped = await client.get_grouped_daily(datetime.combine(current_date, datetime.min.time()))
                
                # Filter to our symbols and insert
                for symbol in symbols:
                    if symbol in grouped:
                        bar = grouped[symbol]
                        
                        # Check if already exists
                        existing = db.query(DailyBar).filter(
                            and_(
                                DailyBar.symbol == symbol,
                                DailyBar.date == bar["timestamp"].date() if hasattr(bar["timestamp"], 'date') else bar["timestamp"],
                            )
                        ).first()
                        
                        if not existing:
                            db_bar = DailyBar(
                                symbol=symbol,
                                date=bar["timestamp"],
                                open=bar["open"],
                                high=bar["high"],
                                low=bar["low"],
                                close=bar["close"],
                                volume=bar["volume"],
                                vwap=bar.get("vwap"),
                            )
                            db.add(db_bar)
                            synced += 1
                
                db.commit()
                
            except Exception as e:
                print(f"Error fetching {current_date}: {e}")
                failed += 1
            
            current_date += timedelta(days=1)
            
            # Rate limit: wait between days to respect 5 calls/min
            await asyncio.sleep(15)
        
        # Now compute ATR and avg_volume for each symbol
        print("Computing ATR and avg volume...")
        for symbol in symbols:
            bars = db.query(DailyBar).filter(
                DailyBar.symbol == symbol
            ).order_by(DailyBar.date.asc()).all()
            
            if len(bars) >= 14:
                bar_dicts = [
                    {"timestamp": b.date, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
                    for b in bars
                ]
                
                atr_14 = compute_atr(bar_dicts, 14)
                avg_vol_14 = compute_avg_volume(bar_dicts, 14)
                
                # Update latest bar with computed metrics
                if bars:
                    bars[-1].atr_14 = atr_14
                    bars[-1].avg_volume_14 = avg_vol_14
        
        db.commit()
        
        return {
            "status": "success",
            "symbols_requested": len(symbols),
            "bars_synced": synced,
            "days_failed": failed,
        }
    
    except Exception as e:
        db.rollback()
        return {"status": "error", "error": str(e)}
    
    finally:
        db.close()


async def cleanup_old_bars(days_to_keep: int = 30) -> int:
    """
    Delete daily bars older than specified days.
    Returns number of rows deleted.
    """
    db = SessionLocal()
    
    try:
        cutoff = datetime.now(ET) - timedelta(days=days_to_keep)
        
        result = db.execute(
            delete(DailyBar).where(DailyBar.date < cutoff)
        )
        
        db.commit()
        return result.rowcount
    
    except Exception as e:
        db.rollback()
        print(f"Error cleaning up old bars: {e}")
        return 0
    
    finally:
        db.close()


def get_latest_metrics(symbol: str, db: Optional[Session] = None) -> dict:
    """
    Get latest ATR and avg volume for a symbol from database.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        latest = db.query(DailyBar).filter(
            DailyBar.symbol == symbol
        ).order_by(DailyBar.date.desc()).first()
        
        if latest:
            return {
                "symbol": symbol,
                "date": latest.date,
                "close": latest.close,
                "atr_14": latest.atr_14,
                "avg_volume_14": latest.avg_volume_14,
            }
        
        return {}
    
    finally:
        if close_session:
            db.close()


def get_universe_with_metrics(
    min_price: float = 5.0,
    min_atr: float = 0.50,
    min_avg_volume: float = 1_000_000,
    db: Optional[Session] = None,
) -> list[dict]:
    """
    Get all symbols from daily_bars that pass base filters.
    Returns list of symbols with their latest metrics.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        # Get latest bar per symbol with metrics
        from sqlalchemy import func
        
        # Subquery for latest date per symbol
        subq = db.query(
            DailyBar.symbol,
            func.max(DailyBar.date).label("max_date")
        ).group_by(DailyBar.symbol).subquery()
        
        # Join to get full bar data
        latest_bars = db.query(DailyBar).join(
            subq,
            and_(
                DailyBar.symbol == subq.c.symbol,
                DailyBar.date == subq.c.max_date,
            )
        ).filter(
            DailyBar.close >= min_price,
            DailyBar.atr_14 >= min_atr,
            DailyBar.avg_volume_14 >= min_avg_volume,
        ).all()
        
        return [
            {
                "symbol": bar.symbol,
                "date": bar.date,
                "close": bar.close,
                "atr_14": bar.atr_14,
                "avg_volume_14": bar.avg_volume_14,
            }
            for bar in latest_bars
        ]
    
    finally:
        if close_session:
            db.close()
