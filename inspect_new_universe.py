import pandas as pd
import sys

files = [
    r"c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\universe\research_2021_sentiment\universe_sentiment_0.6.parquet",
    r"c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\universe\research_2021_sentiment\universe_sentiment_0.7.parquet",
    r"c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\universe\research_2021_sentiment\universe_sentiment_0.8.parquet",
    r"c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\universe\research_2021_sentiment\universe_sentiment_0.9.parquet",
    r"c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\data\backtest\orb\universe\research_2021_sentiment\universe_sentiment_0.95.parquet"
]

for f in files:
    try:
        df = pd.read_parquet(f)
        print(f"File: {f}")
        print(f"Columns: {df.columns.tolist()}")
        if 'rvol_rank' in df.columns:
            print("rvol_rank PRESENT")
        else:
            print("rvol_rank MISSING")
        print("-" * 30)
    except Exception as e:
        print(f"Error reading {f}: {e}")
