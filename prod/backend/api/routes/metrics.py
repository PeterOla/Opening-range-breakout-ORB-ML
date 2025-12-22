"""
Metrics API endpoints.
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta

from shared.schemas import MetricsResponse
from core.config import settings

router = APIRouter()


def _sql_enabled() -> bool:
    return (getattr(settings, "STATE_STORE", "duckdb") or "duckdb").lower() != "duckdb"


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(days: int = 30):
    """Get performance metrics for specified period."""
    if not _sql_enabled():
        raise HTTPException(status_code=501, detail="Metrics are disabled when STATE_STORE=duckdb")

    from db.database import SessionLocal
    from db.models import Trade, PositionStatus

    db = SessionLocal()
    try:
        cutoff_date = datetime.now() - timedelta(days=days)
        
        # Get closed trades
        trades = db.query(Trade).filter(
            Trade.status == PositionStatus.CLOSED,
            Trade.timestamp >= cutoff_date
        ).all()
        
        if not trades:
            return MetricsResponse(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0
            )
        
        # Calculate metrics
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.pnl and t.pnl > 0)
        losing_trades = sum(1 for t in trades if t.pnl and t.pnl < 0)
        
        wins = [t.pnl for t in trades if t.pnl and t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl and t.pnl < 0]
        
        total_pnl = sum(t.pnl for t in trades if t.pnl)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        # Simple Sharpe approximation (needs daily returns for proper calc)
        pnls = [t.pnl for t in trades if t.pnl]
        if len(pnls) > 1:
            import numpy as np
            returns = np.array(pnls)
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if np.std(returns) > 0 else 0.0
        else:
            sharpe = 0.0
        
        # Max drawdown (simplified)
        cumulative_pnl = 0
        peak = 0
        max_dd = 0
        for t in trades:
            if t.pnl:
                cumulative_pnl += t.pnl
                if cumulative_pnl > peak:
                    peak = cumulative_pnl
                dd = peak - cumulative_pnl
                if dd > max_dd:
                    max_dd = dd
        
        return MetricsResponse(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=round(win_rate, 2),
            total_pnl=round(total_pnl, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            sharpe_ratio=round(sharpe, 2),
            max_drawdown=round(max_dd, 2)
        )
    finally:
        db.close()
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Get closed trades
    trades = db.query(Trade).filter(
        Trade.status == PositionStatus.CLOSED,
        Trade.timestamp >= cutoff_date
    ).all()
    
    if not trades:
        return MetricsResponse(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0
        )
    
    # Calculate metrics
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t.pnl and t.pnl > 0)
    losing_trades = sum(1 for t in trades if t.pnl and t.pnl < 0)
    
    wins = [t.pnl for t in trades if t.pnl and t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl and t.pnl < 0]
    
    total_pnl = sum(t.pnl for t in trades if t.pnl)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    
    # Simple Sharpe approximation (needs daily returns for proper calc)
    pnls = [t.pnl for t in trades if t.pnl]
    if len(pnls) > 1:
        import numpy as np
        returns = np.array(pnls)
        sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if np.std(returns) > 0 else 0.0
    else:
        sharpe = 0.0
    
    # Max drawdown (simplified)
    cumulative_pnl = 0
    peak = 0
    max_dd = 0
    for t in trades:
        if t.pnl:
            cumulative_pnl += t.pnl
            if cumulative_pnl > peak:
                peak = cumulative_pnl
            dd = peak - cumulative_pnl
            if dd > max_dd:
                max_dd = dd
    
    return MetricsResponse(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=round(win_rate, 2),
        total_pnl=round(total_pnl, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        sharpe_ratio=round(sharpe, 2),
        max_drawdown=round(max_dd, 2)
    )
