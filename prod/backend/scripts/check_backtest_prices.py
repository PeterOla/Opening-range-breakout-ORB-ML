import pandas as pd
from pathlib import Path

files = [
    "data/backtest/orb/runs/compound/Sent_First_2021_Thresh_0.9/simulated_trades.parquet",
    "data/backtest/orb/runs/compound/Sent_Top5_2021_Thresh_0.9/simulated_trades.parquet"
]

print(f"{'Run Name':<40} | {'Max Entry Price':<15} | {'> $20 Count':<10}")
print("-" * 75)

for f in files:
    path = Path(f)
    if path.exists():
        df = pd.read_parquet(path)
        max_price = df['entry_price'].max()
        over_20 = len(df[df['entry_price'] > 20.0])
        print(f"{path.parent.name:<40} | ${max_price:<14.2f} | {over_20:<10}")
        
        if over_20 > 0:
            print(f"  Sample > $20:")
            print(df[df['entry_price'] > 20][['trade_date', 'symbol', 'entry_price']].head(3))
    else:
        print(f"{path.parent.name:<40} | FILE NOT FOUND")
