"""
Execution API endpoints.
Order management, positions, EOD flatten.
"""
from fastapi import APIRouter
from datetime import datetime
from zoneinfo import ZoneInfo

from execution.order_executor import get_executor, flatten_eod


router = APIRouter(prefix="/execution", tags=["execution"])
ET = ZoneInfo("America/New_York")


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
