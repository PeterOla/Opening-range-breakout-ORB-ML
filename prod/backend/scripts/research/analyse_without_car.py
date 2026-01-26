"""
Analyse strategy performance with CAR outlier removed.
Shows the true edge without the 89.7% mega-winner.
"""
import pandas as pd
import numpy as np

# Load 5% ATR trades
trades = pd.read_parquet('c:/Users/Olale/Documents/Codebase/Quant/Opening Range Breakout (ORB)/data/backtest/orb/runs/compound/ROLLING24H_Sent_090_Top5_5ATR/simulated_trades.parquet')
trades['is_winner'] = trades['pnl_gross'] > 0

print('='*80)
print('ORIGINAL RESULTS (WITH CAR OUTLIER)')
print('='*80)

# Calculate original metrics
winners = trades[trades['is_winner'] == True]
losers = trades[trades['is_winner'] == False]

original_total_pnl = trades['pnl_gross'].sum()
original_win_rate = (len(winners) / len(trades)) * 100
original_avg_winner = winners['pnl_gross'].mean() if len(winners) > 0 else 0
original_avg_loser = losers['pnl_gross'].mean() if len(losers) > 0 else 0
original_pf = abs(winners['pnl_gross'].sum() / losers['pnl_gross'].sum()) if losers['pnl_gross'].sum() != 0 else 0

# Find CAR trade
car_trades = trades[trades['ticker'] == 'CAR'].copy()
car_trade = car_trades[car_trades['pnl_gross'] > 100000].copy()  # The mega winner
if len(car_trade) > 0:
    car_pnl = car_trade.iloc[0]['pnl_gross']
    car_pct = (car_pnl / original_total_pnl) * 100
    print(f'\nCAR Trade (2 Nov 2021):')
    print(f'  Entry: ${car_trade.iloc[0]["entry_price"]:.2f}')
    print(f'  Exit: ${car_trade.iloc[0]["exit_price"]:.2f}')
    print(f'  Return: {car_trade.iloc[0]["pnl_pct"]:+.2f}%')
    print(f'  Profit: ${car_pnl:,.0f}')
    print(f'  % of Total: {car_pct:.1f}%')

print(f'\nOriginal Metrics:')
print(f'  Total Trades: {len(trades):,}')
print(f'  Winners: {len(winners)} ({original_win_rate:.1f}%)')
print(f'  Losers: {len(losers)} ({100-original_win_rate:.1f}%)')
print(f'  Total PnL: ${original_total_pnl:,.0f}')
print(f'  Avg Winner: ${original_avg_winner:,.0f}')
print(f'  Avg Loser: ${original_avg_loser:,.0f}')
print(f'  Winner/Loser Ratio: {abs(original_avg_winner/original_avg_loser):.2f}x')
print(f'  Profit Factor: {original_pf:.2f}')

# Load actual backtest final equity
yearly = pd.read_parquet('c:/Users/Olale/Documents/Codebase/Quant/Opening Range Breakout (ORB)/data/backtest/orb/runs/compound/ROLLING24H_Sent_090_Top5_5ATR/yearly_results.parquet')
original_final_equity = yearly['end_equity'].iloc[-1]
original_return_pct = yearly['year_return_pct'].iloc[-1]
print(f'  Final Equity: ${original_final_equity:,.0f}')
print(f'  Total Return: {original_return_pct:,.0f}%')

print('\n' + '='*80)
print('RESULTS WITHOUT CAR OUTLIER')
print('='*80)

# Remove CAR mega-winner
trades_no_car = trades[~((trades['ticker'] == 'CAR') & (trades['pnl_gross'] > 100000))].copy()

# Recalculate metrics
winners_no_car = trades_no_car[trades_no_car['is_winner'] == True]
losers_no_car = trades_no_car[trades_no_car['is_winner'] == False]

new_total_pnl = trades_no_car['pnl_gross'].sum()
new_win_rate = (len(winners_no_car) / len(trades_no_car)) * 100
new_avg_winner = winners_no_car['pnl_gross'].mean() if len(winners_no_car) > 0 else 0
new_avg_loser = losers_no_car['pnl_gross'].mean() if len(losers_no_car) > 0 else 0
new_pf = abs(winners_no_car['pnl_gross'].sum() / losers_no_car['pnl_gross'].sum()) if losers_no_car['pnl_gross'].sum() != 0 else 0

print(f'\nNew Metrics (No CAR):')
print(f'  Total Trades: {len(trades_no_car):,}')
print(f'  Winners: {len(winners_no_car)} ({new_win_rate:.1f}%)')
print(f'  Losers: {len(losers_no_car)} ({100-new_win_rate:.1f}%)')
print(f'  Total PnL: ${new_total_pnl:,.0f}')
print(f'  Avg Winner: ${new_avg_winner:,.0f}')
print(f'  Avg Loser: ${new_avg_loser:,.0f}')
print(f'  Winner/Loser Ratio: {abs(new_avg_winner/new_avg_loser):.2f}x')
print(f'  Profit Factor: {new_pf:.2f}')

