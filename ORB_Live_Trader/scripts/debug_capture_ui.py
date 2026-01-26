from pathlib import Path
import sys
import os
import json
import time
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Precise Path Resolution
ORB_ROOT = Path(r"c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\ORB_Live_Trader")
PROJECT_ROOT = ORB_ROOT.parent
BACKEND_PATH = PROJECT_ROOT / "prod" / "backend"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(ORB_ROOT))
sys.path.insert(0, str(BACKEND_PATH))

from dotenv import load_dotenv
load_dotenv(ORB_ROOT / "config" / ".env")

from execution.tradezero.client import TradeZero

def capture_snapshot():
    user = os.getenv("TRADEZERO_USERNAME")
    pw = os.getenv("TRADEZERO_PASSWORD")
    mfa = os.getenv("TRADEZERO_MFA_SECRET")
    
    snapshot_base = ORB_ROOT / "logs" / "ui_debug"
    snapshot_base.mkdir(parents=True, exist_ok=True)
    
    print(f"Initializing TradeZero client (GUI mode)...")
    client = TradeZero(user_name=user, password=pw, mfa_secret=mfa, headless=False)
    
    try:
        print("Logging in...")
        if not client.login():
            print("Login process failed/timed out.")
        
        print("Waiting for dashboard elements (Portfolio Table)...")
        # Wait up to 60s for the portfolio table to actually be present (id='opTable-1' is common for open positions)
        try:
            wait = WebDriverWait(client.driver, 60)
            wait.until(EC.presence_of_element_located((By.ID, "h-total-pl-value")))
            print("Dashboard header detected. Giving extra 15s for tables to populate...")
            time.sleep(15)
        except Exception as e:
            print(f"Warning: Dashboard stabilization timed out: {e}")

        # Manually trigger DOM and Screenshot capture
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = snapshot_base / f"stable_snapshot_{ts}"
        out_path.mkdir(parents=True, exist_ok=True)
        
        print(f"Capturing HTML to {out_path / 'page.html'}...")
        (out_path / "page.html").write_text(client.driver.page_source, encoding='utf-8')
        
        print(f"Capturing Screenshot to {out_path / 'screen.png'}...")
        client.driver.save_screenshot(str(out_path / "screen.png"))
        
        print(f"Snapshot complete. Saved to {out_path}")
        
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
    finally:
        print("Closing browser in 20s...")
        time.sleep(20)
        client.exit()

if __name__ == "__main__":
    capture_snapshot()
