"""
Execution Abstractions
Decouples logic from real-time execution for verification/simulation.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Optional, Any

class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        pass
    
    @abstractmethod
    def sleep(self, seconds: float):
        pass

class Broker(ABC):
    @abstractmethod
    def get_quote(self, symbol: str) -> Dict[str, float]:
        """Returns {'last': float, 'bid': float, 'ask': float, 'volume': int}"""
        pass
    
    @abstractmethod
    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, price: Optional[float] = None) -> str:
        """Returns order_id"""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Returns [{'symbol': str, 'qty': float, 'avg_price': float, ...}]"""
        pass

    @abstractmethod
    def get_active_orders(self) -> List[Dict[str, Any]]:
        """Returns [{'symbol': str, 'qty': float, 'ref_number': str, ...}]"""
        pass

    @abstractmethod
    def get_notifications(self) -> List[Dict[str, Any]]:
        """Returns [{'date': str, 'title': str, 'message': str}]"""
        pass
        
    @abstractmethod
    def get_account_info(self) -> Dict[str, float]:
        """Returns {'equity': float, 'buying_power': float}"""
        pass
    
    @abstractmethod
    def get_account_summary(self) -> Dict[str, float]:
        """Returns official broker figures: 
        {'day_realized': float, 'day_unrealized': float, 'day_total': float, 
         'account_value': float, 'est_comm_fees': float, ...}
        """
        pass
    
    @abstractmethod
    def login(self):
        pass
    
    @abstractmethod
    def logout(self):
        pass
