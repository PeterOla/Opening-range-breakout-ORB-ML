"""
Ticker universe synchronisation service.

Fetches all NYSE/NASDAQ stocks from Polygon and stores in database.
Active stocks only (no delisted) for production use.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.database import SessionLocal
from db.models import Ticker
from services.polygon_client import get_polygon_client


async def sync_tickers_from_polygon(
    db: Optional[Session] = None,
) -> dict:
    """
    Sync active stock tickers from Polygon to database.
    Uses official massive/polygon library with proper pagination.
    
    - Inserts new tickers
    - Updates existing tickers
    - Marks tickers as INACTIVE if they're no longer in Polygon's active list
    
    Expected result: ~5,000-6,000 active NYSE/NASDAQ common stocks.
    
    Args:
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
        
        # Use the sync method directly - works reliably
        # The async wrapper can have issues with run_in_executor
        tickers = client.get_active_stock_tickers_sync()
        
        if not tickers:
            return {"status": "error", "error": "No tickers fetched"}
        
        print(f"✓ Fetched {len(tickers)} active tickers from Polygon")
        
        # Build set of active symbols from Polygon
        active_symbols_from_polygon = {t.get("ticker") for t in tickers if t.get("ticker")}
        
        # Get current active symbols from database
        current_active_in_db = {
            row[0] for row in db.query(Ticker.symbol).filter(Ticker.active == True).all()
        }
        
        # Find symbols to deactivate (in DB but not in Polygon's active list)
        symbols_to_deactivate = current_active_in_db - active_symbols_from_polygon
        
        print(f"  Current active in DB: {len(current_active_in_db)}")
        print(f"  Active from Polygon: {len(active_symbols_from_polygon)}")
        print(f"  To deactivate: {len(symbols_to_deactivate)}")
        
        # Deactivate tickers no longer active
        deactivated = 0
        if symbols_to_deactivate:
            deactivated = db.query(Ticker).filter(
                Ticker.symbol.in_(symbols_to_deactivate)
            ).update(
                {Ticker.active: False, Ticker.last_updated: datetime.utcnow()},
                synchronize_session=False
            )
            db.commit()
            print(f"  ✓ Deactivated {deactivated} tickers")
        
        print("Starting database insert/update...")
        
        # Stats
        inserted = 0
        updated = 0
        errors = 0
        
        for i, t in enumerate(tickers):
            symbol = t.get("ticker")
            if not symbol:
                continue
            
            try:
                # Check if exists
                existing = db.query(Ticker).filter(Ticker.symbol == symbol).first()
                
                if existing:
                    # Update
                    existing.name = t.get("name")
                    existing.primary_exchange = t.get("primary_exchange")
                    existing.type = t.get("type")
                    existing.active = True  # Re-activate if it was inactive
                    existing.currency = t.get("currency", "USD")
                    existing.cik = t.get("cik")
                    existing.last_updated = datetime.utcnow()
                    updated += 1
                else:
                    # Insert
                    new_ticker = Ticker(
                        symbol=symbol,
                        name=t.get("name"),
                        primary_exchange=t.get("primary_exchange"),
                        type=t.get("type"),
                        active=True,
                        currency=t.get("currency", "USD"),
                        cik=t.get("cik"),
                    )
                    db.add(new_ticker)
                    inserted += 1
                
                # Commit in batches of 500
                if (i + 1) % 500 == 0:
                    db.commit()
                    print(f"  Progress: {i + 1}/{len(tickers)} - {inserted} inserted, {updated} updated")
                    
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"  Error on {symbol}: {e}")
                db.rollback()
        
        # Final commit
        db.commit()
        print(f"✓ Database sync complete: {inserted} inserted, {updated} updated, {deactivated} deactivated, {errors} errors")
        
        return {
            "status": "success",
            "total_fetched": len(tickers),
            "inserted": inserted,
            "updated": updated,
            "deactivated": deactivated,
            "errors": errors,
        }
    
    except Exception as e:
        db.rollback()
        print(f"✗ Sync failed: {e}")
        import traceback
        traceback.print_exc()
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
        
        # Get last updated timestamp
        last_updated = db.query(func.max(Ticker.last_updated)).scalar()
        
        return {
            "total": total or 0,
            "active": active or 0,
            "delisted": delisted or 0,
            "nyse": nyse or 0,
            "nasdaq": nasdaq or 0,
            "meets_all_filters": meets_all or 0,
            "last_updated": last_updated.isoformat() if last_updated else None,
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
