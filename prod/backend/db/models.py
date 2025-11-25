"""
SQLAlchemy database models.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Enum as SQLEnum
from sqlalchemy.sql import func
import enum

from db.database import Base


class OrderSide(str, enum.Enum):
    """Order side enum."""
    LONG = "LONG"
    SHORT = "SHORT"


class OrderStatus(str, enum.Enum):
    """Order status enum."""
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PositionStatus(str, enum.Enum):
    """Position status enum."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LogLevel(str, enum.Enum):
    """Log level enum."""
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class Trade(Base):
    """Trade records table."""
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    ticker = Column(String(10), nullable=False, index=True)
    side = Column(SQLEnum(OrderSide), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    shares = Column(Integer, nullable=False)
    pnl = Column(Float, nullable=True)
    status = Column(SQLEnum(PositionStatus), default=PositionStatus.OPEN, nullable=False)
    alpaca_order_id = Column(String(50), nullable=True, index=True)
    entry_time = Column(DateTime, default=func.now(), nullable=False)
    exit_time = Column(DateTime, nullable=True)
    stop_price = Column(Float, nullable=True)
    take_price = Column(Float, nullable=True)


class Signal(Base):
    """Trading signals table."""
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    ticker = Column(String(10), nullable=False, index=True)
    side = Column(SQLEnum(OrderSide), nullable=False)
    confidence = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=False)
    stop_price = Column(Float, nullable=True)
    take_price = Column(Float, nullable=True)
    order_id = Column(String(50), nullable=True, index=True)
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    filled_price = Column(Float, nullable=True)
    filled_time = Column(DateTime, nullable=True)
    rejection_reason = Column(String(255), nullable=True)


class SystemLog(Base):
    """System logs table."""
    __tablename__ = "logs"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
    level = Column(SQLEnum(LogLevel), nullable=False, index=True)
    component = Column(String(50), nullable=False, index=True)
    message = Column(String(1000), nullable=False)
    metadata = Column(String(500), nullable=True)


class DailyMetrics(Base):
    """Daily trading metrics table."""
    __tablename__ = "daily_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, unique=True, index=True)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    starting_equity = Column(Float, nullable=False)
    ending_equity = Column(Float, nullable=False)
