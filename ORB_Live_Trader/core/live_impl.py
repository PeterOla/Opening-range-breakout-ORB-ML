"""
Live Implementation of Execution Interfaces
Wraps TradeZero client and Real-time Clock.
"""
from datetime import datetime
import time as time_module
import pandas as pd
from typing import Dict, List, Any, Optional
from .execution import Clock, Broker
# Assuming backend path is setup in main script, but valid relative import here
# will be difficult without sys.path hacks if this module is imported.
# Expect main script to inject dependencies? 
# Or we just assume TradeZero client object is passed to constructor.

import pytz

class LiveClock(Clock):
    def now(self) -> datetime:
        return datetime.now(pytz.timezone("America/New_York"))
    
    def sleep(self, seconds: float):
        time_module.sleep(seconds)

class TimedLiveClock(Clock):
    """
    A live clock that starts at a specific historical time and 
    advances at real-time speed from there.
    """
    def __init__(self, target_datetime: datetime):
        # Ensure target_datetime is aware
        et_tz = pytz.timezone("America/New_York")
        if target_datetime.tzinfo is None:
            self.target_start = et_tz.localize(target_datetime)
        else:
            self.target_start = target_datetime.astimezone(et_tz)
            
        self.actual_start = datetime.now(et_tz)
        
    def now(self) -> datetime:
        elapsed = datetime.now(pytz.timezone("America/New_York")) - self.actual_start
        return self.target_start + elapsed
    
    def sleep(self, seconds: float):
        time_module.sleep(seconds)

class TradeZeroBroker(Broker):
    def __init__(self, tz_client, dry_run: bool = False):
        self.client = tz_client
        self.dry_run = dry_run
        self._mock_positions = [] # Used only in dry_run mode
        self._mock_orders = []    # Used only in dry_run mode
        
    def get_quote(self, symbol: str) -> Dict[str, float]:
        data = self.client.get_market_data(symbol)
        if not data:
            return {'last': 0.0, 'bid': 0.0, 'ask': 0.0, 'volume': 0}
            
        # Normalize from namedtuple: ['open', 'high', 'low', 'close', 'volume', 'last', 'ask', 'bid']
        return {
            'last': float(data.last),
            'bid': float(data.bid),
            'ask': float(data.ask),
            'volume': int(data.volume)
        }
    
    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, price: Optional[float] = None) -> str:
        if self.dry_run:
            order_id = f"MOCK_{int(datetime.now().timestamp())}_{symbol}"
            self._mock_orders.append({
                'order_id': order_id,
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'qty': quantity,
                'price': price,
                'status': 'SUBMITTED',
                'submitted_at': datetime.now() 
            })
            return order_id
            
        # Map side/type to TZ
        from execution.tradezero.client import Order, TIF

        # 1. Map Side
        side_map = {
            'BUY': Order.BUY,
            'SELL': Order.SELL,
            'SHORT': Order.SHORT,
            'COVER': Order.COVER
        }
        tz_side = side_map.get(side.upper(), Order.BUY)

        # 2. Route to specialized method
        otype = order_type.upper()
        if otype == 'STOP':
            # Stop order at TradeZero is automated via stop_order method
            success = self.client.stop_order(
                direction=tz_side,
                symbol=symbol.upper(),
                quantity=int(quantity),
                stop_price=price,
                tif=TIF.DAY
            )
        elif otype == 'LIMIT':
            success = self.client.limit_order(
                direction=tz_side,
                symbol=symbol.upper(),
                quantity=int(quantity),
                price=price,
                tif=TIF.DAY
            )
        else: # MARKET
            success = self.client.market_order(
                direction=tz_side,
                symbol=symbol.upper(),
                quantity=int(quantity),
                tif=TIF.DAY
            )
        
        # TradeZero client returns bool for success usually, or we return a mock ID if true
        if success:
            return f"TZ_{otype}_{symbol}_{int(datetime.now().timestamp())}"
        return ""
    
    def get_positions(self) -> List[Dict[str, Any]]:
        if self.dry_run:
            return self._mock_positions

        portfolio_df = self.client.get_portfolio()
        # Convert DF to list of dicts for generic Broker interface
        if isinstance(portfolio_df, pd.DataFrame) and not portfolio_df.empty:
            # TradeZero client.get_portfolio already returns standardized keys:
            # [symbol, qty, last_price, avg_price, unrealized_pnl]
            return portfolio_df.to_dict('records')
        return []

    def get_active_orders(self) -> List[Dict[str, Any]]:
        if self.dry_run:
            return [o for o in self._mock_orders if o['status'] == 'SUBMITTED']
        
        orders_df = self.client.get_active_orders()
        if orders_df is None: return None
        if isinstance(orders_df, pd.DataFrame) and not orders_df.empty:
            return orders_df.to_dict('records')
        return []

    def get_notifications(self) -> List[Dict[str, Any]]:
        if self.dry_run:
            return []
            
        notifs_df = self.client.get_notifications()
        if isinstance(notifs_df, pd.DataFrame) and not notifs_df.empty:
            return notifs_df.to_dict('records')
        return []
    
    def get_account_info(self) -> Dict[str, float]:
        return {
            'equity': self.client.get_equity(),
            'buying_power': self.client.get_buying_power()
        }
    
    def login(self):
        # Assumed client handles this
        pass
        
    def logout(self):
        self.client.logout()
