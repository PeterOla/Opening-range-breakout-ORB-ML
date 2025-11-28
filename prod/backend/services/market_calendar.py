"""
Market Calendar Service.

Uses Alpaca's calendar API to detect:
1. Market holidays (closed days)
2. Early close days (1 PM ET close)
3. Regular trading days

This is critical for:
- Avoiding placing orders on closed days
- Flattening positions early on half days
- Proper pre-market detection
"""
import logging
from datetime import datetime, date, time
from typing import Optional
from zoneinfo import ZoneInfo
from functools import lru_cache

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest

from execution.alpaca_client import get_alpaca_client

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Known early close days (market closes at 1 PM ET)
# These are the typical early close days - Black Friday, Christmas Eve, etc.
# The Alpaca calendar API provides authoritative data
EARLY_CLOSE_TIME = time(13, 0)  # 1:00 PM ET
REGULAR_CLOSE_TIME = time(16, 0)  # 4:00 PM ET
REGULAR_OPEN_TIME = time(9, 30)  # 9:30 AM ET


class MarketCalendar:
    """Market calendar with early close detection."""
    
    def __init__(self):
        self.client = get_alpaca_client()
        self._cache = {}  # Cache calendar lookups
    
    def get_calendar_for_date(self, target_date: date) -> Optional[dict]:
        """
        Get market calendar for a specific date.
        
        Returns:
            dict with open, close times and early_close flag
            None if market is closed
        """
        cache_key = target_date.isoformat()
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            # Get calendar for date range (single day)
            request = GetCalendarRequest(
                start=target_date,
                end=target_date,
            )
            calendar = self.client.get_calendar(request)
            
            if not calendar:
                # No calendar entry = market closed
                self._cache[cache_key] = None
                return None
            
            cal = calendar[0]
            
            # Parse open/close times - Alpaca returns datetime objects
            if isinstance(cal.open, datetime):
                open_time = cal.open.time()
            elif isinstance(cal.open, time):
                open_time = cal.open
            else:
                open_time = datetime.strptime(str(cal.open), "%H:%M").time()
            
            if isinstance(cal.close, datetime):
                close_time = cal.close.time()
            elif isinstance(cal.close, time):
                close_time = cal.close
            else:
                close_time = datetime.strptime(str(cal.close), "%H:%M").time()
            
            # Detect early close (anything before 4 PM)
            is_early_close = close_time < REGULAR_CLOSE_TIME
            
            result = {
                "date": target_date.isoformat(),
                "open": open_time.strftime("%H:%M"),
                "close": close_time.strftime("%H:%M"),
                "early_close": is_early_close,
                "regular_hours": not is_early_close,
            }
            
            self._cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.error(f"Failed to get calendar for {target_date}: {e}")
            return None
    
    def is_trading_day(self, target_date: date) -> bool:
        """Check if a given date is a trading day."""
        return self.get_calendar_for_date(target_date) is not None
    
    def is_early_close_day(self, target_date: Optional[date] = None) -> bool:
        """
        Check if today (or specified date) is an early close day.
        
        Early close days include:
        - Day after Thanksgiving (Black Friday) - 1 PM close
        - Christmas Eve (if weekday) - 1 PM close  
        - July 3rd (if July 4th is Saturday) - 1 PM close
        """
        if target_date is None:
            target_date = datetime.now(ET).date()
        
        cal = self.get_calendar_for_date(target_date)
        if cal is None:
            return False  # Market closed entirely
        
        return cal.get("early_close", False)
    
    def get_market_close_time(self, target_date: Optional[date] = None) -> Optional[time]:
        """
        Get the market close time for today (or specified date).
        
        Returns:
            time object for close, or None if market closed
        """
        if target_date is None:
            target_date = datetime.now(ET).date()
        
        cal = self.get_calendar_for_date(target_date)
        if cal is None:
            return None
        
        return datetime.strptime(cal["close"], "%H:%M").time()
    
    def get_flatten_time(self, target_date: Optional[date] = None, minutes_before: int = 5) -> Optional[time]:
        """
        Get the time to flatten positions (X minutes before close).
        
        For regular days: 3:55 PM (5 mins before 4 PM)
        For early close: 12:55 PM (5 mins before 1 PM)
        
        Args:
            target_date: Date to check (default: today)
            minutes_before: How many minutes before close to flatten
            
        Returns:
            time object for flatten, or None if market closed
        """
        if target_date is None:
            target_date = datetime.now(ET).date()
        
        close_time = self.get_market_close_time(target_date)
        if close_time is None:
            return None
        
        # Convert to datetime for arithmetic and use timedelta
        from datetime import timedelta
        close_dt = datetime.combine(target_date, close_time)
        flatten_dt = close_dt - timedelta(minutes=minutes_before)
        
        return flatten_dt.time()
    
    def should_flatten_now(self, minutes_before: int = 5) -> bool:
        """
        Check if we should flatten positions now.
        
        Returns True if current time >= flatten time.
        """
        now = datetime.now(ET)
        target_date = now.date()
        
        flatten_time = self.get_flatten_time(target_date, minutes_before)
        if flatten_time is None:
            return False  # Market closed
        
        return now.time() >= flatten_time
    
    def get_todays_schedule(self) -> dict:
        """Get comprehensive schedule info for today."""
        today = datetime.now(ET).date()
        now = datetime.now(ET).time()
        
        cal = self.get_calendar_for_date(today)
        
        if cal is None:
            return {
                "date": today.isoformat(),
                "is_trading_day": False,
                "market_closed": True,
                "reason": "Holiday or weekend",
            }
        
        close_time = datetime.strptime(cal["close"], "%H:%M").time()
        flatten_time = self.get_flatten_time(today)
        
        return {
            "date": today.isoformat(),
            "is_trading_day": True,
            "early_close": cal["early_close"],
            "open": cal["open"],
            "close": cal["close"],
            "flatten_time": flatten_time.strftime("%H:%M") if flatten_time else None,
            "should_flatten_now": now >= flatten_time if flatten_time else False,
            "market_open": now >= datetime.strptime(cal["open"], "%H:%M").time(),
            "market_closed": now >= close_time,
        }


# Singleton instance
_calendar = None


def get_market_calendar() -> MarketCalendar:
    """Get or create market calendar singleton."""
    global _calendar
    if _calendar is None:
        _calendar = MarketCalendar()
    return _calendar


def is_early_close_today() -> bool:
    """Quick check if today is an early close day."""
    return get_market_calendar().is_early_close_day()


def get_flatten_time_today() -> Optional[time]:
    """Get today's flatten time (5 mins before close)."""
    return get_market_calendar().get_flatten_time()
