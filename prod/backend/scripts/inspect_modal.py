import sys
import time
import json
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

sys.path.append(str(Path(__file__).parent.parent))
from execution.tradezero.client import TradeZero
from core.config import settings

def dump_html(driver, name):
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"logs/debug_modal_{timestamp}_{name}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"Dumped HTML to {filename}")
    return filename

def check_for_modals(driver):
    print("Checking for modals...")
    modals = driver.find_elements(By.CSS_SELECTOR, "#simplemodal-container")
    if modals:
        print(f"FOUND MODAL! ID: {modals[0].get_attribute('id')}")
        print(f"Modal HTML: {modals[0].get_attribute('outerHTML')}")
        
        # Check for buttons inside
        buttons = modals[0].find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            print(f"Modal Button: Text='{btn.text}', ID='{btn.get_attribute('id')}', Class='{btn.get_attribute('class')}'")
        
        inputs = modals[0].find_elements(By.TAG_NAME, "input")
        for inp in inputs:
            print(f"Modal Input: ID='{inp.get_attribute('id')}', Type='{inp.get_attribute('type')}'")
            
        return True
    else:
        print("No #simplemodal-container found.")
        
    # Check for other common overlay types
    overlays = driver.find_elements(By.CLASS_NAME, "ui-dialog")
    if overlays:
         print("Found jQuery UI Dialog!")
         print(overlays[0].get_attribute('outerHTML'))
         return True
         
    return False

def main():
    print("Starting Modal Inspector...")
    tz = TradeZero(
        user_name=settings.TRADEZERO_USERNAME,
        password=settings.TRADEZERO_PASSWORD,
        headless=True, # Use headless to capture DOM state as code sees it
        home_url=settings.TRADEZERO_HOME_URL,
        mfa_secret=settings.TRADEZERO_MFA_SECRET,
    )
    
    try:
        # 1. Load Symbol
        symbol = "AEVA"
        print(f"Loading {symbol}...")
        tz.load_symbol(symbol)
        
        time.sleep(2)
        check_for_modals(tz.driver)
        
        # 2. Try to Click Locate Tab (simulating where it failed)
        print("Attempting to click Locate tab...")
        try:
             # Mimic client.py locate logic
            clicked = False
            for loc in [
                (By.ID, "locate-tab-1"),
                (By.CSS_SELECTOR, "[id^='locate-tab-']"),
                (By.XPATH, "//a[contains(translate(., 'LOCATE', 'locate'), 'locate')]"),
            ]:
                try:
                    elem = tz.driver.find_element(*loc)
                    if elem.is_displayed():
                        elem.click()
                        clicked = True
                        print(f"Clicked {loc}")
                        break
                except Exception as e:
                    pass
            
            if not clicked:
                print("Failed to click Locate tab.")
            
            time.sleep(2)
            check_for_modals(tz.driver)
            
        except Exception as e:
            print(f"Locate interaction failed: {e}")
            check_for_modals(tz.driver)
            
        # 3. Try access Order Form for Shorting
        print("Attempting to interact with order form...")
        # Assume we are back on order tab or still on it
        
        # Try to submit a dummy order (without clicking final submit maybe, or clicking it to trigger modal)
        # We need to trigger the modal the user mentioned.
        # Maybe clicking the "Short" button triggers a confirmation modal?
        
        # Select "Short" type just in case
        try:
             # Find Short button? usually it's a "Sell Short" button at bottom or Type dropdown
             # In TZ web, often Type is a dropdown: Market, Limit, Stop, etc.
             # The Action is Buy/Sell/Short/Cover buttons.
             
             # Locate Short button
             short_btn = tz.driver.find_element(By.ID, "trading-order-action-short") # Guessing ID based on patterns
             # If exact ID unknown, check client.py stop_order
             pass
        except:
            pass

        # Let's inspect what buttons are available
        print("Dumping available buttons on page...")
        buttons = tz.driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            bid = btn.get_attribute("id")
            btxt = btn.text
            if "short" in btxt.lower() or "sell" in btxt.lower():
                 print(f"Button: {btxt} (ID: {bid})")
        
        dump_html(tz.driver, "after_actions")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        tz.exit()

if __name__ == "__main__":
    main()
