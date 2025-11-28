"""
Execution API endpoints.
Order management, positions, EOD flatten.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from execution.order_executor import get_executor, flatten_eod, calculate_position_size
from core.config import settings


router = APIRouter(prefix="/execution", tags=["execution"])
ET = ZoneInfo("America/New_York")


class OrderRequest(BaseModel):
    """Request body for placing an order."""
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    stop_price: float


class TestOrderRequest(BaseModel):
    """Request for test order."""
    symbol: str = "F"  # Ford - cheap liquid stock
    entry_price: float = 11.00
    stop_price: float = 10.90


@router.post("/test-order")
async def place_test_order(request: TestOrderRequest):
    """
    Place a test order on paper account.
    
    ⚠️ Only works on paper account!
    Uses fixed 2x leverage position sizing.
    """
    if not settings.ALPACA_PAPER:
        return {
            "status": "rejected",
            "reason": "Test orders only allowed on paper account",
        }
    
    # Calculate position size
    sizing = calculate_position_size(request.entry_price, request.stop_price)
    
    if sizing["shares"] < 1:
        return {
            "status": "rejected",
            "reason": "Position size too small (0 shares)",
            "sizing": sizing,
        }
    
    executor = get_executor()
    
    result = executor.place_entry_order(
        symbol=request.symbol.upper(),
        side="LONG",
        shares=sizing["shares"],
        entry_price=request.entry_price,
        stop_price=request.stop_price,
    )
    
    return {
        **result,
        "sizing": sizing,
        "settings": {
            "capital": settings.TRADING_CAPITAL,
            "leverage": settings.FIXED_LEVERAGE,
            "risk_per_trade": settings.RISK_PER_TRADE_PCT,
        },
    }


@router.post("/order")
async def place_order(request: OrderRequest):
    """
    Place an order with automatic position sizing.
    
    Uses fixed 2x leverage from settings.
    """
    # Calculate position size
    sizing = calculate_position_size(request.entry_price, request.stop_price)
    
    if sizing["shares"] < 1:
        return {
            "status": "rejected",
            "reason": "Position size too small (0 shares)",
            "sizing": sizing,
        }
    
    executor = get_executor()
    
    result = executor.place_entry_order(
        symbol=request.symbol.upper(),
        side=request.side.upper(),
        shares=sizing["shares"],
        entry_price=request.entry_price,
        stop_price=request.stop_price,
    )
    
    return {
        **result,
        "sizing": sizing,
    }


@router.get("/sizing")
async def get_position_sizing(
    entry_price: float,
    stop_price: float,
):
    """
    Calculate position sizing for given entry/stop prices.
    
    Useful for previewing trade size before placing.
    """
    sizing = calculate_position_size(entry_price, stop_price)
    
    return {
        "entry_price": entry_price,
        "stop_price": stop_price,
        "sizing": sizing,
        "settings": {
            "capital": settings.TRADING_CAPITAL,
            "leverage": settings.FIXED_LEVERAGE,
            "risk_per_trade_pct": settings.RISK_PER_TRADE_PCT,
            "risk_per_trade_dollars": settings.TRADING_CAPITAL * settings.RISK_PER_TRADE_PCT,
        },
    }


@router.get("/orders")
async def get_open_orders():
    """Get all open orders on Alpaca."""
    executor = get_executor()
    orders = executor.get_open_orders()
    return {
        "count": len(orders),
        "orders": orders,
    }


@router.delete("/orders")
async def cancel_all_orders():
    """Cancel all open orders."""
    executor = get_executor()
    result = executor.cancel_all_orders()
    return result


@router.get("/positions")
async def get_positions():
    """Get all open positions."""
    executor = get_executor()
    positions = executor.get_positions()
    
    total_pnl = sum(p["unrealized_pnl"] for p in positions)
    total_value = sum(p["market_value"] for p in positions)
    
    return {
        "count": len(positions),
        "total_unrealized_pnl": round(total_pnl, 2),
        "total_market_value": round(total_value, 2),
        "positions": positions,
    }


@router.delete("/positions/{symbol}")
async def close_position(symbol: str):
    """Close a single position."""
    executor = get_executor()
    result = executor.close_position(symbol.upper())
    return result


@router.delete("/positions")
async def close_all_positions():
    """Close all positions (manual EOD flatten)."""
    executor = get_executor()
    result = executor.close_all_positions()
    return result


@router.post("/flatten-eod")
async def flatten_end_of_day():
    """
    End-of-day flatten: Cancel all orders and close all positions.
    Typically called at 3:55 PM ET.
    """
    result = flatten_eod()
    return result


@router.get("/account")
async def get_account():
    """Get Alpaca account information."""
    executor = get_executor()
    account = executor.get_account()
    return account


@router.get("/kill-switch")
async def get_kill_switch_status():
    """Check kill switch status."""
    executor = get_executor()
    return {
        "active": executor.is_kill_switch_active(),
        "timestamp": datetime.now(ET).isoformat(),
    }


@router.post("/kill-switch/activate")
async def activate_kill_switch():
    """Activate kill switch - stops all new orders."""
    executor = get_executor()
    
    # Cancel all open orders immediately
    executor.cancel_all_orders()
    
    # Activate kill switch
    success = executor.activate_kill_switch()
    
    return {
        "status": "activated" if success else "failed",
        "active": executor.is_kill_switch_active(),
        "timestamp": datetime.now(ET).isoformat(),
    }


@router.post("/kill-switch/deactivate")
async def deactivate_kill_switch():
    """Deactivate kill switch - resumes trading."""
    executor = get_executor()
    success = executor.deactivate_kill_switch()
    
    return {
        "status": "deactivated" if success else "failed",
        "active": executor.is_kill_switch_active(),
        "timestamp": datetime.now(ET).isoformat(),
    }
