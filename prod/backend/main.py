"""
FastAPI main entry point for ORB trading system.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import positions, account, trades, signals, metrics, system, execution
from api.websocket import router as ws_router
from core.config import settings
from services.scheduler import start_scheduler, stop_scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    import asyncio
    
    # Startup
    logger.info("Starting ORB Trading System")
    logger.info(f"Paper Mode: {settings.ALPACA_PAPER}")
    logger.info(f"State Store: {getattr(settings, 'STATE_STORE', 'duckdb')}")
    if (getattr(settings, "STATE_STORE", "duckdb") or "duckdb").lower() != "duckdb":
        logger.info(f"Database: {settings.DATABASE_URL}")

        from db.database import engine, Base

        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created")
    
    # Start EOD scheduler
    start_scheduler()
    logger.info("EOD scheduler started")
    
    # Check if we need initial data sync
    if (getattr(settings, "STATE_STORE", "duckdb") or "duckdb").lower() != "duckdb":
        asyncio.create_task(_check_and_sync_data())

    # Check for stale data (All stores) - Ensure we have data up to the last market close
    asyncio.create_task(_check_data_freshness())
    
    yield
    
    # Shutdown
    stop_scheduler()
    logger.info("Shutting down ORB Trading System")


async def _check_and_sync_data():
    """Check if database is empty and auto-trigger sync."""
    import asyncio
    await asyncio.sleep(2)  # Let server fully start
    
    from db.database import SessionLocal
    from db.models import Ticker, DailyBar
    from sqlalchemy import func
    
    db = SessionLocal()
    try:
        ticker_count = db.query(func.count(Ticker.id)).scalar() or 0
        bar_count = db.query(func.count(DailyBar.id)).scalar() or 0
        
        logger.info(f"📊 Data check: {ticker_count} tickers, {bar_count} daily bars")
        
        if ticker_count == 0:
            logger.info("🔄 No tickers found - starting auto-sync from Alpaca...")
            from services.ticker_sync import sync_tickers_from_alpaca
            result = await sync_tickers_from_alpaca()
            logger.info(f"✓ Ticker sync complete: {result}")
            
            # After tickers synced, sync daily bars
            logger.info("🔄 Starting daily bars sync from Alpaca...")
            from services.data_sync import sync_daily_bars_from_alpaca
            result = await sync_daily_bars_from_alpaca(lookback_days=30)
            logger.info(f"✓ Daily bars sync complete: {result}")
            
            # Update filter flags
            from services.ticker_sync import update_ticker_filters
            await update_ticker_filters()
            logger.info("✓ Ticker filters updated")
            
        elif bar_count == 0:
            logger.info("🔄 No daily bars found - starting auto-sync from Alpaca...")
            from services.data_sync import sync_daily_bars_from_alpaca
            result = await sync_daily_bars_from_alpaca(lookback_days=30)
            logger.info(f"✓ Daily bars sync complete: {result}")
            
            from services.ticker_sync import update_ticker_filters
            await update_ticker_filters()
            logger.info("✓ Ticker filters updated")
        else:
            logger.info("✓ Data already synced - skipping auto-sync")
            
    except Exception as e:
        logger.error(f"Auto-sync error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


app = FastAPI(
    title="ORB Trading System API",
    description="Opening Range Breakout automated trading system with Alpaca",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(positions.router, prefix="/api", tags=["Positions"])
app.include_router(account.router, prefix="/api", tags=["Account"])
app.include_router(trades.router, prefix="/api", tags=["Trades"])
app.include_router(signals.router, prefix="/api", tags=["Signals"])
app.include_router(metrics.router, prefix="/api", tags=["Metrics"])
app.include_router(system.router, prefix="/api/system", tags=["System"])

# Scanner router depends on STATE_STORE.
if (getattr(settings, "STATE_STORE", "duckdb") or "duckdb").lower() == "duckdb":
    from api.routes import scanner_duckdb as scanner
else:
    from api.routes import scanner

app.include_router(scanner.router, prefix="/api", tags=["Scanner"])
app.include_router(execution.router, prefix="/api", tags=["Execution"])
app.include_router(ws_router, prefix="/ws", tags=["WebSocket"])

if (getattr(settings, "STATE_STORE", "duckdb") or "duckdb").lower() != "duckdb":
    from routers.analytics import router as analytics_router

    app.include_router(analytics_router, tags=["Analytics"])


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "online",
        "version": "1.0.0",
        "paper_mode": settings.ALPACA_PAPER
    }


@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "state_store": (getattr(settings, "STATE_STORE", "duckdb") or "duckdb"),
        "database": "disabled" if (getattr(settings, "STATE_STORE", "duckdb") or "duckdb").lower() == "duckdb" else "enabled",
        "alpaca": "connected" if settings.ALPACA_API_KEY else "not_configured"
    }


async def _check_data_freshness():
    """
    Check if data is stale on startup.
    If the last successful sync was before the last market close, trigger a sync.
    """
    import asyncio
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from pathlib import Path
    from services.market_calendar import get_market_calendar
    from services.scheduler import job_nightly_data_sync

    # Wait for server to start
    await asyncio.sleep(5)

    logger.info("🔍 Checking data freshness...")
    
    try:
        calendar = get_market_calendar()
        et = ZoneInfo("America/New_York")
        now_et = datetime.now(et)
        today = now_et.date()
        
        # Determine the "target" sync date (the date of the data we MUST have)
        today_schedule = calendar.get_calendar_for_date(today)
        
        target_data_date = None
        
        if today_schedule:
            # Market is open today
            # Check if we passed the sync time (6:00 PM ET)
            sync_cutoff = now_et.replace(hour=18, minute=0, second=0, microsecond=0)
            
            if now_et > sync_cutoff:
                target_data_date = today
            else:
                # Need previous trading day
                target_data_date = _get_previous_trading_day(calendar, today)
        else:
            # Market closed today
            target_data_date = _get_previous_trading_day(calendar, today)
            
        logger.info(f"📅 Target data date (required): {target_data_date}")
        
        if not target_data_date:
            logger.warning("[WARN] Could not determine target data date. Skipping check.")
            return

        # Check last sync time from logs
        # Try to find logs directory relative to current working directory
        possible_log_dirs = [
            Path("logs"),
            Path("../../logs"),
            Path("../../../logs")
        ]
        
        found_log_dir = None
        for d in possible_log_dirs:
            if d.exists() and d.is_dir():
                found_log_dir = d
                break
        
        if not found_log_dir:
            logger.warning("[WARN] Log directory not found, assuming stale data.")
            await job_nightly_data_sync()
            return

        # Find all sync logs (orb_sync_YYYYMMDD_HHMMSS.json)
        sync_logs = list(found_log_dir.glob("orb_sync_*.json"))
        
        last_sync_date = None
        
        if sync_logs:
            # Sort by date in filename
            sync_logs.sort(reverse=True)
            latest_log = sync_logs[0]
            
            # Parse date from filename: orb_sync_20251229_183202.json
            try:
                filename_parts = latest_log.name.split("_")
                if len(filename_parts) >= 3:
                    date_str = filename_parts[2]
                    last_sync_date = datetime.strptime(date_str, "%Y%m%d").date()
            except Exception as e:
                logger.error(f"[ERROR] Failed to parse sync log filename {latest_log}: {e}")

        logger.info(f"[INFO] Last sync date found: {last_sync_date}")

        # Compare
        if last_sync_date is None or last_sync_date < target_data_date:
            logger.warning(f"[WARN] Data is stale! Last sync: {last_sync_date}, Target: {target_data_date}")
            logger.info("[INFO] Triggering auto-sync now...")
            await job_nightly_data_sync()
        else:
            logger.info("[OK] Data is up to date.")

    except Exception as e:
        logger.error(f"[ERROR] Error checking data freshness: {e}")
        import traceback
        traceback.print_exc()


def _get_previous_trading_day(calendar, from_date):
    """Helper to find previous trading day."""
    from datetime import timedelta
    current = from_date - timedelta(days=1)
    for _ in range(10): # Look back 10 days max
        if calendar.get_calendar_for_date(current):
            return current
        current -= timedelta(days=1)
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
        log_level="info"
    )
