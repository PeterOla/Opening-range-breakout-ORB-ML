"""
Scanner API routes.
Endpoints for running ORB stock scanner and data sync.
"""
from fastapi import APIRouter, Query, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from services.orb_scanner import scan_orb_candidates, get_todays_candidates
from services.data_sync import (
    sync_universe_daily_bars,
    sync_daily_bars_fast,
    cleanup_old_bars,
    get_universe_with_metrics,
)
from services.ticker_sync import (
    sync_tickers_from_polygon,
    get_active_tickers,
    get_ticker_stats,
    update_ticker_filters,
)


router = APIRouter(prefix="/scanner", tags=["scanner"])
ET = ZoneInfo("America/New_York")


class ScannerFilters(BaseModel):
    """Request body for custom scanner filters."""
    min_price: float = 5.0
    min_avg_volume: float = 1_000_000
    min_atr: float = 0.50
    min_rvol: float = 1.0
    top_n: int = 20


class ScanCandidate(BaseModel):
    """Single stock candidate from scanner."""
    symbol: str
    rank: Optional[int] = None
    price: Optional[float] = None
    atr: float
    avg_volume: int
    rvol: float
    or_high: float
    or_low: float
    or_open: Optional[float] = None
    or_close: Optional[float] = None
    or_volume: int
    direction: int
    direction_label: str
    entry_price: float
    stop_price: float
    stop_distance: Optional[float] = None


class DataSyncRequest(BaseModel):
    """Request body for data sync."""
    symbols: Optional[list[str]] = None  # If None, use active tickers from DB
    lookback_days: int = 30


class TickerSyncRequest(BaseModel):
    """Request body for ticker sync."""
    include_delisted: bool = False


# ============ Scanner Endpoints ============

@router.get("/run")
async def run_scanner(
    min_price: float = Query(5.0, ge=0, description="Minimum stock price"),
    min_avg_volume: float = Query(1_000_000, ge=0, description="Minimum 14-day avg volume"),
    min_atr: float = Query(0.50, ge=0, description="Minimum ATR value"),
    min_rvol: float = Query(1.0, ge=0, description="Minimum RVOL (1.0 = 100%)"),
    top_n: int = Query(20, ge=1, le=100, description="Number of top candidates to return"),
    save_to_db: bool = Query(True, description="Save results to database"),
):
    """
    Run the ORB stock scanner.
    
    Uses hybrid approach:
    - Historical data (ATR, avg volume) from Polygon via database
    - Live opening range from Alpaca
    
    Requires daily_bars to be synced first via /scanner/sync endpoint.
    """
    result = await scan_orb_candidates(
        min_price=min_price,
        min_atr=min_atr,
        min_avg_volume=min_avg_volume,
        min_rvol=min_rvol,
        top_n=top_n,
        save_to_db=save_to_db,
    )
    
    # Add count alias for backwards compatibility
    if "candidates_top_n" in result:
        result["count"] = result["candidates_top_n"]
    
    return result


@router.post("/run")
async def run_scanner_post(filters: ScannerFilters):
    """Run scanner with POST body filters."""
    result = await scan_orb_candidates(
        min_price=filters.min_price,
        min_atr=filters.min_atr,
        min_avg_volume=filters.min_avg_volume,
        min_rvol=filters.min_rvol,
        top_n=filters.top_n,
        save_to_db=True,
    )
    return result


@router.get("/today")
async def get_today_candidates(
    top_n: int = Query(20, ge=1, le=100),
):
    """
    Get today's scanned candidates from database.
    Use this after running /scanner/run to retrieve saved results.
    """
    candidates = await get_todays_candidates(top_n)
    return {
        "status": "success",
        "timestamp": datetime.now(ET).isoformat(),
        "count": len(candidates),
        "candidates": candidates,
    }


# ============ Data Sync Endpoints ============

@router.post("/sync-tickers")
async def sync_tickers(request: TickerSyncRequest = None):
    """
    Sync stock ticker universe from Polygon.
    
    Fetches all NYSE/NASDAQ common stocks and stores in database.
    Run this once to populate the universe, then periodically to update.
    
    Takes ~2-5 minutes depending on API rate limits.
    """
    include_delisted = request.include_delisted if request else False
    result = await sync_tickers_from_polygon(include_delisted=include_delisted)
    return result