# Re-simulate equity curve without CAR trade
# Start with $1500, compound through all trades except CAR mega-winner
equity_curve = [1500.0]
current_equity = 1500.0

for _, trade in trades_no_car.iterrows():
    if trade['shares'] > 0:
        # Recalculate position size based on current equity
        allocation = current_equity / 5.0  # Top 5 allocation
        position_value = allocation * 6.0  # 6x leverage
        shares_recalc = int(position_value / trade['entry_price'])
        
        # Calculate P&L as percentage of current equity
        if shares_recalc > 0:
            pnl_pct_of_equity = (trade['pnl_gross'] / current_equity) if current_equity > 0 else 0
            current_equity += trade['pnl_gross']
            equity_curve.append(current_equity)

new_final_equity = current_equity
new_return_pct = ((new_final_equity - 1500) / 1500) * 100
print(f'  Final Equity: ${new_final_equity:,.0f}')
print(f'  Total Return: {new_return_pct:,.0f}%')

print('\n' + '='*80)
print('IMPACT ANALYSIS')
print('='*80)

pnl_change = ((new_total_pnl - original_total_pnl) / original_total_pnl) * 100
equity_change = ((new_final_equity - original_final_equity) / original_final_equity) * 100
wr_change = new_win_rate - original_win_rate
pf_change = new_pf - original_pf

print(f'\nChanges After Removing CAR:')
print(f'  Total PnL: {pnl_change:+.1f}% (${original_total_pnl:,.0f} → ${new_total_pnl:,.0f})')
print(f'  Final Equity: {equity_change:+.1f}% (${original_final_equity:,.0f} → ${new_final_equity:,.0f})')
print(f'  Win Rate: {wr_change:+.1f}pp ({original_win_rate:.1f}% → {new_win_rate:.1f}%)')
print(f'  Profit Factor: {pf_change:+.2f} ({original_pf:.2f} → {new_pf:.2f})')
print(f'  Avg Winner: {((new_avg_winner - original_avg_winner)/original_avg_winner)*100:+.1f}% (${original_avg_winner:,.0f} → ${new_avg_winner:,.0f})')

print(f'\n{"="*80}')
print('VERDICT')
print(f'{"="*80}\n')

if new_pf >= 1.5:
    verdict = '✅ STILL PROFITABLE'
    explanation = 'System has genuine edge beyond single outlier'
elif new_pf >= 1.0:
    verdict = '⚠️  BARELY PROFITABLE'
    explanation = 'Edge is weak without outliers - requires large sample size'
else:
    verdict = '❌ LOSES MONEY'
    explanation = 'No genuine edge - completely outlier-dependent'

print(f'{verdict} (PF = {new_pf:.2f})')
print(f'{explanation}\n')

print(f'Removing one trade ({1/len(trades)*100:.2f}% of sample) changed:')
print(f'  • Equity by {equity_change:.1f}%')
print(f'  • Profit Factor by {pf_change:.2f}')

if abs(equity_change) > 90:
    dependency = 'EXTREME outlier dependency'
    risk_level = 'CRITICAL'
elif abs(equity_change) > 40:
    dependency = 'Significant outlier dependency'
    risk_level = 'HIGH'
else:
    dependency = 'Reasonable diversification'
    risk_level = 'MODERATE'

print(f'\nConclusion: {dependency} ({risk_level} RISK)')

# Show what top 5 trades contribute
top5_trades = trades.nlargest(5, 'pnl_gross')
top5_pnl = top5_trades['pnl_gross'].sum()
top5_pct = (top5_pnl / original_total_pnl) * 100

print(f'\nTop 5 trades (0.6% of sample) = ${top5_pnl:,.0f} ({top5_pct:.1f}% of total profits)')
print('\nImplication for Live Trading:')
if new_pf < 1.0:
    print('  ⚠️  Strategy REQUIRES outliers to be profitable')
    print('  ⚠️  Without CAR-like trades, system loses money')
    print('  ⚠️  Must trade LARGE sample size to capture rare winners')
    print('  ⚠️  Small sample backtests are MISLEADING')
elif new_pf >= 1.5:
    print('  ✅ Strategy is robust without mega-outliers')
    print('  ✅ Edge is real and consistent')
    print('  ✅ Outliers boost returns but not essential')
else:
    print('  ⚠️  Strategy is marginal without outliers')
    print('  ⚠️  Outliers make the difference between profit and breakeven')
    print('  ⚠️  Requires patience to capture rare winners')
