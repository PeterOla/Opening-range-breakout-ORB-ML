import pandas as pd
from pathlib import Path

data_dir = Path('data/processed/daily')
files = sorted(data_dir.glob('*.parquet'))[-5:]

for f in files:
    df = pd.read_parquet(f)
    df_recent = df.tail(3)
    print(f'{f.stem}:')
    print(f'  Columns: {list(df.columns)}')
    print(f'  Latest dates: {list(df_recent["date"].values)}')
    print(f'  Has TR: {"tr" in df.columns}')
    print(f'  Has ATR14: {"atr_14" in df.columns}')
    if "tr" in df.columns:
        print(f'  TR NaN count (last 5): {df_recent["tr"].isna().sum()}')
    if "atr_14" in df.columns:
        print(f'  ATR14 NaN count (last 5): {df_recent["atr_14"].isna().sum()}')
    print()
