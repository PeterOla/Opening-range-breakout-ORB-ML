"""
Scanner API routes.
Endpoints for running ORB stock scanner and data sync.
"""
from fastapi import APIRouter, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from services.orb_scanner import scan_orb_candidates, get_todays_candidates
from services.historical_scanner import (
    get_historical_top20,
    get_scanner_mode,
    get_historical_top20_stream,
    get_premarket_candidates,
)
from services.data_sync import (
    sync_daily_bars_from_alpaca,
    cleanup_old_bars,
    get_universe_with_metrics,
)
from services.ticker_sync import (
    sync_tickers_from_alpaca,
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


@router.get("/today/live")
async def get_today_live_pnl(
    top_n: int = Query(20, ge=1, le=100),
):
    """
    Get today's candidates with live prices and unrealized P&L.
    
    For each candidate that would have been entered:
    - Fetches current price from Alpaca
    - Calculates unrealized P&L (% and $)
    - Shows if stop would have been hit
    
    Use this during live trading hours for real-time P&L tracking.
    """
    from services.orb_scanner import get_todays_candidates_with_live_pnl
    
    candidates = await get_todays_candidates_with_live_pnl(top_n)
    
    # Calculate summary stats
    total_pnl_pct = 0
    total_dollar_pnl = 0
    total_base_dollar_pnl = 0
    total_leverage = 0
    winners = 0
    losers = 0
    trades_entered = 0
    
    for c in candidates:
        if c.get("entered"):
            trades_entered += 1
            pnl = c.get("pnl_pct", 0)
            total_pnl_pct += pnl
            total_dollar_pnl += c.get("dollar_pnl", 0)
            total_base_dollar_pnl += c.get("base_dollar_pnl", 0)
            total_leverage += c.get("leverage", 2.0)
            if pnl > 0:
                winners += 1
            elif pnl < 0:
                losers += 1
    
    return {
        "status": "success",
        "timestamp": datetime.now(ET).isoformat(),
        "count": len(candidates),
        "candidates": candidates,
        "summary": {
            "total_candidates": len(candidates),
            "trades_entered": trades_entered,
            "winners": winners,
            "losers": losers,
            "win_rate": round(winners / trades_entered * 100, 1) if trades_entered > 0 else 0,
            "total_pnl_pct": round(total_pnl_pct, 2),
            "avg_pnl_pct": round(total_pnl_pct / trades_entered, 2) if trades_entered > 0 else 0,
            "total_dollar_pnl": round(total_dollar_pnl, 2),
            "base_dollar_pnl": round(total_base_dollar_pnl, 2),
            "avg_leverage": round(total_leverage / trades_entered, 2) if trades_entered > 0 else 0,
        },
    }


@router.get("/mode")
async def get_mode():
    """
    Get the current scanner mode based on time of day.
    
    Modes:
    - premarket: 04:00-09:35 ET - Show universe candidates (no ORB yet)
    - live: 09:35-16:00 ET - Real-time scanning (requires subscription)
    - historical_today: After 16:00 ET - Today's results with P&L
    - historical_previous: Before 04:00 ET or fallback - Previous day results
    """
    mode_info = get_scanner_mode()
    return {
        "status": "success",
        **mode_info,
    }


@router.get("/premarket")
async def get_premarket():
    """
    Get pre-market universe candidates (04:00 - 09:35 ET).
    
    Shows stocks that pass daily filters (ATR, volume) and could make Top 20
    once RVOL is calculated at 9:35 ET.
    
    Ranked by avg volume as proxy until opening range data is available.
    """
    result = await get_premarket_candidates()
    return result


@router.get("/historical/{date}")
async def get_historical_scan(
    date: str,
    top_n: int = Query(20, ge=1, le=100),
):
    """
    Get historical Top 20 candidates for a specific date with P&L.
    
    Date format: YYYY-MM-DD
    Returns candidates with entry, stop, exit prices and actual P&L.
    Results are saved to database (simulated_trades table).
    """
    result = await get_historical_top20(date, top_n)
    return result


@router.get("/historical/{date}/stream")
async def get_historical_scan_stream(
    date: str,
    top_n: int = Query(20, ge=1, le=100),
    force_refresh: bool = Query(False, description="Bypass cache and refetch data"),
):
    """
    Stream progress while calculating historical Top 20 candidates.
    
    Uses Server-Sent Events (SSE) to stream progress updates.
    Events:
    - progress: {step, message, percent, detail}
    - result: final data (same as /historical/{date})
    - error: {message}
    
    Set force_refresh=true to bypass cache.
    """
    return StreamingResponse(
        get_historical_top20_stream(date, top_n, force_refresh=force_refresh),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/simulated-trades")
async def get_simulated_trades(
    start_date: str = Query(None, description="Start date YYYY-MM-DD"),
    end_date: str = Query(None, description="End date YYYY-MM-DD"),
    ticker: str = Query(None, description="Filter by ticker"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
):
    """
    Query saved simulated trades from the database.
    
    These are historical "what if" trades - NOT actual live trades.
    Use this for performance analysis, equity curves, etc.
    """
    from db.database import SessionLocal
    from db.models import SimulatedTrade
    from sqlalchemy import desc, and_
    
    db = SessionLocal()
    try:
        query = db.query(SimulatedTrade)
        
        filters = []
        if start_date:
            filters.append(SimulatedTrade.trade_date >= datetime.strptime(start_date, "%Y-%m-%d"))
        if end_date:
            filters.append(SimulatedTrade.trade_date <= datetime.strptime(end_date, "%Y-%m-%d"))
        if ticker:
            filters.append(SimulatedTrade.ticker == ticker.upper())
        
        if filters:
            query = query.filter(and_(*filters))
        
        trades = query.order_by(desc(SimulatedTrade.trade_date), SimulatedTrade.rvol_rank).limit(limit).all()
        
        # Aggregate stats
        total_pnl = sum(t.pnl_pct or 0 for t in trades)
        entered = [t for t in trades if t.exit_reason and t.exit_reason != "NO_ENTRY"]
        winners = [t for t in entered if (t.pnl_pct or 0) > 0]
        losers = [t for t in entered if (t.pnl_pct or 0) < 0]
        
        return {
            "status": "success",
            "count": len(trades),
            "summary": {
                "total_trades": len(trades),
                "trades_entered": len(entered),
                "winners": len(winners),
                "losers": len(losers),
                "win_rate": round(len(winners) / len(entered) * 100, 1) if entered else 0,
                "total_pnl_pct": round(total_pnl, 2),
                "avg_pnl_pct": round(total_pnl / len(entered), 2) if entered else 0,
            },
            "trades": [
                {
                    "id": t.id,
                    "date": str(t.trade_date.date()) if t.trade_date else None,
                    "ticker": t.ticker,
                    "side": t.side.value if t.side else None,
                    "rank": t.rvol_rank,
                    "rvol": t.rvol,
                    "entry_price": t.entry_price,
                    "stop_price": t.stop_price,
                    "exit_price": t.exit_price,
                    "exit_reason": t.exit_reason,
                    "pnl_pct": t.pnl_pct,
                    "is_simulated": True,  # Always true for this table
                }
                for t in trades
            ],
        }
    finally:
        db.close()


@router.get("/simulated-trades/summary")
async def get_simulated_trades_summary():
    """
    Get daily aggregated P&L from simulated trades.
    
    Useful for equity curve plotting.
    """
    from db.database import SessionLocal
    from db.models import SimulatedTrade
    from sqlalchemy import func, and_
    
    db = SessionLocal()
    try:
        # Daily P&L aggregation
        daily_stats = db.query(
            func.date(SimulatedTrade.trade_date).label("date"),
            func.count(SimulatedTrade.id).label("total_candidates"),
            func.sum(
                func.case(
                    (SimulatedTrade.exit_reason != "NO_ENTRY", 1),
                    else_=0
                )
            ).label("trades_entered"),
            func.sum(
                func.case(
                    (and_(SimulatedTrade.pnl_pct != None, SimulatedTrade.pnl_pct > 0), 1),
                    else_=0
                )
            ).label("winners"),
            func.sum(SimulatedTrade.pnl_pct).label("total_pnl"),
        ).group_by(
            func.date(SimulatedTrade.trade_date)
        ).order_by(
            func.date(SimulatedTrade.trade_date)
        ).all()
        
        results = []
        cumulative_pnl = 0
        
        for row in daily_stats:
            day_pnl = row.total_pnl or 0
            cumulative_pnl += day_pnl
            entered = row.trades_entered or 0
            winners = row.winners or 0
            
            results.append({
                "date": str(row.date),
                "total_candidates": row.total_candidates,
                "trades_entered": entered,
                "winners": winners,
                "losers": entered - winners,
                "win_rate": round(winners / entered * 100, 1) if entered > 0 else 0,
                "day_pnl_pct": round(day_pnl, 2),
                "cumulative_pnl_pct": round(cumulative_pnl, 2),
            })
        
        return {
            "status": "success",
            "days": len(results),
            "total_pnl_pct": round(cumulative_pnl, 2),
            "daily_summary": results,
        }
    finally:
        db.close()


# ============ Data Sync Endpoints ============

@router.post("/sync-tickers")
async def sync_tickers():
    """
    Sync active stock ticker universe from Polygon/Massive.
    
    Fetches all active NYSE/NASDAQ common stocks and stores in database.
    Run this once to populate the universe, then periodically to update.
    
    Runs as background task - returns immediately.
    Check /scanner/ticker-stats to monitor progress.
    Expected result: ~5,000-6,000 active common stocks.
    """
    import asyncio
    
    # Fire and forget - run sync in background
    asyncio.create_task(_run_ticker_sync())
    
    return {
        "status": "started",
        "message": "Ticker sync started in background. Check /scanner/ticker-stats to monitor progress.",
    }


async def _run_ticker_sync():
    """Background task for ticker sync."""
    try:
        result = await sync_tickers_from_alpaca()
        print(f"✓ Ticker sync completed: {result}")
    except Exception as e:
        print(f"✗ Ticker sync failed: {e}")
        import traceback
        traceback.print_exc()


@router.post("/sync-daily")
async def sync_daily_data(
    lookback_days: int = Query(14, ge=7, le=30, description="Number of days to fetch"),
):
    """
    Sync daily bars for ALL stocks from Alpaca.
    
    Uses Alpaca Historical Data API.
    
    This is the recommended method for nightly sync:
    - Fetches OHLCV for all active stocks
    - Computes ATR(14) and avg_volume(14) for each symbol
    
    Runs as background task - returns immediately.
    Check /scanner/health to monitor progress.
    
    Use cases:
    - Initial setup: Run with lookback_days=14
    - Daily refresh: Run with lookback_days=3 (catches up weekends)
    """
    import asyncio
    
    # Fire and forget - run sync in background
    asyncio.create_task(_run_daily_sync(lookback_days))
    
    return {
        "status": "started",
        "message": f"Daily bars sync started in background ({lookback_days} days). Check /scanner/health to monitor progress.",
        "lookback_days": lookback_days,
    }


async def _run_daily_sync(lookback_days: int):
    """Background task for daily bars sync."""
    try:
        result = await sync_daily_bars_from_alpaca(lookback_days=lookback_days)
        print(f"✓ Daily bars sync completed: {result}")
        
        # Update filter flags after sync
        if result.get("status") == "success":
            await update_ticker_filters()
            print("✓ Ticker filters updated")
    except Exception as e:
        print(f"✗ Daily bars sync failed: {e}")
        import traceback
        traceback.print_exc()


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
    Sync daily bars from Alpaca for specified symbols (or all active tickers).
    
    If no symbols provided, uses active tickers from database.
    Requires /scanner/sync-tickers to be run first if using DB tickers.
    
    This may take several minutes depending on the number of symbols.
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
    
    result = await sync_daily_bars_from_alpaca(
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


@router.delete("/cleanup-orphans")
async def cleanup_orphan_bars():
    """
    Delete daily bars for symbols not in active ticker list.
    Use after re-syncing tickers to remove stale data.
    """
    from db.database import SessionLocal
    from db.models import DailyBar, Ticker
    from sqlalchemy import func
    
    db = SessionLocal()
    try:
        # Get active ticker symbols
        active_symbols = [row[0] for row in db.query(Ticker.symbol).filter(Ticker.active == True).all()]
        
        if not active_symbols:
            return {"status": "error", "error": "No active tickers found"}
        
        # Count orphans before delete
        orphan_count = db.query(func.count(DailyBar.id)).filter(
            ~DailyBar.symbol.in_(active_symbols)
        ).scalar()
        
        # Delete bars for symbols not in active list
        deleted = db.query(DailyBar).filter(
            ~DailyBar.symbol.in_(active_symbols)
        ).delete(synchronize_session=False)
        
        db.commit()
        
        return {
            "status": "success",
            "orphan_bars_deleted": deleted,
            "active_tickers": len(active_symbols),
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@router.delete("/cleanup-duplicates")
async def cleanup_duplicate_bars():
    """
    Delete duplicate daily bars (same symbol + date).
    Keeps the bar with the highest ID (most recent insert).
    """
    from db.database import SessionLocal
    from db.models import DailyBar
    from sqlalchemy import func, and_
    
    db = SessionLocal()
    try:
        # Find duplicates: group by symbol + date, count > 1
        print("🔍 Scanning for duplicate bars...")
        duplicates = db.query(
            DailyBar.symbol,
            DailyBar.date,
            func.count(DailyBar.id).label('count'),
            func.max(DailyBar.id).label('keep_id')
        ).group_by(
            DailyBar.symbol, DailyBar.date
        ).having(
            func.count(DailyBar.id) > 1
        ).all()
        
        if not duplicates:
            print("✓ No duplicates found")
            return {
                "status": "success",
                "message": "No duplicates found",
                "duplicates_deleted": 0,
            }
        
        print(f"Found {len(duplicates)} symbol+date combinations with duplicates")
        
        total_deleted = 0
        batch_size = 500
        
        for i, dup in enumerate(duplicates):
            # Delete all bars for this symbol+date except the one with highest ID
            deleted = db.query(DailyBar).filter(
                and_(
                    DailyBar.symbol == dup.symbol,
                    DailyBar.date == dup.date,
                    DailyBar.id != dup.keep_id
                )
            ).delete(synchronize_session=False)
            total_deleted += deleted
            
            # Progress log every batch_size items
            if (i + 1) % batch_size == 0:
                db.commit()  # Commit in batches for large datasets
                print(f"  [{i + 1}/{len(duplicates)}] Deleted {total_deleted} duplicates so far...")
        
        db.commit()
        
        print(f"✓ Deleted {total_deleted} duplicate bars from {len(duplicates)} combinations")
        
        return {
            "status": "success",
            "duplicate_combinations": len(duplicates),
            "duplicates_deleted": total_deleted,
        }
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


# ============ Ticker Data Endpoints ============

@router.get("/tickers/list")
async def list_all_tickers(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=10, le=200, description="Items per page"),
    search: str = Query(None, description="Search by symbol or name"),
    exchange: str = Query(None, description="Filter by exchange (XNYS, XNAS)"),
    qualified: bool = Query(None, description="Filter to only qualified tickers (meets all filters)"),
    sort_by: str = Query("symbol", description="Sort field"),
    sort_order: str = Query("asc", description="Sort order (asc/desc)"),
):
    """
    Get paginated list of all tickers with details.
    """
    from db.database import SessionLocal
    from db.models import Ticker, DailyBar
    from sqlalchemy import func, desc, asc, and_
    
    db = SessionLocal()
    try:
        # Base query
        query = db.query(Ticker).filter(Ticker.active == True)
        
        # Apply qualified filter (meets all filters: price >= $5, vol >= 1M, ATR >= $0.50)
        if qualified:
            query = query.filter(
                Ticker.meets_price_filter == True,
                Ticker.meets_volume_filter == True,
                Ticker.meets_atr_filter == True,
            )
        
        # Apply search filter
        if search:
            search_term = f"%{search.upper()}%"
            query = query.filter(
                (Ticker.symbol.ilike(search_term)) | 
                (Ticker.name.ilike(f"%{search}%"))
            )
        
        # Apply exchange filter
        if exchange:
            query = query.filter(Ticker.primary_exchange == exchange)
        
        # Get total count
        total = query.count()
        
        # Apply sorting
        sort_col = getattr(Ticker, sort_by, Ticker.symbol)
        if sort_order == "desc":
            query = query.order_by(desc(sort_col))
        else:
            query = query.order_by(asc(sort_col))
        
        # Apply pagination
        offset = (page - 1) * per_page
        tickers = query.offset(offset).limit(per_page).all()
        
        # Get latest bar data for these tickers
        symbols = [t.symbol for t in tickers]
        
        # Subquery for latest bar per symbol
        subq = db.query(
            DailyBar.symbol,
            func.max(DailyBar.date).label("max_date")
        ).filter(DailyBar.symbol.in_(symbols)).group_by(DailyBar.symbol).subquery()
        
        latest_bars = db.query(DailyBar).join(
            subq,
            and_(
                DailyBar.symbol == subq.c.symbol,
                DailyBar.date == subq.c.max_date,
            )
        ).all()
        
        bar_lookup = {b.symbol: b for b in latest_bars}
        
        # Build response
        results = []
        for t in tickers:
            bar = bar_lookup.get(t.symbol)
            results.append({
                "symbol": t.symbol,
                "name": t.name,
                "exchange": t.primary_exchange,
                "type": t.type,
                "price": bar.close if bar else None,
                "atr_14": bar.atr_14 if bar else None,
                "avg_volume_14": bar.avg_volume_14 if bar else None,
                "latest_date": str(bar.date) if bar else None,
                "meets_filters": t.meets_price_filter and t.meets_volume_filter and t.meets_atr_filter,
            })
        
        return {
            "status": "success",
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
            "tickers": results,
        }
    finally:
        db.close()


@router.get("/tickers/{symbol}")
async def get_ticker_detail(symbol: str):
    """
    Get full details for a single ticker including price history.
    """
    from db.database import SessionLocal
    from db.models import Ticker, DailyBar
    from sqlalchemy import desc
    
    db = SessionLocal()
    try:
        # Get ticker info
        ticker = db.query(Ticker).filter(Ticker.symbol == symbol.upper()).first()
        if not ticker:
            return {"status": "error", "error": f"Ticker {symbol} not found"}
        
        # Get price history (last 30 days)
        bars = db.query(DailyBar).filter(
            DailyBar.symbol == symbol.upper()
        ).order_by(desc(DailyBar.date)).limit(30).all()
        
        # Reverse to chronological order
        bars = list(reversed(bars))
        
        # Latest bar for current metrics
        latest = bars[-1] if bars else None
        
        return {
            "status": "success",
            "ticker": {
                "symbol": ticker.symbol,
                "name": ticker.name,
                "exchange": ticker.primary_exchange,
                "type": ticker.type,
                "active": ticker.active,
                "cik": ticker.cik,
                "currency": ticker.currency,
            },
            "metrics": {
                "price": latest.close if latest else None,
                "atr_14": latest.atr_14 if latest else None,
                "avg_volume_14": latest.avg_volume_14 if latest else None,
                "latest_date": str(latest.date) if latest else None,
                "meets_price_filter": ticker.meets_price_filter,
                "meets_volume_filter": ticker.meets_volume_filter,
                "meets_atr_filter": ticker.meets_atr_filter,
            },
            "price_history": [
                {
                    "date": str(b.date),
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in bars
            ],
        }
    finally:
        db.close()


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
        oldest_bar = db.query(func.min(DailyBar.date)).scalar()
        trading_days = db.query(func.count(func.distinct(DailyBar.date))).scalar()
        
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
                "oldest_bar_date": str(oldest_bar) if oldest_bar else None,
                "latest_bar_date": str(latest_bar) if latest_bar else None,
                "trading_days": trading_days,
                "avg_bars_per_symbol": round(daily_bar_count / symbol_count, 1) if symbol_count else 0,
                "todays_or_count": todays_or_count,
            },
        }
    finally:
        db.close()
