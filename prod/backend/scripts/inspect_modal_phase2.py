import sys
import time
import json
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

sys.path.append(str(Path(__file__).parent.parent))
from execution.tradezero.client import TradeZero
from core.config import settings

def dump_html(driver, name):
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"logs/debug_modal_{timestamp}_{name}.html"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"Dumped HTML to {filename}")
    except Exception as e:
        print(f"Failed to dump HTML: {e}")
    return filename

def check_for_modals(driver):
    print("Checking for modals...")
    try:
        modals = driver.find_elements(By.CSS_SELECTOR, "#simplemodal-container")
        if modals:
            print(f"FOUND MODAL! ID: {modals[0].get_attribute('id')}")
            print(f"Modal Text: '{modals[0].text}'")
            print(f"Modal HTML: {modals[0].get_attribute('outerHTML')}")
            return True
        else:
            print("No #simplemodal-container found.")
    except Exception as e:
        print(f"Error checking modals: {e}")
    return False

def main():
    print("Starting Modal Inspector Phase 2...")
    tz = TradeZero(
        user_name=settings.TRADEZERO_USERNAME,
        password=settings.TRADEZERO_PASSWORD,
        headless=True,
        home_url=settings.TRADEZERO_HOME_URL,
        mfa_secret=settings.TRADEZERO_MFA_SECRET,
    )
    
    try:
        # 1. Load Symbol
        symbol = "AEVA"
        print(f"Loading {symbol}...")
        tz.load_symbol(symbol)
        time.sleep(2)
        
        # 2. Fill Order Form (Dummy values to trigger validation/modal)
        print("Filling Order Form...")
        
        # Qty
        try:
            qty = tz.driver.find_element(By.ID, "trading-order-input-quantity")
            qty.clear()
            qty.send_keys("100")
        except Exception as e:
            print(f"Qty fill failed: {e}")

        # Price (Market or Limit)
        # Select Limit/Stop/Market
        # Let's try MARKET first as it's simplest to trigger "Locate Required"
        try:
            Select(tz.driver.find_element(By.ID, "trading-order-select-type")).select_by_index(0) # Market
        except:
            pass
            
        # 3. Click Short
        print("Clicking Short Button...")
        try:
            short_btn = tz.driver.find_element(By.ID, "trading-order-button-short")
            short_btn.click()
            print("Clicked SHORT.")
        except Exception as e:
            print(f"Failed to click Short: {e}")
            
        # 4. Wait and Check Modals
        time.sleep(1)
        if check_for_modals(tz.driver):
            dump_html(tz.driver, "found_modal")
        else:
            time.sleep(2)
            if check_for_modals(tz.driver):
                dump_html(tz.driver, "found_modal_delayed")
            else:
                dump_html(tz.driver, "no_modal")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        tz.exit()

if __name__ == "__main__":
    main()
