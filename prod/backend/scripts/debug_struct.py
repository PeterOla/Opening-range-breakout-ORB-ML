import sys
from pathlib import Path
from selenium.webdriver.common.by import By
import time

sys.path.append(str(Path(__file__).parent.parent))
from execution.tradezero.client import TradeZero
from core.config import settings

def main():
    tz = TradeZero(
        user_name=settings.TRADEZERO_USERNAME,
        password=settings.TRADEZERO_PASSWORD,
        headless=False,
        home_url=settings.TRADEZERO_HOME_URL,
        mfa_secret=settings.TRADEZERO_MFA_SECRET,
    )
    
    try:
        time.sleep(5) # settle
        print("Searching for 'Account Value'...")
        
        # Find elements containing "Account Value"
        els = tz.driver.find_elements(By.XPATH, "//*[contains(text(), 'Account Value')]")
        for el in els:
            print(f"Tag: {el.tag_name}, Text: '{el.text}'")
            # Get parent HTML to understand structure
            parent = el.find_element(By.XPATH, "..")
            print(f"Parent HTML: {parent.get_attribute('outerHTML')[:300]}") # Truncate
            
            # Check siblings
            try:
                sib = el.find_element(By.XPATH, "following-sibling::*")
                print(f"Next Sibling: {sib.tag_name}, Text: '{sib.text}'")
            except: pass
            
    except Exception as e:
        print(e)
    finally:
        tz.exit()

if __name__ == "__main__":
    main()
