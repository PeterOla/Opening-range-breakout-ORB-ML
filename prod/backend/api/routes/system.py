"""
System control API endpoints.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List
from pathlib import Path
from shared.schemas import LogResponse, KillSwitchResponse
from core.config import settings
from services.scheduler import get_scheduled_jobs

router = APIRouter()


def _sql_enabled() -> bool:
    return (getattr(settings, "STATE_STORE", "duckdb") or "duckdb").lower() != "duckdb"


@router.get("/kill-switch", response_model=KillSwitchResponse)
async def get_kill_switch_status():
    """Get current kill switch status."""
    kill_switch_path = Path(settings.KILL_SWITCH_FILE)
    enabled = kill_switch_path.exists()
    
    return KillSwitchResponse(
        enabled=enabled,
        message="Kill switch is ON - no new orders" if enabled else "Kill switch is OFF - trading active"
    )


@router.post("/kill-switch", response_model=KillSwitchResponse)
async def toggle_kill_switch(enable: bool):
    """Toggle kill switch on/off."""
    kill_switch_path = Path(settings.KILL_SWITCH_FILE)
    
    if enable:
        # Create file to enable kill switch
        kill_switch_path.touch()
        message = "Kill switch ENABLED - all new orders stopped"
    else:
        # Remove file to disable kill switch
        if kill_switch_path.exists():
            kill_switch_path.unlink()
        message = "Kill switch DISABLED - trading resumed"
    
    return KillSwitchResponse(
        enabled=enable,
        message=message
    )


@router.get("/logs", response_model=List[LogResponse])
async def get_logs(
    limit: int = Query(100, ge=1, le=500),
    level: str = Query(None),
    component: str = Query(None),
):
    """Get system logs with filters."""
    if not _sql_enabled():
        raise HTTPException(status_code=501, detail="System logs are disabled when STATE_STORE=duckdb")

    from sqlalchemy import desc
    from db.database import SessionLocal
    from db.models import SystemLog

    db = SessionLocal()
    try:
        query = db.query(SystemLog)

        if level:
            query = query.filter(SystemLog.level == level)
        if component:
            query = query.filter(SystemLog.component == component)

        logs = query.order_by(desc(SystemLog.timestamp)).limit(int(limit)).all()

        return [
            LogResponse(
                id=log.id,
                timestamp=log.timestamp,
                level=log.level.value,
                component=log.component,
                message=log.message,
            )
            for log in logs
        ]
    finally:
        db.close()


@router.get("/scheduler")
async def get_scheduler_status():
    """Get scheduled jobs and their next run times."""
    jobs = get_scheduled_jobs()
    return {
        "status": "running" if jobs else "no_jobs",
        "jobs": jobs,
    }


@router.post("/scheduler/trigger-sync")
async def trigger_data_sync():
    """
    Manually trigger the nightly data sync.
    
    Useful for:
    - Initial setup (first time running the system)
    - Catching up after downtime
    - Testing the sync process
    """
    from services.scheduler import job_nightly_data_sync
    
    try:
        result = await job_nightly_data_sync()
        return {
            "status": "success",
            "message": "Data sync triggered successfully",
            "result": result,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Data sync failed: {str(e)}",
        }


@router.get("/market-calendar")
async def get_market_calendar():
    """
    Get today's market schedule including early close detection.
    
    Returns:
    - is_trading_day: Whether market is open today
    - early_close: True if market closes early (e.g., Black Friday)
    - open/close: Market hours
    - flatten_time: When positions will be closed (5 mins before close)
    """
    from services.market_calendar import get_market_calendar
    
    calendar = get_market_calendar()
    schedule = calendar.get_todays_schedule()
    
    return {
        "status": "success",
        "schedule": schedule,
    }


@router.post("/flatten-positions")
async def flatten_all_positions():
    """
    Manually close all positions and cancel all orders.
    
    Use this for:
    - Emergency position closure
    - Early close days if automatic didn't trigger
    - End of day manual flatten
    """
    from execution.order_executor import flatten_eod
    
    try:
        result = flatten_eod()
        return {
            "status": "success",
            "message": "All positions flattened",
            "result": result,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to flatten: {str(e)}",
        }


@router.post("/scheduler/schedule-eod")
async def schedule_eod_flatten():
    """
    Manually schedule today's EOD flatten based on market calendar.
    
    This will detect early close days and schedule appropriately:
    - Regular days: 3:55 PM ET
    - Early close: 12:55 PM ET (or 5 mins before actual close)
    """
    from services.scheduler import schedule_todays_eod_flatten
    from services.market_calendar import get_market_calendar
    
    try:
        await schedule_todays_eod_flatten()
        
        calendar = get_market_calendar()
        schedule = calendar.get_todays_schedule()
        
        return {
            "status": "success",
            "message": "EOD flatten scheduled",
            "schedule": schedule,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to schedule: {str(e)}",
        }
