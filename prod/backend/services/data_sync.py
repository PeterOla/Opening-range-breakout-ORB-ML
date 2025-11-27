"""
Data synchronisation service.

- Nightly job: Fetch 14-day daily bars from Polygon → daily_bars table
- Calculate ATR(14) and avg_volume(14) for each symbol
- Delete bars older than 30 days

Uses grouped daily endpoint for efficiency (1 call = all stocks for 1 day).
"""
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import and_, delete
import asyncio

from db.database import SessionLocal
from db.models import DailyBar, Ticker
from services.polygon_client import get_polygon_client


ET = ZoneInfo("America/New_York")


def get_trading_days(start_date: datetime, end_date: datetime) -> list[datetime]:
    """
    Get list of trading days (weekdays only, excludes weekends).
    Does not account for market holidays - Polygon returns empty for non-trading days.
    """
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # Mon=0, Fri=4
            days.append(current)
        current += timedelta(days=1)
    return days


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
    Uses grouped daily endpoint for efficiency (1 API call = all stocks for 1 day).
    
    For 14-day lookback: ~20 API calls (14 weekdays + buffer for holidays)
    Much more efficient than per-symbol calls (1 call per symbol per day).
    
    Returns:
        Dict with sync stats
    """
    db = SessionLocal()
    client = get_polygon_client()
    
    try:
        end_date = datetime.now(ET).date()
        start_date = end_date - timedelta(days=lookback_days)
        
        # Get trading days only
        trading_days = get_trading_days(
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.min.time())
        )
        
        synced = 0
        failed = 0
        symbols_set = set(symbols)  # Fast lookup
        
        print(f"Syncing {len(trading_days)} trading days for {len(symbols)} symbols...")
        
        for i, day in enumerate(trading_days):
            print(f"[{i+1}/{len(trading_days)}] Fetching grouped daily for {day.strftime('%Y-%m-%d')}...")
            
            try:
                grouped = await client.get_grouped_daily(day)
                
                if not grouped:
                    print(f"  No data for {day.strftime('%Y-%m-%d')} (likely holiday)")
                    continue
                
                day_synced = 0
                
                # Filter to our symbols and insert
                for symbol in symbols_set:
                    if symbol in grouped:
                        bar = grouped[symbol]
                        bar_date = bar["timestamp"].date() if hasattr(bar["timestamp"], 'date') else bar["timestamp"]
                        
                        # Check if already exists
                        existing = db.query(DailyBar).filter(
                            and_(
                                DailyBar.symbol == symbol,
                                DailyBar.date == bar_date,
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
                            day_synced += 1
                
                db.commit()
                synced += day_synced
                print(f"  ✓ Synced {day_synced} bars")
                
            except Exception as e:
                print(f"  ✗ Error fetching {day.strftime('%Y-%m-%d')}: {e}")
                failed += 1
            
            # Rate limit: Polygon free tier = 5 calls/min
            # 12 seconds between calls keeps us safe
            if i < len(trading_days) - 1:
                await asyncio.sleep(12)
        
        # Now compute ATR and avg_volume for each symbol
        print("\nComputing ATR(14) and avg_volume(14) for all symbols...")
        updated_count = 0
        
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
                    updated_count += 1
        
        db.commit()
        print(f"  ✓ Updated metrics for {updated_count} symbols")
        
        return {
            "status": "success",
            "symbols_requested": len(symbols),
            "bars_synced": synced,
            "days_processed": len(trading_days),
            "days_failed": failed,
            "metrics_updated": updated_count,
        }
    
    except Exception as e:
        db.rollback()
        return {"status": "error", "error": str(e)}
    
    finally:
        db.close()


async def sync_daily_bars_fast(lookback_days: int = 14) -> dict:
    """
    Fast sync: Fetch grouped daily bars for ALL stocks, then filter to active universe.
    
    This is the most efficient approach for syncing the entire universe:
    - 1 API call per day (not 1 per symbol)
    - For 14 days = ~20 API calls total
    - Only stores bars for active tickers in database
    
    Use this for the nightly sync job.
    
    Returns:
        Dict with sync stats
    """
    db = SessionLocal()
    client = get_polygon_client()
    
    try:
        # Get active ticker symbols for filtering
        active_symbols = set(
            row[0] for row in db.query(Ticker.symbol).filter(Ticker.active == True).all()
        )
        
        if not active_symbols:
            return {"status": "error", "error": "No active tickers. Run ticker sync first."}
        
        print(f"Syncing bars for {len(active_symbols)} active tickers...")
        
        end_date = datetime.now(ET).date()
        start_date = end_date - timedelta(days=lookback_days + 7)  # Buffer for weekends/holidays
        
        trading_days = get_trading_days(
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.min.time())
        )
        
        total_synced = 0
        days_processed = 0
        days_failed = 0
        symbols_seen = set()
        
        print(f"Fast sync: {len(trading_days)} trading days...")
        
        for i, day in enumerate(trading_days):
            print(f"[{i+1}/{len(trading_days)}] {day.strftime('%Y-%m-%d')}...", end=" ")
            
            try:
                grouped = await client.get_grouped_daily(day)
                
                if not grouped:
                    print("(no data - holiday?)")
                    continue
                
                day_synced = 0
                
                # Only insert bars for active tickers
                for symbol, bar in grouped.items():
                    # Skip if not in our active universe
                    if symbol not in active_symbols:
                        continue
                    
                    symbols_seen.add(symbol)
                    bar_date = bar["timestamp"].date() if hasattr(bar["timestamp"], 'date') else bar["timestamp"]
                    
                    # Upsert: check if exists
                    existing = db.query(DailyBar).filter(
                        and_(
                            DailyBar.symbol == symbol,
                            DailyBar.date == bar_date,
                        )
                    ).first()
                    
                    if not existing:
                        try:
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
                            db.flush()  # Catch unique constraint violations early
                            day_synced += 1
                        except Exception:
                            db.rollback()  # Skip duplicates silently
                
                db.commit()
                total_synced += day_synced
                days_processed += 1
                print(f"✓ {day_synced} bars")
                
            except Exception as e:
                print(f"✗ Error: {e}")
                days_failed += 1
            
            # Rate limit
            if i < len(trading_days) - 1:
                await asyncio.sleep(12)
        
        # Compute ATR and avg_volume for all symbols with enough data
        print(f"\nComputing metrics for {len(symbols_seen)} symbols...")
        updated_count = 0
        
        for symbol in symbols_seen:
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
                
                if bars:
                    bars[-1].atr_14 = atr_14
                    bars[-1].avg_volume_14 = avg_vol_14
                    updated_count += 1
        
        db.commit()
        print(f"  ✓ Metrics updated for {updated_count} symbols")
        
        return {
            "status": "success",
            "days_processed": days_processed,
            "days_failed": days_failed,
            "bars_synced": total_synced,
            "unique_symbols": len(symbols_seen),
            "metrics_updated": updated_count,
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
