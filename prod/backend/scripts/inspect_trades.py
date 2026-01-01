import pandas as pd
from pathlib import Path

TRADES_FILE = Path(r'c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\runs\compound\5year_micro_small_top5_compound\simulated_trades.parquet')

try:
    df = pd.read_parquet(TRADES_FILE)
    print("Columns:", df.columns.tolist())
    print("\nFirst Row:")
    print(df.iloc[0])
except Exception as e:
    print(f"Error: {e}")
