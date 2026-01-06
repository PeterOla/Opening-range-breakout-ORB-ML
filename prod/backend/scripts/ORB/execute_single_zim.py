import sys
import os
import time
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from execution.tradezero.executor import TradeZeroExecutor
from core.config import settings

# Force TradeZero execution
os.environ["EXECUTION_BROKER"] = "tradezero"
# Ensure REAL execution (not dry run) to open the browser and place order
os.environ["TRADEZERO_DRY_RUN"] = "false"

def main():
    print("="*60)
    print("MANUAL EXECUTION: ZIM (LONG)")
    print("="*60)
    
    # Initialize Executor (this will launch Chrome and login)
    print("Initializing TradeZero Executor (Launching Chrome)...")
    try:
        executor = TradeZeroExecutor()
        # Force client initialization now to show browser immediately
        executor._get_client()
        
        print("\n" + "="*60)
        print("ACTION REQUIRED: CHECK BROWSER")
        print("1. If the login failed, please log in manually now.")
        print("2. Ensure the TradeZero Trading Dashboard is visible.")
        print("3. You have 60 seconds to complete login...")
        print("="*60)
        
        for i in range(60, 0, -1):
            print(f"Continuing in {i} seconds...", end="\r")
            time.sleep(1)
        print("\nProceeding with order placement...")
        
    except Exception as e:
        print(f"Failed to initialize TradeZero client: {e}")
        print("Check your .env file for TRADEZERO_USERNAME and TRADEZERO_PASSWORD.")
        return

    symbol = "ZIM"
    side = "LONG"
    # Calculated shares for $1,000 Equity ($1,000 position value)
    # $1000 / 22.20 = 45.04
    shares = 45
    entry = 22.20
    stop = 22.10
    
    print(f"\nPlacing STOP ENTRY Order:")
    print(f"  Symbol: {symbol}")
    print(f"  Side:   {side}")
    print(f"  Shares: {shares}")
    print(f"  Price:  ${entry}")
    print(f"  Stop:   ${stop}")
    print("-" * 30)
    
    try:
        res = executor.place_entry_order(
            symbol=symbol,
            side=side,
            shares=shares,
            entry_price=entry,
            stop_price=stop
        )
        print("\nOrder Result:", res)
        
        if res.get("status") == "submitted":
            print("\nSUCCESS: Order submitted to TradeZero.")
            print("Check the 'Active Orders' tab in the browser.")
        else:
            print(f"\nWARNING: Order status is {res.get('status')}")
            
    except Exception as e:
        print(f"\nERROR executing order: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*60)
    print("BROWSER SESSION IS ACTIVE.")
    print("You can now inspect the TradeZero window.")
    print("Press Ctrl+C in this terminal to close the browser and exit.")
    print("="*60)
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
