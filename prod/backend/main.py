"""
FastAPI main entry point for ORB trading system.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import positions, account, trades, signals, metrics, system
from api.websocket import router as ws_router
from db.database import engine, Base
from core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("Starting ORB Trading System")
    logger.info(f"Paper Mode: {settings.ALPACA_PAPER}")
    logger.info(f"Database: {settings.DATABASE_URL}")
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    
    yield
    
    # Shutdown
    logger.info("Shutting down ORB Trading System")


app = FastAPI(
    title="ORB Trading System API",
    description="Opening Range Breakout automated trading system with Alpaca",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
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
app.include_router(system.router, prefix="/api", tags=["System"])
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
