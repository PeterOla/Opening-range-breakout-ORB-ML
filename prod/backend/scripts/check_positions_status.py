import sys
from pathlib import Path
import logging

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from execution.order_executor import get_executor

logging.basicConfig(level=logging.INFO)

def main():
    print("Checking POSITIONS...")
    executor = get_executor() 
    
    try:
        # We need to reuse the client if possible to avoid relogin, but likely need new one.
        # Actually, get_positions calls self.client.get_portfolio()
        # If we just instantiate executor, it creates a new client which logs in.
        
        # Note: If the previous script closed the browser (it did), we need to log in again.
        # This will be the 3rd login in a row, hopefully TZ doesn't rate limit or block.
        
        # Optimization: We can check if we can check active orders AND positions in one go.
        
        client = executor._get_client()
        
        print("\n--- Current Positions ---")
        positions = executor.get_positions()
        if not positions:
            print("No open positions.")
        else:
            for p in positions:
                print(p)
                
    except Exception as e:
        print(f"Error checking positions: {e}")

if __name__ == "__main__":
    main()
