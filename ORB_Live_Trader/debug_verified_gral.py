
import pandas as pd
from pathlib import Path
import json

# Setup
ORB_ROOT = Path(__file__).resolve().parent
verified_path = ORB_ROOT / "data" / "sentiment" / "verified_2025-01-23.parquet"

def inspect_verified():
    if not verified_path.exists():
        print("Verified file not found.")
        return

    df = pd.read_parquet(verified_path)
    gral = df[df['symbol'] == 'GRAL'].iloc[0]
    
    print("=== GRAL PARAMETERS ===")
    print(f"ATR_14: {gral.get('atr_14')}")
    print(f"OR_HIGH: {gral.get('or_high')}")
    print(f"OR_LOW:  {gral.get('or_low')}")
    
    stop_dist = 0.05 * gral.get('atr_14', 0)
    print(f"Stop Dist (0.05*ATR): {stop_dist}")
    print(f"Implied Stop: {gral.get('or_high') - stop_dist}")
    
    print("\n=== GRAL BARS (First 5) ===")
    bars_json = gral['bars_json']
    # If it's a string, load it
    if isinstance(bars_json, str):
        bars = json.loads(bars_json)
    else:
        bars = bars_json # list/dict
        
    for i, b in enumerate(bars[:5]):
        print(f"Bar {i}: {b}")

if __name__ == "__main__":
    inspect_verified()
