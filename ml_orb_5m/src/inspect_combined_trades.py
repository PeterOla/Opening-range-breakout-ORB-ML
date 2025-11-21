import sys
from pathlib import Path
import pandas as pd
import numpy as np
import torch

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ml_orb_5m.src.data.lstm_dataset import ORBSequenceDataset

def inspect_combined_trades():
    print("--- INSPECTING COMBINED TRADES DATA ---")
    
    # Paths
    top20_path = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top20" / "all_trades.csv"
    top50_path = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top50" / "all_trades.csv"
    
    # 1. Inspect Top 20
    print(f"\n[Top 20] Loading: {top20_path}")
    if top20_path.exists():
        df20 = pd.read_csv(top20_path)
        print(f"Total Trades: {len(df20)}")
        print(f"Date Range: {df20['date'].min()} to {df20['date'].max()}")
        print("First 3 Rows:")
        print(df20[["symbol", "date", "entry_time", "net_pnl"]].head(3))
    else:
        print("File not found!")

    # 2. Inspect Top 50
    print(f"\n[Top 50] Loading: {top50_path}")
    if top50_path.exists():
        df50 = pd.read_csv(top50_path)
        print(f"Total Trades: {len(df50)}")
        print(f"Date Range: {df50['date'].min()} to {df50['date'].max()}")
        print("First 3 Rows:")
        print(df50[["symbol", "date", "entry_time", "net_pnl"]].head(3))
    else:
        print("File not found!")

if __name__ == "__main__":
    inspect_combined_trades()
