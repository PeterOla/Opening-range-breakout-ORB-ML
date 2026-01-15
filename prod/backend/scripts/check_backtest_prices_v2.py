import pandas as pd
from pathlib import Path

files = [
    "data/backtest/orb/runs/compound/Sent_First_2021_Thresh_0.9/simulated_trades.parquet",
]

for f in files:
    path = Path(f)
    if path.exists():
        df = pd.read_parquet(path)
        print(f"Columns: {list(df.columns)}")
        # Check for symbol/ticker
        sym_col = 'symbol' if 'symbol' in df.columns else 'ticker'
        
        over_20 = df[df['entry_price'] > 20.0]
        print(f"Count > 20: {len(over_20)}")
        if not over_20.empty:
            print(over_20[[sym_col, 'entry_price', 'trade_date']].head(5))
