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
from services.universe import get_trading_client
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus


async def sync_tickers_from_alpaca(
    db: Optional[Session] = None,
) -> dict:
    """
    Sync active stock tickers from Alpaca to database.
    
    - Inserts new tickers
    - Updates existing tickers
    - Marks tickers as INACTIVE if they're no longer in Alpaca's active list
    
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
        client = get_trading_client()
        
        # Get all active US equities
        request = GetAssetsRequest(
            asset_class=AssetClass.US_EQUITY,
            status=AssetStatus.ACTIVE
        )
        assets = client.get_all_assets(request)
        
        # Filter to tradeable, non-OTC, common stocks (roughly)
        # Alpaca doesn't strictly separate "common stock" vs ETF in the asset object easily without parsing name/exchange
        # But we can filter out obvious non-tradeables
        tickers = [
            a for a in assets 
            if a.tradable and a.status == AssetStatus.ACTIVE and "." not in a.symbol
        ]
        
        if not tickers:
            return {"status": "error", "error": "No tickers fetched from Alpaca"}
            
        print(f"✓ Fetched {len(tickers)} active tickers from Alpaca")
        
        # Build set of active symbols
        active_symbols_from_source = {t.symbol for t in tickers}
        
        # Get current active symbols from database
        current_active_in_db = {
            row[0] for row in db.query(Ticker.symbol).filter(Ticker.active == True).all()
        }
        
        # Find symbols to deactivate
        symbols_to_deactivate = current_active_in_db - active_symbols_from_source
        
        print(f"  Current active in DB: {len(current_active_in_db)}")
        print(f"  Active from Alpaca: {len(active_symbols_from_source)}")
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
        
        inserted = 0
        updated = 0
        
        for t in tickers:
            symbol = t.symbol
            name = t.name
            exchange = t.exchange.value if hasattr(t.exchange, 'value') else str(t.exchange)
            
            existing = db.query(Ticker).filter(Ticker.symbol == symbol).first()
            
            if existing:
                existing.name = name
                existing.primary_exchange = exchange
                existing.active = True
                existing.last_updated = datetime.utcnow()
                updated += 1
            else:
                new_ticker = Ticker(
                    symbol=symbol,
                    name=name,
                    primary_exchange=exchange,
                    active=True,
                    last_updated=datetime.utcnow()
                )
                db.add(new_ticker)
                inserted += 1
                
            if (inserted + updated) % 500 == 0:
                db.commit()
                print(f"  Progress: {inserted + updated}/{len(tickers)} - {inserted} inserted, {updated} updated")
                
        db.commit()
        print(f"✓ Database sync complete: {inserted} inserted, {updated} updated, {deactivated} deactivated")
        
        return {
            "status": "success",
            "total_fetched": len(tickers),
            "inserted": inserted,
            "updated": updated,
            "deactivated": deactivated,
            "errors": 0
        }
        
    except Exception as e:
        db.rollback()
        print(f"Error syncing tickers from Alpaca: {e}")
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
