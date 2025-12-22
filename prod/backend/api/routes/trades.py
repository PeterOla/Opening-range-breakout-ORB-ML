"""Trades API endpoints.

Trade history is stored in the legacy SQL database.
When STATE_STORE=duckdb (DuckDB-only live mode), these endpoints are disabled.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from core.config import settings
from shared.schemas import TradeResponse


router = APIRouter()


def _sql_enabled() -> bool:
    return (getattr(settings, "STATE_STORE", "duckdb") or "duckdb").lower() != "duckdb"


@router.get("/trades", response_model=List[TradeResponse])
async def get_trades(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    ticker: Optional[str] = None,
):
    """Get historical trades with pagination and filters."""
    if not _sql_enabled():
        raise HTTPException(status_code=501, detail="Trades history is disabled when STATE_STORE=duckdb")

    from sqlalchemy import desc
    from db.database import SessionLocal
    from db.models import Trade

    db = SessionLocal()
    try:
        query = db.query(Trade)
        if status:
            query = query.filter(Trade.status == status)
        if ticker:
            query = query.filter(Trade.ticker == ticker)

        trades = query.order_by(desc(Trade.timestamp)).offset(int(offset)).limit(int(limit)).all()

        return [
            TradeResponse(
                id=t.id,
                timestamp=t.timestamp,
                ticker=t.ticker,
                side=t.side.value,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                shares=t.shares,
                pnl=t.pnl,
                status=t.status.value,
                duration=(t.exit_time - t.entry_time).total_seconds() / 60 if t.exit_time else None,
            )
            for t in trades
        ]
    finally:
        db.close()


@router.get("/trades/today", response_model=List[TradeResponse])
async def get_today_trades():
    """Get trades from today only."""
    if not _sql_enabled():
        raise HTTPException(status_code=501, detail="Trades history is disabled when STATE_STORE=duckdb")

    from sqlalchemy import desc
    from db.database import SessionLocal
    from db.models import Trade

    db = SessionLocal()
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        trades = db.query(Trade).filter(
            Trade.timestamp >= today_start
        ).order_by(desc(Trade.timestamp)).all()

        return [
            TradeResponse(
                id=t.id,
                timestamp=t.timestamp,
                ticker=t.ticker,
                side=t.side.value,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                shares=t.shares,
                pnl=t.pnl,
                status=t.status.value,
                duration=(t.exit_time - t.entry_time).total_seconds() / 60 if t.exit_time else None,
            )
            for t in trades
        ]
    finally:
        db.close()
