"""
Signal Engine for ORB Strategy.

Generates trading signals from scanned candidates:
1. Takes top N candidates from scanner
2. Calculates entry and stop levels
3. Computes position size based on risk
4. Creates Signal records ready for execution
"""
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from db.database import SessionLocal
from db.models import Signal, OpeningRange, OrderSide, OrderStatus
from core.config import settings, get_strategy_config


ET = ZoneInfo("America/New_York")


def calculate_position_size(
    entry_price: float,
    stop_price: float,
    account_equity: float,
    risk_per_trade_pct: float = 0.01,
    max_position_value: Optional[float] = None,
) -> int:
    """
    Calculate position size based on RISK (matching backtest logic).
    
    Position sized so that if stopped out, you lose exactly risk_per_trade_pct of equity.
    Stop loss is at 10% ATR distance from entry (per strategy document).
    
    Args:
        entry_price: Expected entry price
        stop_price: Stop loss price (10% ATR from entry)
        account_equity: Total account equity
        risk_per_trade_pct: Risk per trade as decimal (0.01 = 1%)
        max_position_value: Maximum position value (optional)
        
    Returns:
        Number of shares to trade
    """
    if entry_price <= 0:
        return 0
    
    # Risk per share = distance to stop
    risk_per_share = abs(entry_price - stop_price)
    
    if risk_per_share <= 0:
        return 0
    
    # Dollar risk = percentage of equity
    dollar_risk = account_equity * risk_per_trade_pct
    
    # Shares sized so max loss = dollar_risk
    shares = int(dollar_risk / risk_per_share)
    
    # Apply max position value constraint if provided
    if max_position_value:
        max_shares_by_value = int(max_position_value / entry_price)
        shares = min(shares, max_shares_by_value)
    
    return max(shares, 0)


def generate_signals_from_candidates(
    candidates: list[dict],
    account_equity: float,
    buying_power: float = None,
    risk_per_trade_pct: float = None,
    max_positions: int = None,
    save_to_db: bool = True,
) -> list[dict]:
    """
    Generate trading signals from scanner candidates.
    
    Args:
        candidates: List of candidates from orb_scanner.scan_orb_candidates()
        account_equity: Current account equity for position sizing
        buying_power: Available buying power (defaults to equity if not provided)
        risk_per_trade_pct: Risk per trade (defaults to strategy config)
        max_positions: Maximum number of signals to generate (defaults to strategy config)
        save_to_db: Whether to save signals to database
        
    Returns:
        List of signal dicts ready for execution
    """
    # Get strategy config for defaults
    strategy = get_strategy_config()
    
    if risk_per_trade_pct is None:
        risk_per_trade_pct = strategy["risk_per_trade"]
    
    if max_positions is None:
        max_positions = strategy["top_n"]
    
    # Default buying power to equity if not provided
    if buying_power is None:
        buying_power = account_equity
    
    # Calculate max position value per trade based on buying power
    # Each position gets equal share of buying power
    max_position_value = buying_power / max_positions
    
    db = SessionLocal() if save_to_db else None
    signals = []
    
    try:
        # Check for existing signals today to prevent duplicates
        existing_symbols = set()
        if db:
            today = datetime.now(ET).date()
            existing = db.query(Signal).filter(
                func.date(Signal.signal_date) == today
            ).all()
            existing_symbols = {s.ticker for s in existing}
        
        # Take only top N candidates
        top_candidates = candidates[:max_positions]
        
        for candidate in top_candidates:
            symbol = candidate["symbol"]
            
            # Skip if signal already exists for this symbol today
            if symbol in existing_symbols:
                continue
            
            direction = candidate["direction"]
            entry_price = candidate["entry_price"]
            stop_price = candidate["stop_price"]
            
            # Determine side
            side = OrderSide.LONG if direction == 1 else OrderSide.SHORT
            
            # Calculate position size with buying power constraint
            shares = calculate_position_size(
                entry_price=entry_price,
                stop_price=stop_price,
                account_equity=account_equity,
                risk_per_trade_pct=risk_per_trade_pct,
                max_position_value=max_position_value,
            )
            
            if shares <= 0:
                continue
            
            signal_data = {
                "symbol": symbol,
                "side": side.value,
                "direction": direction,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "shares": shares,
                "rvol": candidate.get("rvol"),
                "atr": candidate.get("atr"),
                "or_high": candidate.get("or_high"),
                "or_low": candidate.get("or_low"),
                "rank": candidate.get("rank"),
                "risk_amount": shares * abs(entry_price - stop_price),
                "position_value": shares * entry_price,
            }
            
            signals.append(signal_data)
            
            # Save to database
            if save_to_db and db:
                db_signal = Signal(
                    signal_date=datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0),
                    timestamp=datetime.now(ET),
                    ticker=symbol,
                    side=side,
                    confidence=candidate.get("rvol", 1.0),  # Use RVOL as confidence proxy
                    entry_price=entry_price,
                    stop_price=stop_price,
                    status=OrderStatus.PENDING,
                )
                db.add(db_signal)
        
        if save_to_db and db:
            db.commit()
            
            # Update opening_ranges to mark signals generated
            for signal in signals:
                db.query(OpeningRange).filter(
                    and_(
                        OpeningRange.symbol == signal["symbol"],
                        OpeningRange.date == datetime.now(ET).date(),
                    )
                ).update({"signal_generated": True})
            
            db.commit()
        
        return signals
    
    except Exception as e:
        if db:
            db.rollback()
        raise e
    
    finally:
        if db:
            db.close()


