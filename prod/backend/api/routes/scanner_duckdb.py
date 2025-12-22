"""Scanner API routes (DuckDB-only live mode).

This module exists to avoid importing any SQLAlchemy-backed services when
STATE_STORE=duckdb.

Exposes only the live ORB workflow endpoints:
- /scanner/run
- /scanner/today
- /scanner/today/live
- /scanner/mode
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.orb_scanner import (
    scan_orb_candidates,
    get_todays_candidates,
    get_todays_candidates_with_live_pnl,
)


router = APIRouter(prefix="/scanner", tags=["scanner"])
ET = ZoneInfo("America/New_York")


class ScannerFilters(BaseModel):
    """Request body for custom scanner filters."""

    min_price: float = 5.0
    min_avg_volume: float = 1_000_000
    min_atr: float = 0.50
    min_rvol: float = 1.0
    top_n: int = 20


@router.get("/run")
async def run_scanner(
    min_price: float = Query(5.0, ge=0, description="Minimum stock price"),
    min_avg_volume: float = Query(1_000_000, ge=0, description="Minimum 14-day avg volume"),
    min_atr: float = Query(0.50, ge=0, description="Minimum ATR value"),
    min_rvol: float = Query(1.0, ge=0, description="Minimum RVOL (1.0 = 100%)"),
    top_n: int = Query(20, ge=1, le=100, description="Number of top candidates to return"),
    save_to_db: bool = Query(True, description="Save results to DuckDB state store"),
):
    """Run the ORB stock scanner (Parquet/DuckDB metrics + live opening range bars)."""
    result = await scan_orb_candidates(
        min_price=min_price,
        min_atr=min_atr,
        min_avg_volume=min_avg_volume,
        min_rvol=min_rvol,
        top_n=top_n,
        save_to_db=save_to_db,
    )

    # Backwards-compatible alias
    if isinstance(result, dict) and "candidates_top_n" in result:
        result["count"] = result.get("candidates_top_n")

    return result


@router.post("/run")
async def run_scanner_post(filters: ScannerFilters):
    """Run scanner with POST body filters."""
    return await scan_orb_candidates(
        min_price=filters.min_price,
        min_atr=filters.min_atr,
        min_avg_volume=filters.min_avg_volume,
        min_rvol=filters.min_rvol,
        top_n=filters.top_n,
        save_to_db=True,
    )


@router.get("/today")
async def get_today_candidates(
    top_n: int = Query(20, ge=1, le=100),
    direction: str = Query("both", description="long, short, or both"),
):
    """Get today's scanned candidates from DuckDB state store."""
    candidates = await get_todays_candidates(top_n=int(top_n), direction=str(direction))
    return {
        "status": "success",
        "timestamp": datetime.now(ET).isoformat(),
        "count": len(candidates),
        "candidates": candidates,
    }


@router.get("/today/live")
async def get_today_live_pnl(
    top_n: int = Query(20, ge=1, le=100),
):
    """Get today's candidates with live prices and unrealised P&L."""
    candidates = await get_todays_candidates_with_live_pnl(int(top_n))

    total_pnl_pct = 0.0
    total_dollar_pnl = 0.0
    total_base_dollar_pnl = 0.0
    total_leverage = 0.0
    winners = 0
    losers = 0
    trades_entered = 0

    for c in candidates:
        if c.get("entered"):
            trades_entered += 1
            pnl = float(c.get("pnl_pct") or 0)
            total_pnl_pct += pnl
            total_dollar_pnl += float(c.get("dollar_pnl") or 0)
            total_base_dollar_pnl += float(c.get("base_dollar_pnl") or 0)
            total_leverage += float(c.get("leverage") or 2.0)
            if pnl > 0:
                winners += 1
            elif pnl < 0:
                losers += 1

    return {
        "status": "success",
        "timestamp": datetime.now(ET).isoformat(),
        "count": len(candidates),
        "candidates": candidates,
        "summary": {
            "total_candidates": len(candidates),
            "trades_entered": trades_entered,
            "winners": winners,
            "losers": losers,
            "win_rate": round(winners / trades_entered * 100, 1) if trades_entered > 0 else 0,
            "total_pnl_pct": round(total_pnl_pct, 2),
            "avg_pnl_pct": round(total_pnl_pct / trades_entered, 2) if trades_entered > 0 else 0,
            "total_dollar_pnl": round(total_dollar_pnl, 2),
            "base_dollar_pnl": round(total_base_dollar_pnl, 2),
            "avg_leverage": round(total_leverage / trades_entered, 2) if trades_entered > 0 else 0,
        },
    }


@router.get("/mode")
async def get_mode():
    """Return scanner mode based on time-of-day (ET)."""
    now = datetime.now(ET)
    t = now.time()

    premarket_start = time(4, 0)
    live_start = time(9, 35)
    live_end = time(16, 0)

    if premarket_start <= t < live_start:
        mode = "premarket"
    elif live_start <= t < live_end:
        mode = "live"
    else:
        mode = "historical_today" if t >= live_end else "historical_previous"

    return {
        "status": "success",
        "timestamp": now.isoformat(),
        "mode": mode,
    }
