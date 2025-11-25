"""
Positions API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from db.database import get_db
from db.models import Trade, PositionStatus
from execution.alpaca_client import get_alpaca_client
from shared.schemas import PositionResponse

router = APIRouter()


@router.get("/positions", response_model=List[PositionResponse])
async def get_open_positions(db: Session = Depends(get_db)):
    """Get all open positions from Alpaca and database."""
    try:
        # Get live positions from Alpaca
        client = get_alpaca_client()
        alpaca_positions = client.get_all_positions()
        
        # Convert to response format
        positions = []
        for pos in alpaca_positions:
            positions.append(PositionResponse(
                ticker=pos.symbol,
                side="LONG" if float(pos.qty) > 0 else "SHORT",
                shares=abs(int(pos.qty)),
                entry_price=float(pos.avg_entry_price),
                current_price=float(pos.current_price),
                pnl=float(pos.unrealized_pl),
                pnl_pct=float(pos.unrealized_plpc) * 100
            ))
        
        return positions
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch positions: {str(e)}")


@router.get("/positions/{ticker}", response_model=PositionResponse)
async def get_position(ticker: str, db: Session = Depends(get_db)):
    """Get specific position by ticker."""
    try:
        client = get_alpaca_client()
        pos = client.get_open_position(ticker)
        
        return PositionResponse(
            ticker=pos.symbol,
            side="LONG" if float(pos.qty) > 0 else "SHORT",
            shares=abs(int(pos.qty)),
            entry_price=float(pos.avg_entry_price),
            current_price=float(pos.current_price),
            pnl=float(pos.unrealized_pl),
            pnl_pct=float(pos.unrealized_plpc) * 100
        )
        
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Position not found: {str(e)}")


@router.post("/positions/{ticker}/close")
async def close_position(ticker: str, db: Session = Depends(get_db)):
    """Manually close a position."""
    try:
        client = get_alpaca_client()
        order = client.close_position(ticker)
        
        return {
            "status": "success",
            "message": f"Position {ticker} closed",
            "order_id": order.id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to close position: {str(e)}")
