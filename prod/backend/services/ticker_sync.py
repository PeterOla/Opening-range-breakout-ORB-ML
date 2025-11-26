"""
Ticker universe synchronisation service.

Fetches all NYSE/NASDAQ stocks from Polygon and stores in database.
Includes both active and delisted tickers for survivorship-bias-free data.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.database import SessionLocal
from db.models import Ticker
from services.polygon_client import get_polygon_client


async def sync_tickers_from_polygon(
    include_delisted: bool = False,
    db: Optional[Session] = None,
) -> dict:
    """
    Sync stock tickers from Polygon to database.
    
    Args:
        include_delisted: Whether to include delisted stocks
        db: Optional database session
        
    Returns:
        Dict with sync stats
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        client = get_polygon_client()
        
        if include_delisted:
            tickers = await client.get_all_us_stocks()
        else:
            print("Fetching active US stocks...")
            tickers = await client.get_stock_tickers(active=True)
        
        if not tickers:
            return {"status": "error", "error": "No tickers fetched"}
        
        # Stats
        inserted = 0
        updated = 0
        
        for t in tickers:
            symbol = t.get("ticker")
            if not symbol:
                continue
            
            # Check if exists
            existing = db.query(Ticker).filter(Ticker.symbol == symbol).first()
            
            if existing:
                # Update
                existing.name = t.get("name")
                existing.primary_exchange = t.get("primary_exchange")
                existing.type = t.get("type")
                existing.active = t.get("active", True)
                existing.currency = t.get("currency", "USD")
                existing.cik = t.get("cik")
                if t.get("delisted_utc"):
                    try:
                        existing.delisted_utc = datetime.fromisoformat(
                            t["delisted_utc"].replace("Z", "+00:00")
                        )
                    except:
                        pass
                existing.last_updated = datetime.utcnow()
                updated += 1
            else:
                # Insert
                delisted_dt = None
                if t.get("delisted_utc"):
                    try:
                        delisted_dt = datetime.fromisoformat(
                            t["delisted_utc"].replace("Z", "+00:00")
                        )
                    except:
                        pass
                
                new_ticker = Ticker(
                    symbol=symbol,
                    name=t.get("name"),
                    primary_exchange=t.get("primary_exchange"),
                    type=t.get("type"),
                    active=t.get("active", True),
                    currency=t.get("currency", "USD"),
                    cik=t.get("cik"),
                    delisted_utc=delisted_dt,
                )
                db.add(new_ticker)
                inserted += 1
            
            # Commit in batches
            if (inserted + updated) % 500 == 0:
                db.commit()
                print(f"  Progress: {inserted} inserted, {updated} updated")
        
        db.commit()
        
        return {
            "status": "success",
            "total_fetched": len(tickers),
            "inserted": inserted,
            "updated": updated,
        }
    
    except Exception as e:
        db.rollback()
        return {"status": "error", "error": str(e)}
    
    finally:
        if close_session:
            db.close()


def get_active_tickers(
    db: Optional[Session] = None,
    limit: Optional[int] = None,
) -> list[str]:
    """
    Get list of active ticker symbols from database.
    
    Returns:
        List of ticker symbols
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        query = db.query(Ticker.symbol).filter(Ticker.active == True)
        
        if limit:
            query = query.limit(limit)
        
        return [row[0] for row in query.all()]
    
    finally:
        if close_session:
            db.close()


def get_filtered_tickers(
    min_price: Optional[float] = None,
    min_volume: Optional[float] = None,
    min_atr: Optional[float] = None,
    active_only: bool = True,
    db: Optional[Session] = None,
) -> list[str]:
    """
    Get tickers that pass pre-computed filters.
    
    Requires daily_bars to be synced first to populate filter flags.
    
    Returns:
        List of ticker symbols
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        query = db.query(Ticker.symbol)
        
        if active_only:
            query = query.filter(Ticker.active == True)
        
        if min_price is not None:
            query = query.filter(Ticker.meets_price_filter == True)
        
        if min_volume is not None:
            query = query.filter(Ticker.meets_volume_filter == True)
        
        if min_atr is not None:
            query = query.filter(Ticker.meets_atr_filter == True)
        
        return [row[0] for row in query.all()]
    
    finally:
        if close_session:
            db.close()


def get_ticker_stats(db: Optional[Session] = None) -> dict:
    """
    Get statistics about ticker universe.
    
    Returns:
        Dict with counts
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        total = db.query(func.count(Ticker.id)).scalar()
        active = db.query(func.count(Ticker.id)).filter(Ticker.active == True).scalar()
        delisted = db.query(func.count(Ticker.id)).filter(Ticker.active == False).scalar()
        
        nyse = db.query(func.count(Ticker.id)).filter(Ticker.primary_exchange == "XNYS").scalar()
        nasdaq = db.query(func.count(Ticker.id)).filter(Ticker.primary_exchange == "XNAS").scalar()
        
        meets_all = db.query(func.count(Ticker.id)).filter(
            Ticker.meets_price_filter == True,
            Ticker.meets_volume_filter == True,
            Ticker.meets_atr_filter == True,
        ).scalar()
        
        return {
            "total": total or 0,
            "active": active or 0,
            "delisted": delisted or 0,
            "nyse": nyse or 0,
            "nasdaq": nasdaq or 0,
            "meets_all_filters": meets_all or 0,
        }
    
    finally:
        if close_session:
            db.close()


async def update_ticker_filters(db: Optional[Session] = None) -> dict:
    """
    Update filter flags on tickers based on latest daily_bars data.
    
    Checks each ticker's latest bar for:
    - Price >= $5
    - Avg volume >= 1M
    - ATR >= $0.50
    
    Returns:
        Dict with update stats
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        from db.models import DailyBar
        from sqlalchemy import and_
        
        # Get latest bar per symbol with metrics
        subq = db.query(
            DailyBar.symbol,
            func.max(DailyBar.date).label("max_date")
        ).group_by(DailyBar.symbol).subquery()
        
        latest_bars = db.query(DailyBar).join(
            subq,
            and_(
                DailyBar.symbol == subq.c.symbol,
                DailyBar.date == subq.c.max_date,
            )
        ).all()
        
        # Build lookup
        bar_lookup = {
            bar.symbol: {
                "close": bar.close,
                "atr_14": bar.atr_14,
                "avg_volume_14": bar.avg_volume_14,
            }
            for bar in latest_bars
        }
        
        updated = 0
        
        # Update ticker flags
        tickers = db.query(Ticker).filter(Ticker.active == True).all()
        
        for ticker in tickers:
            bar = bar_lookup.get(ticker.symbol)
            
            if bar:
                ticker.meets_price_filter = (bar["close"] or 0) >= 5.0
                ticker.meets_volume_filter = (bar["avg_volume_14"] or 0) >= 1_000_000
                ticker.meets_atr_filter = (bar["atr_14"] or 0) >= 0.50
                updated += 1
            else:
                # No data - reset flags
                ticker.meets_price_filter = False
                ticker.meets_volume_filter = False
                ticker.meets_atr_filter = False
        
        db.commit()
        
        return {
            "status": "success",
            "tickers_updated": updated,
            "bars_found": len(bar_lookup),
        }
    
    except Exception as e:
        db.rollback()
        return {"status": "error", "error": str(e)}
    
    finally:
        if close_session:
            db.close()
