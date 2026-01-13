import sys
from pathlib import Path
import logging

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from execution.order_executor import get_executor

logging.basicConfig(level=logging.INFO)

def main():
    print("Checking Notifications for Rejections...")
    executor = get_executor() 
    
    try:
        client = executor._get_client()
        
        print("\n--- Notifications ---")
        notifs = client.get_notifications()
        if notifs is None or notifs.empty:
            print("No new notifications.")
        else:
            print(notifs.to_string())
            
    except Exception as e:
        print(f"Error checking notifications: {e}")

if __name__ == "__main__":
    main()
