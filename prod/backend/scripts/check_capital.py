import sys
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from execution.order_executor import get_executor
from core.config import settings

def main():
    print("Initializing Executor...")
    
    # Ensure we use TradeZero if that's the intent
    broker_setting = getattr(settings, "EXECUTION_BROKER", "alpaca")
    print(f"Configured EXECUTION_BROKER: {broker_setting}")
    
    executor = get_executor()
    
    print(f"Executor Type: {type(executor).__name__}")
    
    print("Fetching Account Info...")
    try:
        account_info = executor.get_account()
        
        print("\n" + "="*30)
        print("ACCOUNT SUMMARY")
        print("="*30)
        print(f"Equity:         ${account_info.get('equity', 0.0):,.2f}")
        print(f"Buying Power:   ${account_info.get('buying_power', 0.0):,.2f}")
        print(f"Broker:         {account_info.get('broker')}")
        print(f"Dry Run:        {account_info.get('dry_run')}")
        print("="*30 + "\n")
        
    except Exception as e:
        logger.error(f"Failed to fetch account info: {e}")

if __name__ == "__main__":
    main()
