import sys
import time
from pathlib import Path
from selenium.webdriver.common.by import By

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from execution.tradezero.client import TradeZero
from core.config import settings

def main():
    print("Initializing TradeZero Client...")
    tz = TradeZero(
        user_name=settings.TRADEZERO_USERNAME,
        password=settings.TRADEZERO_PASSWORD,
        headless=settings.TRADEZERO_HEADLESS,
        home_url=settings.TRADEZERO_HOME_URL,
    )

    try:
        print("Logging in...")
        tz.login()
        print("Login successful.")
        
        # 1. Inspect Login Form elements (since we seem stuck there)
        print("\n--- Inspecting Login Form ---")
        try:
            inputs = tz.driver.find_elements(By.TAG_NAME, "input")
            for inp in inputs:
                print(f"Input: Type={inp.get_attribute('type')}, ID={inp.get_attribute('id')}, Name={inp.get_attribute('name')}, Value={inp.get_attribute('value')}")
            
            buttons = tz.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                print(f"Button: Text='{btn.text}', ID={btn.get_attribute('id')}, Class={btn.get_attribute('class')}")
        except:
             pass

        # 2. Dump Visible Text
        print("\n--- Page Text Snapshot ---")
        try:
            body_text = tz.driver.find_element(By.TAG_NAME, "body").text
            print(body_text[:2000] + "...") # First 2000 chars
        except Exception as e:
            print(f"Body text dump failed: {e}")

        # 2. Inspect active windows/modules
        print("\n--- Finding Windows ---")
        try:
            # TradeZero windows usually have class 'window' or 'module'
            windows = tz.driver.find_elements(By.CSS_SELECTOR, ".window-header")
            for w in windows:
                print(f"Window: {w.text}")
        except:
            pass

    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Closing...")
        tz.exit()

if __name__ == "__main__":
    main()
