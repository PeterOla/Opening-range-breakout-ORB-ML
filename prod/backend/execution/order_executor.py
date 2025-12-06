"""
Order Executor for ORB Strategy.

Handles:
1. Placing stop orders (entry) with attached stop-loss
2. Order status tracking
3. EOD position flattening
4. Kill switch functionality
"""
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo
from pathlib import Path

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    StopOrderRequest,
    StopLimitOrderRequest,
    MarketOrderRequest,
    GetOrdersRequest,
    ClosePositionRequest,
    StopLossRequest,
)
from alpaca.trading.enums import (
    OrderSide as AlpacaOrderSide,
    TimeInForce,
    OrderStatus as AlpacaOrderStatus,
    OrderType,
    QueryOrderStatus,
    OrderClass,
)
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import Signal, Trade, OpeningRange, OrderSide, OrderStatus, PositionStatus
from core.config import settings
from execution.alpaca_client import get_alpaca_client


ET = ZoneInfo("America/New_York")


def calculate_position_size(
    entry_price: float,
    stop_price: float,
) -> dict:
    """
    Calculate position size with fixed leverage from settings.
    
    Uses risk-based sizing: shares = risk_dollars / stop_distance
    Caps at max leverage to prevent over-exposure.
    
    Returns:
        dict with shares, position_value, leverage_used, capped
    """
    capital = settings.TRADING_CAPITAL
    leverage = settings.FIXED_LEVERAGE
    risk_pct = settings.RISK_PER_TRADE_PCT
    
    # Risk in dollars
    risk_dollars = capital * risk_pct
    
    # Stop distance
    stop_distance = abs(entry_price - stop_price)
    stop_distance_pct = stop_distance / entry_price * 100 if entry_price > 0 else 0
    
    # Shares based on risk
    shares_by_risk = int(risk_dollars / stop_distance) if stop_distance > 0 else 0
    
    # Position value
    position_value = shares_by_risk * entry_price
    
    # Actual leverage used
    actual_leverage = position_value / capital if capital > 0 else 0
    
    # Check if within leverage limit
    max_position_value = capital * leverage
    
    if position_value > max_position_value:
        # Cap at max leverage
        shares_capped = int(max_position_value / entry_price)
        position_value_capped = shares_capped * entry_price
        actual_leverage_capped = position_value_capped / capital
        
        return {
            "shares": shares_capped,
            "position_value": round(position_value_capped, 2),
            "leverage_used": round(actual_leverage_capped, 2),
            "capped": True,
            "stop_distance_pct": round(stop_distance_pct, 2),
            "risk_dollars": round(risk_dollars, 2),
        }
    
    return {
        "shares": shares_by_risk,
        "position_value": round(position_value, 2),
        "leverage_used": round(actual_leverage, 2),
        "capped": False,
        "stop_distance_pct": round(stop_distance_pct, 2),
        "risk_dollars": round(risk_dollars, 2),
    }


