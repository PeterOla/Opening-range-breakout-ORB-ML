import pandas as pd

# Load trades
df = pd.read_csv(r'c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\orb_5m\core\results\all_trades_raw_2025_20251120_142612.csv')

print("--- Price Stats ---")
print(df['entry_price'].describe())

low_price_5 = df[df['entry_price'] < 5]
low_price_10 = df[df['entry_price'] < 10]

print(f"\nTrades < $5: {len(low_price_5)} ({len(low_price_5)/len(df):.2%})")
print(f"Trades < $10: {len(low_price_10)} ({len(low_price_10)/len(df):.2%})")

# PnL by Price Bucket
df['price_bucket'] = pd.cut(df['entry_price'], bins=[0, 5, 10, 20, 50, 100, 1000])
print("\n--- Net PnL by Price Bucket ---")
print(df.groupby('price_bucket', observed=True)['net_pnl'].sum())

print("\n--- Win Rate by Price Bucket ---")
print(df.groupby('price_bucket', observed=True)['net_pnl'].apply(lambda x: (x > 0).sum() / len(x)))

# ATR Stats
print("\n--- ATR Stats ---")
print(df['atr_14'].describe())

df['atr_bucket'] = pd.cut(df['atr_14'], bins=[0, 0.5, 1.0, 2.0, 5.0, 100])
print("\n--- Net PnL by ATR Bucket ---")
print(df.groupby('atr_bucket', observed=True)['net_pnl'].sum())

print("\n--- Win Rate by ATR Bucket ---")
print(df.groupby('atr_bucket', observed=True)['net_pnl'].apply(lambda x: (x > 0).sum() / len(x)))
