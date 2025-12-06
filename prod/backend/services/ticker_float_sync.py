"""
Fetch and cache float (shares outstanding) for tickers using Alpha Vantage API.

Float is used to filter for low-float stocks in Ross Cameron strategy.

Usage:
    from services.ticker_float_sync import sync_float_for_tickers
    sync_float_for_tickers(session, symbols=['AAPL', 'TSLA'])
"""
import logging
import time
import os
import requests
from typing import Optional, List
from sqlalchemy.orm import Session
from db.models import Ticker
from core.config import Settings

logger = logging.getLogger(__name__)

# Cache to avoid refetching the same ticker within a session
_FLOAT_CACHE = {}

def get_float_from_alphavantage(symbol: str, api_key: str) -> Optional[int]:
    """
    Fetch float (shares outstanding) from Alpha Vantage.
    
    Args:
        symbol: Stock ticker symbol
        api_key: Alpha Vantage API key
        
    Returns:
        Float as integer (shares outstanding), or None if not found/error
    """
    if symbol in _FLOAT_CACHE:
        return _FLOAT_CACHE[symbol]
    
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "OVERVIEW",
        "symbol": symbol,
        "apikey": api_key
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Check for rate limit or error
        if "Note" in data and "5 calls per minute" in data["Note"]:
            logger.warning("Alpha Vantage rate limit reached. Sleeping for 60 seconds...")
            time.sleep(60)
            # Retry once
            response = requests.get(url, params=params)
            data = response.json()

        if "SharesOutstanding" in data:
            shares_str = data["SharesOutstanding"]
            if shares_str and shares_str != "None":
                float_shares = int(float(shares_str)) # API returns string like "12345678"
                _FLOAT_CACHE[symbol] = float_shares
                logger.debug(f"{symbol}: float = {float_shares:,}")
                return float_shares
            else:
                logger.warning(f"{symbol}: SharesOutstanding is None or empty")
        else:
            logger.warning(f"{symbol}: SharesOutstanding not found in response: {data.keys()}")
            
        _FLOAT_CACHE[symbol] = None
        return None

    except Exception as e:
        logger.error(f"{symbol}: Error fetching float from Alpha Vantage: {e}")
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
    settings = Settings()
    api_key = settings.ALPHAVANTAGE_API_KEY
    
    if not api_key:
        # Fallback to env var if not in settings (though settings loads from env)
        api_key = os.getenv("ALPHAVANTAGE_API_KEY")
        
    if not api_key:
        logger.error("ALPHAVANTAGE_API_KEY not set. Cannot sync float.")
        return

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
    
    logger.info(f"Syncing float for {len(symbols)} tickers using Alpha Vantage...")
    
    count = 0
    for symbol in symbols:
        float_val = get_float_from_alphavantage(symbol, api_key)
        
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
        # Simple rate limiting: 1 call every 12 seconds (5 calls/min)
        time.sleep(12) 
    
    db.close()
    logger.info("Float sync complete")

