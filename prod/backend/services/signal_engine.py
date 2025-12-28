"""
Signal Engine for ORB Strategy.

Generates trading signals from scanned candidates:
1. Takes top N candidates from scanner
2. Calculates entry and stop levels
3. Computes position size based on risk
4. Creates Signal records ready for execution
"""
from datetime import datetime, date
from typing import Optional
from zoneinfo import ZoneInfo
import logging

from core.config import settings, get_strategy_config
from state.duckdb_store import DuckDBStateStore

logger = logging.getLogger(__name__)


ET = ZoneInfo("America/New_York")


def calculate_position_size(
    entry_price: float,
    stop_price: float,
    account_equity: float,
    risk_per_trade_pct: float = 0.01,
    max_position_value: Optional[float] = None,
    leverage: float = 5.0,
) -> int:
    """
    Calculate position size based on EQUAL DOLLAR ALLOCATION (matching fast_backtest.py).
    
    Position Size = (Allocation * Leverage) / Entry Price
    Where Allocation = Equity / Top_N (passed as max_position_value)
    
    Args:
        entry_price: Expected entry price
        stop_price: Stop loss price (used for risk check only, not sizing)
        account_equity: Total account equity
        risk_per_trade_pct: Ignored for sizing (legacy)
        max_position_value: The base allocation per trade (Equity / Top_N)
        leverage: Leverage multiplier (default 5.0)
        
    Returns:
        Number of shares to trade
    """
    if entry_price <= 0:
        return 0
    
    # Use max_position_value as the base allocation if provided, else use equity
    base_allocation = max_position_value if max_position_value else account_equity
    
    # Apply leverage
    target_position_value = base_allocation * leverage
    
    # Apply hard cap if set
    if settings.MAX_POSITION_DOLLAR_LIMIT > 0:
        target_position_value = min(target_position_value, settings.MAX_POSITION_DOLLAR_LIMIT)
    
    # Calculate shares
    shares = int(target_position_value / entry_price)
    
    logger.info(
        f"Sizing: Price={entry_price}, BaseAlloc={base_allocation}, Lev={leverage}, "
        f"TargetVal={target_position_value}, Shares={shares}"
    )
    
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
    
    signals = []
    
    try:
        store = DuckDBStateStore() if save_to_db and (settings.STATE_STORE or "duckdb").lower() == "duckdb" else None

        # Check for existing signals today to prevent duplicates
        today = datetime.now(ET).date()
        existing_symbols = store.list_existing_signal_symbols(today) if store else set()
        
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
            
            # Determine side (keep legacy values used by executor)
            side = "LONG" if direction == 1 else "SHORT"
            
            # Calculate position size with buying power constraint
            # Note: max_position_value is derived from buying_power (which is already leveraged equity)
            # So we pass leverage=1.0 to avoid double-leveraging
            shares = calculate_position_size(
                entry_price=entry_price,
                stop_price=stop_price,
                account_equity=account_equity,
                risk_per_trade_pct=risk_per_trade_pct,
                max_position_value=max_position_value,
                leverage=1.0,
            )
            
            if shares <= 0:
                continue
            
            signal_data = {
                "symbol": symbol,
                "side": side,
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

        if store and signals:
            store.insert_signals(
                target_date=today,
                signals=[
                    {
                        "symbol": s["symbol"],
                        "side": s["side"],
                        "confidence": float(s.get("rvol") or 1.0),
                        "entry_price": float(s["entry_price"]),
                        "stop_price": float(s["stop_price"]),
                    }
                    for s in signals
                ],
            )
            store.mark_signals_generated(today, [s["symbol"] for s in signals])
        
        return signals
    
    except Exception as e:
        raise e


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


def get_pending_signals(db: Optional[object] = None) -> list[dict]:
    """
    Get all pending signals that haven't been executed yet.
    """
    store = DuckDBStateStore()
    return store.get_pending_signals()


def update_signal_status(
    signal_id: int,
    status: str,
    order_id: Optional[str] = None,
    filled_price: Optional[float] = None,
    rejection_reason: Optional[str] = None,
    db: Optional[object] = None,
) -> bool:
    """
    Update signal status after order placement.
    """
    store = DuckDBStateStore()
    try:
        return store.update_signal_status(
            signal_id=int(signal_id),
            status=str(status.value if hasattr(status, "value") else status),
            order_id=order_id,
            filled_price=filled_price,
            rejection_reason=rejection_reason,
        )
    except Exception:
        return False
