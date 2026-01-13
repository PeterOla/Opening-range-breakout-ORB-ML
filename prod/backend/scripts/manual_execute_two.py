import sys
from pathlib import Path
import logging

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from execution.order_executor import get_executor
from core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("Initializing Executor...")
    executor = get_executor()
    
    # 2. Hardcoded Details from DB Inspection + Capital Calc
    # Total BP: ~9500. Top 5 Strategy.
    # Allocation: $1900 per trade.
    
    # AEVA: Short at 15.18. Stop 15.28.
    # IMSR: Short at 8.16. Stop 8.22.
    
    targets = [
        {
            "symbol": "AEVA",
            "side": "SHORT",
            "entry_price": 15.18,
            "stop_price": 15.28,
            "shares": 125, # $1900 / 15.18
            "signal_id": 50
        },
        {
            "symbol": "IMSR",
            "side": "SHORT",
            "entry_price": 8.16,
            "stop_price": 8.22,
            "shares": 232, # $1900 / 8.16
            "signal_id": 51
        }
    ]
    
    print(f"\nEXECUTING {len(targets)} TRADES MANUAL OVERRIDE")
    print("-" * 40)
    
    for t in targets:
        print(f"\n>>> PROCESSING {t['symbol']}")
        print(f"    Action: {t['side']} {t['shares']} shares")
        print(f"    Entry:  ${t['entry_price']} (Stop Entry)")
        print(f"    S/L:    ${t['stop_price']}")
        
        try:
            result = executor.place_entry_order(
                symbol=t['symbol'],
                side=t['side'],
                shares=t['shares'],
                entry_price=t['entry_price'],
                stop_price=t['stop_price'],
                signal_id=t['signal_id']
            )
            print(f"    Result: {result['status']}")
            if result.get("reason"):
                print(f"    Reason: {result['reason']}")
                
        except Exception as e:
            print(f"    ERROR: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
