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
    extra_data = Column(String(500), nullable=True)


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


class DailyBar(Base):
    """
    Historical daily OHLCV bars from Polygon.
    Rolling 30-day window for ATR and avg volume calculation.
    """
    __tablename__ = "daily_bars"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    vwap = Column(Float, nullable=True)
    
    # Pre-computed metrics (updated nightly)
    atr_14 = Column(Float, nullable=True)
    avg_volume_14 = Column(Float, nullable=True)
    
    __table_args__ = (
        # Unique constraint on symbol + date
        {"sqlite_autoincrement": True},
    )


class Ticker(Base):
    """
    Stock universe from Polygon.
    Includes active and delisted tickers for survivorship-bias-free data.
    """
    __tablename__ = "tickers"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=True)
    primary_exchange = Column(String(10), nullable=True)  # XNYS, XNAS
    type = Column(String(10), nullable=True)  # CS = Common Stock
    active = Column(Boolean, default=True, index=True)
    currency = Column(String(10), default="USD")
    cik = Column(String(20), nullable=True)
    delisted_utc = Column(DateTime, nullable=True)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Pre-filter flags (updated during daily bar sync)
    meets_price_filter = Column(Boolean, default=False)  # price >= $5
    meets_volume_filter = Column(Boolean, default=False)  # avg_vol >= 1M
    meets_atr_filter = Column(Boolean, default=False)  # ATR >= $0.50


class OpeningRange(Base):
    """
    Opening range data (first 5-min bar) captured each trading day.
    Stores candidates that pass initial filters for review/debugging.
    """
    __tablename__ = "opening_ranges"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    
    # Opening range bar data
    or_open = Column(Float, nullable=False)
    or_high = Column(Float, nullable=False)
    or_low = Column(Float, nullable=False)
    or_close = Column(Float, nullable=False)
    or_volume = Column(Float, nullable=False)
    
    # Direction: 1 = bullish (long), -1 = bearish (short), 0 = doji (skip)
    direction = Column(Integer, nullable=False)
    
    # Computed metrics
    rvol = Column(Float, nullable=True)  # Relative volume
    atr = Column(Float, nullable=True)   # 14-day ATR at time of scan
    avg_volume = Column(Float, nullable=True)  # 14-day avg volume
    
    # Filter results
    passed_filters = Column(Boolean, default=False)  # Met all criteria
    rank = Column(Integer, nullable=True)  # Rank by RVOL (1-20 = top 20)
    
    # Entry levels
    entry_price = Column(Float, nullable=True)  # OR high (long) or OR low (short)
    stop_price = Column(Float, nullable=True)   # 10% ATR from entry
    
    # Outcome tracking
    signal_generated = Column(Boolean, default=False)
    order_placed = Column(Boolean, default=False)
    
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )
