import sys
from pathlib import Path
import logging

# Setup path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
logging.basicConfig(level=logging.INFO)

def test_imports_and_loading():
    print("Testing refactor...")
    
    # 1. Test Universe Service Logic directly
    print("\n--- Testing services.universe.load_universe_from_parquet ---")
    from services.universe import load_universe_from_parquet
    path = PROJECT_ROOT / "data" / "backtest" / "orb" / "universe" / "universe_micro_full.parquet"
    try:
        syms = load_universe_from_parquet(path)
        print(f"SUCCESS: Loaded {len(syms)} symbols directly.")
    except Exception as e:
        print(f"FAILED: {e}")

    # 2. Test Sentiment Scanner Fallback
    print("\n--- Testing services.sentiment_scanner fallback ---")
    # Mocking failure of DB to force fallback is hard without mocking, 
    # but we can call get_micro_cap_universe and see if it works (it might use DB if active, logging will show)
    from services.sentiment_scanner import get_micro_cap_universe
    try:
        syms = get_micro_cap_universe()
        print(f"SUCCESS: Sentiment scanner retrieved {len(syms)} symbols.")
    except Exception as e:
        print(f"FAILED: {e}")

    # 3. Test ORB Scanner Setting
    print("\n--- Testing services.orb_scanner._allowed_symbols_from_universe_setting ---")
    from core.config import settings
    # temporarily force setting
    original = getattr(settings, "ORB_UNIVERSE", "all")
    settings.ORB_UNIVERSE = "micro" # maps to universe_micro_full.parquet
    
    from services.orb_scanner import _allowed_symbols_from_universe_setting
    try:
        syms = _allowed_symbols_from_universe_setting()
        print(f"SUCCESS: ORB scanner loaded {len(syms)} symbols.")
    except Exception as e:
        print(f"FAILED: {e}")
    finally:
        settings.ORB_UNIVERSE = original

if __name__ == "__main__":
    test_imports_and_loading()
