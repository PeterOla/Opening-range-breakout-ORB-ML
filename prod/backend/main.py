"""
FastAPI main entry point for ORB trading system.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import positions, account, trades, signals, metrics, system, scanner, execution
from api.websocket import router as ws_router
from db.database import engine, Base
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
    logger.info(f"Database: {settings.DATABASE_URL}")
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    
    # Start EOD scheduler
    start_scheduler()
    logger.info("EOD scheduler started")
    
    # Check if we need initial data sync
    asyncio.create_task(_check_and_sync_data())
    
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
            logger.info("🔄 No tickers found - starting auto-sync from Polygon...")
            from services.ticker_sync import sync_tickers_from_polygon
            result = await sync_tickers_from_polygon()
            logger.info(f"✓ Ticker sync complete: {result}")
            
            # After tickers synced, sync daily bars
            logger.info("🔄 Starting daily bars sync...")
            from services.data_sync import sync_daily_bars_fast
            result = await sync_daily_bars_fast(lookback_days=14)
            logger.info(f"✓ Daily bars sync complete: {result}")
            
            # Update filter flags
            from services.ticker_sync import update_ticker_filters
            await update_ticker_filters()
            logger.info("✓ Ticker filters updated")
            
        elif bar_count == 0:
            logger.info("🔄 No daily bars found - starting auto-sync...")
            from services.data_sync import sync_daily_bars_fast
            result = await sync_daily_bars_fast(lookback_days=14)
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
app.include_router(scanner.router, prefix="/api", tags=["Scanner"])
app.include_router(execution.router, prefix="/api", tags=["Execution"])
app.include_router(ws_router, prefix="/ws", tags=["WebSocket"])


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
        "database": "connected",
        "alpaca": "connected" if settings.ALPACA_API_KEY else "not_configured"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
        log_level="info"
    )
