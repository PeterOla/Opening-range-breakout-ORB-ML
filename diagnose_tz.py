import os
from dotenv import load_dotenv
from execution.tradezero.client import TradeZero
import pandas as pd

load_dotenv()

def main():
    print("Connecting to TradeZero...")
    tz = TradeZero(
        user_name=os.getenv("TRADEZERO_USERNAME"),
        password=os.getenv("TRADEZERO_PASSWORD"),
        mfa_secret=os.getenv("TRADEZERO_MFA_SECRET"),
        headless=False # Keep it visible so we can see what's happening
    )
    
    try:
        tz.login()
        print("\n--- PORTFOLIO ---")
        pos = tz.get_portfolio()
        print(pos if pos is not None else "Error reading portfolio")
        
        print("\n--- ACTIVE ORDERS ---")
        orders = tz.get_active_orders()
        print(orders if orders is not None else "Error reading orders")
        
        print("\n--- NOTIFICATIONS ---")
        notifs = tz.get_notifications()
        print(notifs.head(10) if notifs is not None else "Error reading notifs")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        print("\nClosing session in 10 seconds...")
        import time
        time.sleep(10)
        tz.exit()

if __name__ == "__main__":
    main()
