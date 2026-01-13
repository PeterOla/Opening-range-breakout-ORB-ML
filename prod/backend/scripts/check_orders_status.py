import sys
from pathlib import Path
import logging

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from execution.order_executor import get_executor

logging.basicConfig(level=logging.INFO)

def main():
    print("Checking Active Orders...")
    executor = get_executor() # This will reuse the TradeZero client if possible or create new
    
    # It might create a new instance which logs in again if not careful, 
    # but let's see. The previous script finished so the session might be closed unless we keep it open.
    # Actually, the previous script `manual_execute_two.py` finished and exited, so the browser closed.
    # We need to log in again to check status.
    
    try:
        client = executor._get_client() # Forces login
        
        print("\n--- Active Orders ---")
        orders = client.get_active_orders()
        if orders is None or orders.empty:
            print("No active orders found.")
        else:
            print(orders.to_string())
            
    except Exception as e:
        print(f"Error checking orders: {e}")

if __name__ == "__main__":
    main()
