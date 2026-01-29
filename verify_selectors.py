
import os
import sys
import time
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

# Load Env
from dotenv import load_dotenv
load_dotenv('ORB_Live_Trader/config/.env')

USERNAME = os.getenv("TRADEZERO_USERNAME")
PASSWORD = os.getenv("TRADEZERO_PASSWORD")
MFA_SECRET = os.getenv("TRADEZERO_MFA_SECRET")

def verify():
    print("Launching Browser...")
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless") # Visible for debugging
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        print("Navigating to TradeZero...")
        driver.get("https://standard.tradezeroweb.us/")
        
        # Login
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "creds-username"))).send_keys(USERNAME)
        driver.find_element(By.ID, "creds-password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "button.button-login").click()
        
        # MFA
        print("Entering MFA...")
        totp = pyotp.TOTP(MFA_SECRET)
        time.sleep(5) # Blind wait for MFA page load
        
        try:
             # Just try to find input directly without wait first to see if it's there
             driver.save_screenshot('debug_mfa_page.png')
             mfa_input = driver.find_element(By.CSS_SELECTOR, "input.input-box-mfa")
             mfa_input.send_keys(totp.now())
             driver.find_element(By.CSS_SELECTOR, "button.button-mfa").click()
        except Exception as e:
             print(f"MFA STEP FAILED: {e}")
             driver.save_screenshot('debug_mfa_fail.png')
             raise
        
        # Wait for load
        print("Waiting for Dashboard...")
        time.sleep(10) # Blind wait for dashboard
        try:
            driver.save_screenshot('debug_dashboard_loading.png')
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "trading-order-input-symbol")))
        except Exception as e:
            print("DASHBOARD TIMEOUT")
            driver.save_screenshot('debug_dashboard_fail.png')
            raise
        
        # Test Symbol
        symbol = "NVDA"
        print(f"Loading Symbol: {symbol}")
        inp = driver.find_element(By.ID, "trading-order-input-symbol")
        inp.clear()
        inp.send_keys(symbol, Keys.RETURN)
        
        time.sleep(5) # Let it render
        
        # Verify Selectors
        print("--- VERIFICATION ---")
        try:
            bid_el = driver.find_element(By.ID, "trading-order-bid")
            ask_el = driver.find_element(By.ID, "trading-order-ask")
            last_el = driver.find_element(By.ID, "trading-order-p") # Corrected ID from snapshot? client.py says 'trading-order-p'
            
            print(f"BID ELEMENT FOUND: Text='{bid_el.text}'")
            print(f"ASK ELEMENT FOUND: Text='{ask_el.text}'")
            print(f"LAST ELEMENT FOUND: Text='{last_el.text}'")
            
            if bid_el.text and ask_el.text:
                print("SUCCESS: Data populated.")
            else:
                print("WARNING: Elements found but empty.")
                
        except Exception as e:
            print(f"ERROR FINDING ELEMENTS: {e}")
            
    except Exception as e:
        print(f"CRITICAL FAILURE: {e}")
    finally:
        print("Closing...")
        driver.quit()

if __name__ == "__main__":
    verify()