class OrderExecutor:
    """Executes trading orders on Alpaca."""
    
    def __init__(self):
        self.client = get_alpaca_client()
        self.kill_switch_file = Path(settings.KILL_SWITCH_FILE)
    
    def is_kill_switch_active(self) -> bool:
        """Check if kill switch is engaged."""
        return self.kill_switch_file.exists()
    
    def activate_kill_switch(self) -> bool:
        """Activate kill switch - stops all new orders."""
        try:
            self.kill_switch_file.touch()
            return True
        except Exception:
            return False
    
    def deactivate_kill_switch(self) -> bool:
        """Deactivate kill switch - resumes trading."""
        try:
            if self.kill_switch_file.exists():
                self.kill_switch_file.unlink()
            return True
        except Exception:
            return False
    
    def place_entry_order(
        self,
        symbol: str,
        side: str,
        shares: int,
        entry_price: float,
        stop_price: float,
        signal_id: Optional[int] = None,
    ) -> dict:
        """
        Place a stop order for entry with stop-loss.
        
        For ORB strategy:
        - LONG: Buy stop at OR high, stop-loss below
        - SHORT: Sell stop at OR low, stop-loss above
        
        Args:
            symbol: Stock ticker
            side: "LONG" or "SHORT"
            shares: Number of shares
            entry_price: Stop order trigger price (OR high/low)
            stop_price: Stop-loss price
            signal_id: Optional signal ID to update
            
        Returns:
            Dict with order details
        """
        # Check kill switch
        if self.is_kill_switch_active():
            return {
                "status": "rejected",
                "reason": "Kill switch is active",
                "symbol": symbol,
            }
        
        try:
            # Determine Alpaca order side
            alpaca_side = AlpacaOrderSide.BUY if side == "LONG" else AlpacaOrderSide.SELL
            stop_loss_side = AlpacaOrderSide.SELL if side == "LONG" else AlpacaOrderSide.BUY
            
            # Use OTO (One-Triggers-Other) order:
            # - Primary: Stop entry order (triggers when price hits OR breakout level)
            # - Secondary: Stop-loss order (only placed after primary fills)
            # This ensures stop-loss is placed automatically when entry fills
            order_request = StopOrderRequest(
                symbol=symbol,
                qty=shares,
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,  # Day order - expires at close
                stop_price=entry_price,  # Entry trigger price (OR high/low)
                order_class=OrderClass.OTO,
                stop_loss=StopLossRequest(stop_price=stop_price),
            )
            
            # Submit OTO order (entry + stop-loss)
            order = self.client.submit_order(order_request)
            
            # Update signal status if provided
            if signal_id:
                from services.signal_engine import update_signal_status
                update_signal_status(
                    signal_id=signal_id,
                    status=OrderStatus.PENDING,
                    order_id=order.id,
                )
            
            # Create trade record
            db = SessionLocal()
            try:
                # Note: Using fields that exist in production DB
                trade = Trade(
                    timestamp=datetime.now(ET),  # Legacy column name
                    ticker=symbol,
                    side=OrderSide.LONG if side == "LONG" else OrderSide.SHORT,
                    entry_price=entry_price,
                    shares=shares,
                    stop_price=stop_price,
                    status=PositionStatus.PENDING,  # Pending until order fills
                    alpaca_order_id=str(order.id),
                    entry_time=datetime.now(ET),
                )
                db.add(trade)
                db.commit()
                trade_id = trade.id
            except Exception as db_error:
                # Order placed successfully, just DB logging failed
                db.rollback()
                return {
                    "status": "submitted",
                    "order_id": str(order.id),
                    "trade_id": None,
                    "db_error": str(db_error),
                    "symbol": symbol,
                    "side": side,
                    "shares": shares,
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "order_status": order.status.value,
                }
            finally:
                db.close()
            
            return {
                "status": "submitted",
                "order_id": order.id,
                "trade_id": trade_id,
                "symbol": symbol,
                "side": side,
                "shares": shares,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "order_status": order.status.value,
            }
        
        except Exception as e:
            # Update signal as rejected
            if signal_id:
                from services.signal_engine import update_signal_status
                update_signal_status(
                    signal_id=signal_id,
                    status=OrderStatus.REJECTED,
                    rejection_reason=str(e),
                )
            
            return {
                "status": "error",
                "reason": str(e),
                "symbol": symbol,
            }
    
    def place_stop_loss_order(
        self,
        symbol: str,
        side: str,
        shares: int,
        stop_price: float,
    ) -> dict:
        """
        Place a stop-loss order for an existing position.
        
        Args:
            symbol: Stock ticker
            side: "LONG" or "SHORT" (original position side)
            shares: Number of shares
            stop_price: Stop-loss trigger price
        """
        try:
            # Stop-loss is opposite side of position
            alpaca_side = AlpacaOrderSide.SELL if side == "LONG" else AlpacaOrderSide.BUY
            
            order_request = StopOrderRequest(
                symbol=symbol,
                qty=shares,
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,
                stop_price=stop_price,
            )
            
            order = self.client.submit_order(order_request)
            
            return {
                "status": "submitted",
                "order_id": order.id,
                "symbol": symbol,
                "stop_price": stop_price,
            }
        
        except Exception as e:
            return {
                "status": "error",
                "reason": str(e),
                "symbol": symbol,
            }
    
    def execute_signals(self, signals: list[dict]) -> list[dict]:
        """
        Execute a batch of signals.
        
        Args:
            signals: List of signal dicts from signal_engine
            
        Returns:
            List of execution results
        """
        results = []
        
        for signal in signals:
            result = self.place_entry_order(
                symbol=signal["symbol"],
                side=signal["side"],
                shares=signal["shares"],
                entry_price=signal["entry_price"],
                stop_price=signal["stop_price"],
            )
            results.append(result)
        
        return results
    
    def get_open_orders(self) -> list[dict]:
        """Get all open orders."""
        try:
            request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = self.client.get_orders(request)
            
            return [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "qty": float(o.qty) if o.qty else 0,
                    "type": o.type.value,
                    "status": o.status.value,
                    "stop_price": float(o.stop_price) if o.stop_price else None,
                    "limit_price": float(o.limit_price) if o.limit_price else None,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in orders
            ]
        except Exception as e:
            return []
    
    def cancel_all_orders(self) -> dict:
        """Cancel all open orders."""
        try:
            self.client.cancel_orders()
            return {"status": "success", "message": "All orders cancelled"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
    
    def get_positions(self) -> list[dict]:
        """Get all open positions."""
        try:
            positions = self.client.get_all_positions()
            
            return [
                {
                    "symbol": p.symbol,
                    "qty": float(p.qty),
                    "side": "LONG" if float(p.qty) > 0 else "SHORT",
                    "entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "market_value": float(p.market_value),
                    "unrealized_pnl": float(p.unrealized_pl),
                    "unrealized_pnl_pct": float(p.unrealized_plpc) * 100,
                }
                for p in positions
            ]
        except Exception as e:
            return []
    
    def close_position(self, symbol: str) -> dict:
        """Close a single position."""
        try:
            self.client.close_position(symbol)
            return {"status": "success", "symbol": symbol, "message": "Position closed"}
        except Exception as e:
            return {"status": "error", "symbol": symbol, "reason": str(e)}
    
    def close_all_positions(self) -> dict:
        """Close all open positions (EOD flatten)."""
        try:
            self.client.close_all_positions(cancel_orders=True)
            return {"status": "success", "message": "All positions closed"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
    
    def get_account(self) -> dict:
        """Get account information."""
        try:
            account = self.client.get_account()
            
            return {
                "equity": float(account.equity),
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "portfolio_value": float(account.portfolio_value),
                "day_trade_count": account.daytrade_count,
                "pattern_day_trader": account.pattern_day_trader,
                "trading_blocked": account.trading_blocked,
                "account_blocked": account.account_blocked,
            }
        except Exception as e:
            return {"error": str(e)}


def flatten_eod() -> dict:
    """
    End-of-day position flattening.
    Call this at 3:55 PM ET to close all positions before market close.
    """
    executor = OrderExecutor()
    
    # First cancel all open orders
    cancel_result = executor.cancel_all_orders()
    
    # Then close all positions
    close_result = executor.close_all_positions()
    
    # Update trade records
    db = SessionLocal()
    try:
        # Mark all open trades as closed
        open_trades = db.query(Trade).filter(
            Trade.status == PositionStatus.OPEN
        ).all()
        
        for trade in open_trades:
            trade.status = PositionStatus.CLOSED
            trade.exit_time = datetime.now(ET)
            # Note: actual exit price will be filled by fill handler
        
        db.commit()
    finally:
        db.close()
    
    return {
        "status": "success",
        "timestamp": datetime.now(ET).isoformat(),
        "orders_cancelled": cancel_result,
        "positions_closed": close_result,
    }


# Singleton executor
_executor = None


def get_executor() -> OrderExecutor:
    """Get or create executor singleton."""
    global _executor
    if _executor is None:
        _executor = OrderExecutor()
    return _executor
