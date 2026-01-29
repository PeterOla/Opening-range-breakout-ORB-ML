"""
Simulation Components for Verification
"""
from datetime import datetime, timedelta
import pandas as pd
from typing import Dict, List, Optional, Any
from .execution import Clock, Broker
import uuid

class SimClock(Clock):
    def __init__(self, start_time: datetime, time_step_sec: float = 60.0):
        self._current_time = start_time
        self._time_step = time_step_sec
    
    def now(self) -> datetime:
        return self._current_time
    
    def sleep(self, seconds: float):
        # In simulation, sleep just advances time
        self._current_time += timedelta(seconds=seconds)
        
    def advance(self, seconds: float):
        self._current_time += timedelta(seconds=seconds)

class SimBroker(Broker):
    def __init__(self, bars_data: Dict[str, pd.DataFrame], clock: SimClock, equity: float = 100000.0, buying_power: float = 600000.0):
        self.bars = bars_data.copy()
        self.clock = clock
        self.orders = []
        self.positions = [] # [{'symbol':, 'shares':, 'avg_price':}]
        self.completed_trades = [] # Track PNL for reporing
        self.cash = equity 
        self.cash = equity 
        self.equity = equity
        self.buying_power = buying_power
        # Commission Config (aligned with fast_backtest defaults)
        self.comm_share = 0.005
        self.comm_min = 0.99
        self.total_fees = 0.0
        
    def get_quote(self, symbol: str) -> Dict[str, float]:
        now = self.clock.now()
        
        # Get latest bar before or at 'now'
        df = self.bars.get(symbol)
        if df is None or df.empty:
            return {'last': 0, 'bid': 0, 'ask': 0, 'volume': 0}
        
        # Assuming df has 'datetime' column and sorted
        # Find latest bar <= now
        # Efficient lookup needed? For now, simple masking
        valid = df[df['datetime'] <= now]
        if valid.empty:
            # Pre-market or no data yet? Return first bar's open? 
            # Or 0 to indicate no quote?
            return {'last': 0, 'bid': 0, 'ask': 0, 'volume': 0}
        
        last_bar = valid.iloc[-1]
        price = float(last_bar['close'])
        
        # Simple spread simulation
        bid = price - 0.01
        ask = price + 0.01
        
        return {
            'last': price,
            'last_price': price, # Alias for PNL reporting
            'bid': bid,
            'ask': ask,
            'volume': int(last_bar['volume'])
        }
    
    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, price: Optional[float] = None) -> str:
        order_id = str(uuid.uuid4())
        self.orders.append({
            'order_id': order_id,
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'qty': quantity,
            'price': price,
            'status': 'SUBMITTED',
            'submitted_at': self.clock.now()
        })
        return order_id
    
    def get_positions(self) -> List[Dict[str, Any]]:
        # Simulate Fill Matching here on the fly
        self._process_fills()
        return self.positions

    def get_account_info(self) -> Dict[str, float]:
        # Uses values provided at initialization
        return {
            'equity': self.equity,
            'buying_power': self.buying_power
        }

    def get_active_orders(self) -> List[Dict[str, Any]]:
        self._process_fills()
        return [o for o in self.orders if o['status'] == 'SUBMITTED']

    def get_notifications(self) -> List[Dict[str, Any]]:
        return []

    def _process_fills(self):
        """Check open orders against price history up to now."""
        now = self.clock.now()
        
        for order in self.orders:
            if order['status'] != 'SUBMITTED':
                continue
            
            symbol = order['symbol']
            df = self.bars.get(symbol)
            if df is None:
                continue
                
            # Get bars between submitted_at and now
            mask = (df['datetime'] > order['submitted_at']) & (df['datetime'] <= now)
            relevant_bars = df[mask]
            
            if relevant_bars.empty:
                continue
                
            # Iterate bars to check for fill
            for _, bar in relevant_bars.iterrows():
                filled = False
                fill_price = 0.0
                
                # Check Limit Logic
                if order['type'] == 'LIMIT':
                    limit_price = order['price']
                    if order['side'] == 'BUY':
                        # Buy Limit: Low <= Limit
                        if bar['low'] <= limit_price:
                            filled = True
                            fill_price = limit_price # Simplified greedy fill
                    elif order['side'] == 'SELL':
                        # Sell Limit: High >= Limit
                        if bar['high'] >= limit_price:
                            filled = True
                            fill_price = limit_price
                            
                elif order['type'] == 'STOP':
                    stop_trigger = order['price']
                    if order['side'] == 'BUY':
                        # Buy Stop: High >= Stop
                        if bar['high'] >= stop_trigger:
                            filled = True
                            # Use max of open or stop_trigger for fill (slippage)
                            fill_price = max(bar['open'], stop_trigger)
                    elif order['side'] == 'SELL' or order['side'] == 'SHORT':
                        # Sell/Short Stop: Low <= Stop
                        if bar['low'] <= stop_trigger:
                            filled = True
                            fill_price = min(bar['open'], stop_trigger)

                elif order['type'] == 'MARKET':
                    filled = True
                    # In simulation, market orders usually fill at the open of the current/next bar.
                    # If we're at the very end of the day, use the close of the current bar.
                    fill_price = bar['open'] if bar['datetime'] < now else bar['close']
                
                if filled:
                    order['status'] = 'FILLED'
                    order['fill_price'] = fill_price
                    order['filled_at'] = bar['datetime']
                    
                    # Calculate Commission
                    fees = max(order['qty'] * self.comm_share, self.comm_min)
                    order['commission'] = fees
                    self.total_fees += fees
                    
                    self._update_position(symbol, order['side'], order['qty'], fill_price)
                    break 

    def _update_position(self, symbol, side, qty, price):
        # Find existing
        pos = next((p for p in self.positions if p['symbol'] == symbol), None)
        
        if side == 'BUY':
            if pos:
                total_val = (pos['qty'] * pos['avg_price']) + (qty * price)
                new_shares = pos['qty'] + qty
                pos['qty'] = new_shares
                pos['avg_price'] = total_val / new_shares
            else:
                self.positions.append({
                    'symbol': symbol,
                    'qty': qty,
                    'avg_price': price,
                    'last_price': price
                })
        elif side == 'SELL':
            if pos:
                # FIFO/Avg Price PNL Realization
                # Use avg_price for cost basis
                cost_basis = pos['avg_price'] * qty
                proceeds = price * qty
                gross_pnl = proceeds - cost_basis
                
                self.completed_trades.append({
                    'symbol': symbol,
                    'qty': qty,
                    'pnl': gross_pnl,
                    'exit_price': price
                })

                new_shares = pos['qty'] - qty
                if new_shares <= 0:
                    self.positions.remove(pos)
                else:
                    pos['qty'] = new_shares
    
    def get_positions(self) -> List[Dict[str, Any]]:
        self._process_fills()
        # Update last_price for all active positions to facilitate PNL logging
        for pos in self.positions:
            quote = self.get_quote(pos['symbol'])
            pos['last_price'] = quote['last']
        return self.positions

    def get_account_summary(self) -> Dict[str, float]:
        """Returns mock account summary for simulation."""
        # In sim, we track realized PNL from completed_trades
        realized = sum(t['pnl'] for t in self.completed_trades)
        return {
            'total_unrealized': 0.0,
            'day_realized': realized,
            'day_unrealized': 0.0,
            'day_total': realized,
            'buying_power': self.buying_power,
            'equity_exposure': 0.0,
            'account_value': self.equity + realized,
            'est_comm_fees': self.total_fees
        }

    def login(self):
        pass
        
    def logout(self):
        pass
    def get_realized_pnl(self):
        # Calculate realized PNL from closed trades (not implemented in simple SimBroker yet, 
        # usually derived from account equity change if we tracked cash properly).
        # For now, we rely on the main loop to sum trade PNLs. 
        # But we can expose total fees.
        return self.total_fees
