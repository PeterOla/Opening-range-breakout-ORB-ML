"""
Pydantic schemas for API request/response validation.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class PositionResponse(BaseModel):
    """Open position response."""
    ticker: str
    side: str
    shares: int
    entry_price: float
    current_price: float
    pnl: float
    pnl_pct: float


class AccountResponse(BaseModel):
    """Account information response."""
    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    day_pnl: float
    day_pnl_pct: float
    paper_mode: bool


class TradeResponse(BaseModel):
    """Historical trade response."""
    id: int
    timestamp: datetime
    ticker: str
    side: str
    entry_price: float
    exit_price: Optional[float]
    shares: int
    pnl: Optional[float]
    status: str
    duration: Optional[float] = Field(None, description="Duration in minutes")


class SignalResponse(BaseModel):
    """Trading signal response."""
    id: int
    timestamp: datetime
    ticker: str
    side: str
    confidence: Optional[float]
    entry_price: float
    status: str
    filled_price: Optional[float]
    filled_time: Optional[datetime]
    rejection_reason: Optional[str]


class MetricsResponse(BaseModel):
    """Performance metrics response."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    sharpe_ratio: float
    max_drawdown: float


class LogResponse(BaseModel):
    """System log response."""
    id: int
    timestamp: datetime
    level: str
    component: str
    message: str


class KillSwitchResponse(BaseModel):
    """Kill switch status response."""
    enabled: bool
    message: str
