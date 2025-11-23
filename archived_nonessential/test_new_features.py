"""Test Volume and Volatility feature extraction"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from ml_orb_5m.src.features.volume_liquidity import extract_volume_features
from ml_orb_5m.src.features.volatility import extract_volatility_features

# Paths
DATA_DIR = Path(__file__).parent.parent / "data" / "processed"

def test_features():
    symbol = "AAME"
    date = "2021-02-05"
    
    print(f"Testing features for {symbol} on {date}...")
    
    # 1. Volume Features
    print("\n1. Volume/Liquidity Features:")
    vol_features = extract_volume_features(symbol, date, str(DATA_DIR))
    for k, v in vol_features.items():
        print(f"  {k}: {v}")
        
    # 2. Volatility Features
    print("\n2. Volatility Features:")
    vola_features = extract_volatility_features(symbol, date, str(DATA_DIR))
    for k, v in vola_features.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    test_features()
