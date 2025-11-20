import pandas as pd
import matplotlib.pyplot as plt

# Load daily report
df = pd.read_csv(r'c:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)\orb_5m\core\results\daily_report_2025_thresh_0.5_20251120_144646.csv')

df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date')
df['equity'] = df['pnl'].cumsum()

print(f"Total PnL: {df['pnl'].sum()}")
print(f"Max Drawdown: {(df['equity'] - df['equity'].cummax()).min()}")

# Plot
plt.figure(figsize=(12, 6))
plt.plot(df['date'], df['equity'])
plt.title('Equity Curve (2025) - Threshold 0.5, Price > $5, ATR > 0.5')
plt.xlabel('Date')
plt.ylabel('Equity ($)')
plt.grid(True)
plt.savefig('orb_5m/core/results/equity_curve_0.5_filtered.png')
print("Saved equity curve plot.")
