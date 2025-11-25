"""
Signals API endpoints.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from db.database import get_db
from db.models import Signal, OrderStatus
from shared.schemas import SignalResponse

router = APIRouter()


class GenerateSignalsRequest(BaseModel):
    """Request body for signal generation."""
    account_equity: Optional[float] = None  # Auto-fetch from Alpaca if not provided
    risk_per_trade_pct: float = 0.01
    max_positions: int = 20


class ExecuteSignalsRequest(BaseModel):
    """Request body for executing signals."""
    signal_ids: Optional[list[int]] = None  # Execute specific signals, or all pending if None


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


@router.post("/signals/generate")
async def generate_signals(request: GenerateSignalsRequest):
    """
    Generate trading signals from today's scanned candidates.
    
    Requires scanner to be run first (/api/scanner/run).
    """
    from services.signal_engine import run_signal_generation
    from execution.order_executor import get_executor
    
    # Get account equity if not provided
    account_equity = request.account_equity
    if account_equity is None:
        executor = get_executor()
        account = executor.get_account()
        account_equity = account.get("equity", 100000)
    
    result = await run_signal_generation(
        account_equity=account_equity,
        risk_per_trade_pct=request.risk_per_trade_pct,
        max_positions=request.max_positions,
    )
    
    return result


@router.post("/signals/execute")
async def execute_signals(request: ExecuteSignalsRequest):
    """
    Execute pending signals by placing orders on Alpaca.
    
    If signal_ids provided, executes only those signals.
    Otherwise, executes all pending signals.
    """
    from services.signal_engine import get_pending_signals
    from execution.order_executor import get_executor
    
    executor = get_executor()
    
    # Check kill switch
    if executor.is_kill_switch_active():
        return {
            "status": "blocked",
            "reason": "Kill switch is active",
            "orders_placed": 0,
        }
    
    # Get pending signals
    pending = get_pending_signals()
    
    if request.signal_ids:
        pending = [s for s in pending if s["id"] in request.signal_ids]
    
    if not pending:
        return {
            "status": "no_signals",
            "message": "No pending signals to execute",
            "orders_placed": 0,
        }
    
    # Execute signals
    results = []
    for signal in pending:
        # We need shares - fetch from the original signal
        from db.database import SessionLocal
        db = SessionLocal()
        try:
            db_signal = db.query(Signal).filter(Signal.id == signal["id"]).first()
            
            # Calculate shares from risk
            from services.signal_engine import calculate_position_size
            account = executor.get_account()
            
            shares = calculate_position_size(
                entry_price=signal["entry_price"],
                stop_price=signal["stop_price"],
                account_equity=account.get("equity", 100000),
            )
            
            if shares > 0:
                result = executor.place_entry_order(
                    symbol=signal["symbol"],
                    side=signal["side"],
                    shares=shares,
                    entry_price=signal["entry_price"],
                    stop_price=signal["stop_price"],
                    signal_id=signal["id"],
                )
                results.append(result)
        finally:
            db.close()
    
    return {
        "status": "success",
        "orders_placed": len([r for r in results if r.get("status") == "submitted"]),
        "orders_failed": len([r for r in results if r.get("status") != "submitted"]),
        "results": results,
    }


@router.get("/signals/pending")
async def get_pending_signals_endpoint():
    """Get all pending signals awaiting execution."""
    from services.signal_engine import get_pending_signals
    
    pending = get_pending_signals()
    return {
        "count": len(pending),
        "signals": pending,
    }
