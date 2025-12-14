"""Fetch and cache float (shares outstanding) for tickers using SEC Company Facts (free).

Notes
- We use SEC XBRL Company Facts `EntityCommonStockSharesOutstanding`.
- This is typically updated on filing cadence (not daily).
- Set `SEC_USER_AGENT` in your environment/.env.
"""
import logging
import time
from typing import Optional, List
from sqlalchemy.orm import Session
from db.models import Ticker
from services.sec_shares import get_latest_shares_outstanding

logger = logging.getLogger(__name__)

# Cache to avoid refetching the same ticker within a session
_FLOAT_CACHE = {}

def get_float_from_sec(symbol: str) -> Optional[int]:
    """Fetch latest shares outstanding from SEC (as a proxy for float)."""
    if symbol in _FLOAT_CACHE:
        return _FLOAT_CACHE[symbol]

    try:
        val = get_latest_shares_outstanding(symbol)
        _FLOAT_CACHE[symbol] = val
        if val is not None:
            logger.debug(f"{symbol}: shares_outstanding(latest) = {val:,}")
        return val
    except Exception as e:
        logger.error(f"{symbol}: Error fetching shares outstanding from SEC: {e}")
        _FLOAT_CACHE[symbol] = None
        return None


def sync_float_for_tickers(db: Session, symbols: Optional[List[str]] = None, force_refresh: bool = False) -> None:
    """
    Fetch float for tickers and update database.
    
    Args:
        db: Database session
        symbols: List of ticker symbols to sync. If None, syncs all tickers with NULL float.
        force_refresh: If True, re-fetch even if float already exists.
    """
    if symbols is None:
        # Fetch all tickers with missing float
        tickers_to_sync = db.query(Ticker).filter(
            Ticker.float.is_(None) | (Ticker.float == 0)
        ).all()
        symbols = [t.symbol for t in tickers_to_sync]
    else:
        # Validate symbols exist in DB
        tickers_to_sync = db.query(Ticker).filter(Ticker.symbol.in_(symbols)).all()
        if force_refresh:
            symbols = [t.symbol for t in tickers_to_sync]
        else:
            # Only re-fetch if NULL
            symbols = [t.symbol for t in tickers_to_sync if t.float is None or t.float == 0]
    
    if not symbols:
        logger.info("No tickers to sync float for")
        return
    
    logger.info(f"Syncing float for {len(symbols)} tickers using SEC Company Facts...")
    
    count = 0
    for symbol in symbols:
        float_val = get_float_from_sec(symbol)
        
        if float_val is not None:
            # Update database
            ticker = db.query(Ticker).filter(Ticker.symbol == symbol).first()
            if ticker:
                ticker.float = float_val
                db.commit()
                logger.info(f"✓ {symbol}: float = {float_val:,}")
            else:
                logger.warning(f"{symbol}: not found in database")
        else:
            logger.warning(f"✗ {symbol}: could not fetch float")
        
        count += 1
        # Be polite to SEC; the client also sleeps on cache-misses.
        time.sleep(0.05)
    
    db.close()
    logger.info("Float sync complete")

