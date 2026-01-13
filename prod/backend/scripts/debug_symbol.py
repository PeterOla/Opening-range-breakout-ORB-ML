import sys
import time
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

sys.path.append(str(Path(__file__).parent.parent))
from execution.tradezero.client import TradeZero
from core.config import settings

def main():
    print("Debug: Symbol Loading...")
    tz = TradeZero(
        user_name=settings.TRADEZERO_USERNAME,
        password=settings.TRADEZERO_PASSWORD,
        headless=False,
        home_url=settings.TRADEZERO_HOME_URL,
        mfa_secret=settings.TRADEZERO_MFA_SECRET,
    )
    
    try:
        time.sleep(3)
        symbol = "AEVA"
        
        print(f"Attempting to load {symbol}...")
        
        # Manual load steps matching client.py roughly
        inp = tz.driver.find_element(By.ID, "trading-order-input-symbol")
        print(f"Input found. Enabled: {inp.is_enabled()}")
        
        inp.clear()
        inp.send_keys(symbol)
        time.sleep(0.5)
        inp.send_keys(Keys.RETURN)
        print("Sent keys + Return.")
        
        time.sleep(2)
        
        # Check Ask
        try:
            ask = tz.driver.find_element(By.ID, "trading-order-ask")
            print(f"Ask Element Text: '{ask.text}'")
        except Exception as e:
            print(f"Ask element not found or error: {e}")
            
        # Snapshot
        tz._dump_ui_snapshot("debug_symbol_load")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        tz.exit()

if __name__ == "__main__":
    main()
