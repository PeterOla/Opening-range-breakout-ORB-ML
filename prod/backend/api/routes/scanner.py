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
    cleanup_old_bars,
    get_universe_with_metrics,
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
    symbols: list[str]
    lookback_days: int = 30


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

@router.post("/sync")
async def sync_daily_bars(request: DataSyncRequest):
    """
    Sync daily bars from Polygon for specified symbols.
    
    This may take several minutes depending on the number of symbols
    and API rate limits (5 calls/min for Polygon Starter).
    """
    result = await sync_universe_daily_bars(
        symbols=request.symbols,
        lookback_days=request.lookback_days,
    )
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