async def run_signal_generation(
    account_equity: float = None,
    risk_per_trade_pct: float = None,
    max_positions: int = None,
    direction: str = None,
) -> dict:
    """
    Full signal generation pipeline.
    
    1. Fetch account equity from Alpaca (if not provided)
    2. Get today's scanned candidates from database
    3. Generate signals with position sizing
    4. Return signals ready for execution
    
    Args:
        account_equity: Current account equity (auto-fetched from Alpaca if None)
        risk_per_trade_pct: Risk per trade percentage (defaults to strategy config)
        max_positions: Maximum positions to open (defaults to strategy config)
        direction: Signal direction filter (defaults to strategy config)
        
    Returns:
        Dict with status and generated signals
    """
    from services.orb_scanner import get_todays_candidates
    from execution.order_executor import get_executor
    
    # Get strategy config for defaults
    strategy = get_strategy_config()
    
    try:
        # Auto-fetch equity and buying power from Alpaca if not provided
        executor = get_executor()
        account = executor.get_account()
        
        if account_equity is None:
            account_equity = float(account.get("equity", 10000))
        
        buying_power = float(account.get("buying_power", account_equity))
        
        # Apply strategy defaults
        top_n = max_positions or strategy["top_n"]
        dir_filter = direction or strategy["direction"]
        risk_pct = risk_per_trade_pct or strategy["risk_per_trade"]
        
        # Get today's candidates
        candidates = await get_todays_candidates(top_n=top_n, direction=dir_filter)
        
        if not candidates:
            return {
                "status": "no_candidates",
                "message": "No candidates found for today. Run scanner first.",
                "signals": [],
            }
        
        # Generate signals using strategy config with buying power constraint
        signals = generate_signals_from_candidates(
            candidates=candidates,
            account_equity=account_equity,
            buying_power=buying_power,
            risk_per_trade_pct=risk_pct,
            max_positions=top_n,
            save_to_db=True,
        )
        
        return {
            "status": "success",
            "timestamp": datetime.now(ET).isoformat(),
            "candidates_available": len(candidates),
            "signals_generated": len(signals),
            "total_risk": sum(s["risk_amount"] for s in signals),
            "total_position_value": sum(s["position_value"] for s in signals),
            "signals": signals,
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "signals": [],
        }


def get_pending_signals(db: Optional[Session] = None) -> list[dict]:
    """
    Get all pending signals that haven't been executed yet.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        pending = db.query(Signal).filter(
            Signal.status == OrderStatus.PENDING
        ).order_by(Signal.timestamp.desc()).all()
        
        return [
            {
                "id": s.id,
                "symbol": s.ticker,
                "side": s.side.value,
                "entry_price": s.entry_price,
                "stop_price": s.stop_price,
                "confidence": s.confidence,
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            }
            for s in pending
        ]
    
    finally:
        if close_session:
            db.close()


def update_signal_status(
    signal_id: int,
    status: OrderStatus,
    order_id: Optional[str] = None,
    filled_price: Optional[float] = None,
    rejection_reason: Optional[str] = None,
    db: Optional[Session] = None,
) -> bool:
    """
    Update signal status after order placement.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        signal = db.query(Signal).filter(Signal.id == signal_id).first()
        
        if not signal:
            return False
        
        signal.status = status
        
        if order_id:
            signal.order_id = order_id
        
        if filled_price:
            signal.filled_price = filled_price
            signal.filled_time = datetime.now(ET)
        
        if rejection_reason:
            signal.rejection_reason = rejection_reason
        
        db.commit()
        return True
    
    except Exception as e:
        db.rollback()
        return False
    
    finally:
        if close_session:
            db.close()
