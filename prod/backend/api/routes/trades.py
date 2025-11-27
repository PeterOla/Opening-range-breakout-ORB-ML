"""
Trades API endpoints.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, timedelta

from db.database import get_db
from db.models import Trade, PositionStatus
from shared.schemas import TradeResponse

router = APIRouter()


@router.get("/trades", response_model=List[TradeResponse])
async def get_trades(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    ticker: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get historical trades with pagination and filters."""
    query = db.query(Trade)
    
    # Apply filters
    if status:
        query = query.filter(Trade.status == status)
    if ticker:
        query = query.filter(Trade.ticker == ticker)
    
    # Order by most recent first
    query = query.order_by(desc(Trade.trade_date))
    
    # Pagination
    trades = query.offset(offset).limit(limit).all()
    
    return [
        TradeResponse(
            id=t.id,
            timestamp=t.trade_date,
            ticker=t.ticker,
            side=t.side.value,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            shares=t.shares,
            pnl=t.pnl,
            status=t.status.value,
            duration=(t.exit_time - t.entry_time).total_seconds() / 60 if t.exit_time else None
        )
        for t in trades
    ]


@router.get("/trades/today", response_model=List[TradeResponse])
async def get_today_trades(db: Session = Depends(get_db)):
    """Get trades from today only."""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    trades = db.query(Trade).filter(
        Trade.trade_date >= today_start
    ).order_by(desc(Trade.trade_date)).all()
    
    return [
        TradeResponse(
            id=t.id,
            timestamp=t.trade_date,
            ticker=t.ticker,
            side=t.side.value,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            shares=t.shares,
            pnl=t.pnl,
            status=t.status.value,
            duration=(t.exit_time - t.entry_time).total_seconds() / 60 if t.exit_time else None
        )
        for t in trades
    ]
