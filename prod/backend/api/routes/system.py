"""
System control API endpoints.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
from pathlib import Path

from db.database import get_db
from db.models import SystemLog, LogLevel
from shared.schemas import LogResponse, KillSwitchResponse
from core.config import settings

router = APIRouter()


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
    db: Session = Depends(get_db)
):
    """Get system logs with filters."""
    query = db.query(SystemLog)
    
    # Apply filters
    if level:
        query = query.filter(SystemLog.level == level)
    if component:
        query = query.filter(SystemLog.component == component)
    
    # Order by most recent
    logs = query.order_by(desc(SystemLog.timestamp)).limit(limit).all()
    
    return [
        LogResponse(
            id=log.id,
            timestamp=log.timestamp,
            level=log.level.value,
            component=log.component,
            message=log.message
        )
        for log in logs
    ]
