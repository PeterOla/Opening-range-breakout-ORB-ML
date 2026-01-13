import sys
import time
import os
from pathlib import Path
from selenium.webdriver.common.by import By

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

# Ensure full DOM dump
os.environ["TZ_DEBUG_DUMP"] = "1"

from execution.tradezero.client import TradeZero
from core.config import settings

def main():
    print("Initializing TradeZero Client for UI Inspection...")
    
    tz = TradeZero(
        user_name=settings.TRADEZERO_USERNAME,
        password=settings.TRADEZERO_PASSWORD,
        headless=False,
        home_url=settings.TRADEZERO_HOME_URL,
        mfa_secret=settings.TRADEZERO_MFA_SECRET,
    )

    try:
        print("Wait for dashboard to settle...")
        time.sleep(5)
        
        # 1. Dump visible text of the main body
        print("\n--- Visible Body Text (First 1000 chars) ---")
        try:
            print(tz.driver.find_element(By.TAG_NAME, "body").text[:1000])
        except: pass
        
        # 2. Look for "Equity" string anywhere
        print("\n--- Searching for 'Equity' text ---")
        try:
            # XPath to find any element containing 'Equity'
            # We look for leaf nodes or close to leaf nodes
            els = tz.driver.find_elements(By.XPATH, "//*[contains(text(), 'Equity')]")
            for i, el in enumerate(els):
                print(f"Match {i}: Tag={el.tag_name}, Text='{el.text}'")
                try:
                    parent = el.find_element(By.XPATH, "..")
                    print(f"  Parent: {parent.tag_name} | {parent.text[:50]}...")
                except: pass
        except Exception as e:
            print(f"Search failed: {e}")

        # 3. Try to click Account tab if it exists
        print("\n--- Interaction with Account Tab ---")
        try:
            # Try to find something that looks like an Account tab
            # Based on previous code: portfolio-tab-acc-1
            tab = tz.driver.find_element(By.ID, "portfolio-tab-acc-1")
            print("Found 'portfolio-tab-acc-1', clicking...")
            tab.click()
            time.sleep(2)
            
            # Now dump the table content in that tab
            container = tz.driver.find_element(By.ID, "portfolio-tab-acc")
            print(f"Account Tab Content:\n{container.text}")
        except Exception as e:
            print(f"Account tab interaction failed: {e}. Trying generic 'Account' search...")
            try:
                # Try finding a tab with text "Account"
                acc_tabs = tz.driver.find_elements(By.XPATH, "//*[contains(text(), 'Account')]")
                for t in acc_tabs:
                    if "tab" in t.get_attribute("class") or "tab" in t.get_attribute("id"):
                        print(f"Clicking candidate tab: {t.text}")
                        t.click()
                        time.sleep(1)
                        print(tz.driver.find_element(By.TAG_NAME, "body").text[:500])
                        break
            except: pass

        # Snapshot
        tz._dump_ui_snapshot("capital_check_debug")
        print(f"\nSnapshot saved to logs/tradezero_ui_..._capital_check_debug")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        tz.exit()

if __name__ == "__main__":
    main()