@router.post("/sync-daily")
async def sync_daily_data(
    lookback_days: int = Query(14, ge=7, le=30, description="Number of days to fetch"),
):
    """
    Sync daily bars for ALL stocks from Polygon (fast method).
    
    Uses grouped daily endpoint: 1 API call = all stocks for 1 day.
    For 14-day lookback: ~20 API calls total (vs thousands for per-symbol).
    
    This is the recommended method for nightly sync:
    - Fetches OHLCV for all NYSE/NASDAQ stocks
    - Computes ATR(14) and avg_volume(14) for each symbol
    - Takes ~5 minutes for 14 days
    
    Use cases:
    - Initial setup: Run with lookback_days=14
    - Daily refresh: Run with lookback_days=3 (catches up weekends)
    """
    result = await sync_daily_bars_fast(lookback_days=lookback_days)
    
    # Update filter flags after sync
    if result.get("status") == "success":
        await update_ticker_filters()
    
    return result


@router.get("/tickers")
async def get_tickers(
    active_only: bool = Query(True, description="Only return active tickers"),
    limit: int = Query(None, description="Limit number of tickers returned"),
):
    """
    Get ticker symbols from database.
    
    Use after running /scanner/sync-tickers.
    """
    symbols = get_active_tickers(limit=limit) if active_only else get_active_tickers(limit=limit)
    return {
        "status": "success",
        "count": len(symbols),
        "symbols": symbols[:100] if len(symbols) > 100 else symbols,  # Truncate for response size
        "total": len(symbols),
    }


@router.get("/ticker-stats")
async def ticker_stats():
    """
    Get statistics about the ticker universe.
    """
    stats = get_ticker_stats()
    return {
        "status": "success",
        "stats": stats,
    }


@router.post("/sync")
async def sync_daily_bars(request: DataSyncRequest = None):
    """
    Sync daily bars from Polygon for specified symbols (or all active tickers).
    
    If no symbols provided, uses active tickers from database.
    Requires /scanner/sync-tickers to be run first if using DB tickers.
    
    This may take several minutes depending on the number of symbols
    and API rate limits (5 calls/min for Polygon Starter).
    """
    if request and request.symbols:
        symbols = request.symbols
    else:
        # Use active tickers from DB
        symbols = get_active_tickers()
        
        if not symbols:
            return {
                "status": "error",
                "error": "No tickers in database. Run /scanner/sync-tickers first.",
            }
    
    lookback_days = request.lookback_days if request else 30
    
    result = await sync_universe_daily_bars(
        symbols=symbols,
        lookback_days=lookback_days,
    )
    
    # Update filter flags after sync
    if result.get("status") == "success":
        await update_ticker_filters()
    
    return result


@router.get("/universe")
async def get_universe(
    min_price: float = Query(5.0, ge=0),
    min_atr: float = Query(0.50, ge=0),
    min_avg_volume: float = Query(1_000_000, ge=0),
):
    """
    Get current universe from database that passes base filters.
    Shows symbols available for scanning.
    """
    universe = get_universe_with_metrics(
        min_price=min_price,
        min_atr=min_atr,
        min_avg_volume=min_avg_volume,
    )
    return {
        "status": "success",
        "count": len(universe),
        "symbols": universe,
    }


@router.delete("/cleanup")
async def cleanup_old_data(
    days_to_keep: int = Query(30, ge=7, le=90),
):
    """
    Delete daily bars older than specified days.
    Keeps database size manageable.
    """
    deleted = await cleanup_old_bars(days_to_keep)
    return {
        "status": "success",
        "rows_deleted": deleted,
    }


# ============ Health Check ============

@router.get("/health")
async def scanner_health():
    """Check scanner service health and data status."""
    from db.database import SessionLocal
    from db.models import DailyBar, OpeningRange
    from sqlalchemy import func
    
    db = SessionLocal()
    try:
        daily_bar_count = db.query(func.count(DailyBar.id)).scalar()
        symbol_count = db.query(func.count(func.distinct(DailyBar.symbol))).scalar()
        latest_bar = db.query(func.max(DailyBar.date)).scalar()
        
        today = datetime.now(ET).date()
        todays_or_count = db.query(func.count(OpeningRange.id)).filter(
            OpeningRange.date == today
        ).scalar()
        
        return {
            "status": "online",
            "service": "orb_scanner",
            "timestamp": datetime.now(ET).isoformat(),
            "database": {
                "daily_bars_count": daily_bar_count,
                "symbols_count": symbol_count,
                "latest_bar_date": str(latest_bar) if latest_bar else None,
                "todays_or_count": todays_or_count,
            },
        }
    finally:
        db.close()
