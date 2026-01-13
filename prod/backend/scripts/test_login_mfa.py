import sys
import os
import time
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

# Enable Diagnostic/Screenshot Mode
os.environ["TZ_DEBUG_DUMP"] = "1"

from execution.tradezero.client import TradeZero
from core.config import settings

def main():
    print("Locked & Loaded: Starting MFA Login Test in Diagnostic Mode...")
    print(f"Screenshots will be saved to: {Path(__file__).parent.parent.parent.parent / 'logs'}")
    
    # Override settings explicitly for this test if needed, but .env should handle it
    print(f"MFA Secret Configured: {'Yes' if settings.TRADEZERO_MFA_SECRET else 'No'}")
    
    try:
        # Client init automatically calls login()
        tz = TradeZero(
            user_name=settings.TRADEZERO_USERNAME,
            password=settings.TRADEZERO_PASSWORD,
            headless=False, # Force visible for local debugging if watched
            home_url=settings.TRADEZERO_HOME_URL,
            mfa_secret=settings.TRADEZERO_MFA_SECRET,
        )
        
        print("\nLogin sequence complete.")
        print("Checking if trading panel is ready...")
        
        if tz._wait_for_trading_panel_ready(timeout_s=5):
            print("SUCCESS: Trading panel is active.")
            tz._dump_ui_snapshot("test_success")
        else:
            print("WARNING: Trading panel not immediately detected, but login didn't crash.")
            tz._dump_ui_snapshot("test_warning_post_login")
            
        time.sleep(2)
        tz.exit()
        
    except Exception as e:
        print(f"\nFATAL: Login failed with error: {e}")
        # The client likely already dumped a snapshot on exception, but just in case:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
