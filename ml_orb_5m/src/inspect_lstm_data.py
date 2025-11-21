import sys
from pathlib import Path
import pandas as pd
import torch

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ml_orb_5m.src.data.lstm_dataset import ORBSequenceDataset

def inspect_data():
    print("--- INSPECTING LSTM DATA GENERATION ---")
    symbol = "AAPL"
    start = "2022-01-01"
    end = "2022-02-01"
    
    print(f"Loading dataset for {symbol} ({start} to {end})...")
    ds = ORBSequenceDataset(symbol, start, end)
    
    print(f"\nTotal Samples (Trades) Found: {len(ds)}")
    
    if len(ds) == 0:
        print("No trades found to inspect.")
        return

    # Inspect the first sample
    print("\n--- SAMPLE 0 INSPECTION ---")
    features, label = ds[0]
    
    print(f"Tensor Shape: {features.shape} (Should be [12, 5])")
    print(f"Label: {label} (1.0 = Win, 0.0 = Loss)")
    
    print("\nFeature Matrix (First 5 bars):")
    print("Cols: [Rel_Open, Rel_High, Rel_Low, Rel_Close, Log_Vol]")
    print(features[:5])
    
    print("\nFeature Stats:")
    print(f"Max Value: {features.max():.4f}")
    print(f"Min Value: {features.min():.4f}")
    print(f"Mean Value: {features.mean():.4f}")
    
    # Check for NaNs
    if torch.isnan(features).any():
        print("\nWARNING: NaNs detected in features!")
    else:
        print("\nData Quality: Clean (No NaNs)")

if __name__ == "__main__":
    inspect_data()
