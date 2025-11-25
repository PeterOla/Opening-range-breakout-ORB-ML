"""
Signals API endpoints.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
from datetime import datetime

from db.database import get_db
from db.models import Signal, OrderStatus
from shared.schemas import SignalResponse

router = APIRouter()


@router.get("/signals", response_model=List[SignalResponse])
async def get_signals(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Get recent signals."""
    signals = db.query(Signal).order_by(
        desc(Signal.timestamp)
    ).offset(offset).limit(limit).all()
    
    return [
        SignalResponse(
            id=s.id,
            timestamp=s.timestamp,
            ticker=s.ticker,
            side=s.side.value,
            confidence=s.confidence,
            entry_price=s.entry_price,
            status=s.status.value,
            filled_price=s.filled_price,
            filled_time=s.filled_time,
            rejection_reason=s.rejection_reason
        )
        for s in signals
    ]


@router.get("/signals/active", response_model=List[SignalResponse])
async def get_active_signals(db: Session = Depends(get_db)):
    """Get active/pending signals from today."""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    signals = db.query(Signal).filter(
        Signal.timestamp >= today_start,
        Signal.status.in_([OrderStatus.PENDING, OrderStatus.PARTIAL])
    ).order_by(desc(Signal.timestamp)).all()
    
    return [
        SignalResponse(
            id=s.id,
            timestamp=s.timestamp,
            ticker=s.ticker,
            side=s.side.value,
            confidence=s.confidence,
            entry_price=s.entry_price,
            status=s.status.value,
            filled_price=s.filled_price,
            filled_time=s.filled_time,
            rejection_reason=s.rejection_reason
        )
        for s in signals
    ]
