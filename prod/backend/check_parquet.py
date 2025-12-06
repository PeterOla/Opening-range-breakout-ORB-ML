
import pandas as pd
import os

file_path = r"c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\processed\5min\AAPL.parquet"
if os.path.exists(file_path):
    try:
        df = pd.read_parquet(file_path)
        print(f"Columns: {df.columns.tolist()}")
        print(f"Rows: {len(df)}")
        print(f"Date Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        print(df.head())
    except Exception as e:
        print(f"Error reading parquet: {e}")
else:
    print("File not found")
