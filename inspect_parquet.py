import pandas as pd
import os

file_path = r"C:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\universe\universe_micro_full.parquet"

if os.path.exists(file_path):
    try:
        df = pd.read_parquet(file_path)
        print(f"Columns: {df.columns.tolist()}")
        print(f"Shape: {df.shape}")
        if 'ticker' in df.columns:
            print("Check: 'ticker' column EXISTS.")
        else:
            print("Check: 'ticker' column MISSING.")
            # check for symbol
            if 'symbol' in df.columns:
                 print("Check: 'symbol' column EXISTS (maybe a mismatch?).")
            
    except Exception as e:
        print(f"Error reading parquet: {e}")
else:
    print(f"File not found: {file_path}")
