"""
Simulate realistic trading costs on backtest results.

Applies:
1. IBKR realistic commissions: $0.0035/share, min $0.35/order
2. Slippage: 0.02-0.05% per order (entry + exit)
3. One bar entry delay to simulate market drift
"""
import pandas as pd
import numpy as np
from pathlib import Path

# Constants
COMMISSION_PER_SHARE = 0.0035
MIN_COMMISSION_PER_ORDER = 0.35
SLIPPAGE_PCT_MIN = 0.0002  # 0.02%
SLIPPAGE_PCT_MAX = 0.0005  # 0.05%
INITIAL_EQUITY = 1000.0

def calculate_realistic_commission(shares):
    """Calculate IBKR commission."""
    commission = shares * COMMISSION_PER_SHARE
    return max(commission, MIN_COMMISSION_PER_ORDER)

def calculate_slippage(price, shares, direction):
    """Calculate slippage cost (random between 0.02-0.05%)."""
    slippage_pct = np.random.uniform(SLIPPAGE_PCT_MIN, SLIPPAGE_PCT_MAX)
    # Slippage always hurts: buy higher, sell lower
    slippage_per_share = price * slippage_pct
    total_slippage = slippage_per_share * shares
    return total_slippage

def simulate_one_bar_delay(entry_price, exit_price, direction):
    """
    Simulate one bar entry delay (market drift).
    Assume price moves randomly 0.1-0.3% against us on entry.
    """
    drift_pct = np.random.uniform(0.001, 0.003)  # 0.1-0.3%
    
    # Entry drift: price moves against us
    if direction == 1:  # Long - entry price increases
        adjusted_entry = entry_price * (1 + drift_pct)
    else:  # Short - entry price decreases (we short at lower price, worse)
        adjusted_entry = entry_price * (1 - drift_pct)
    
    return adjusted_entry

def apply_realistic_costs(trades_df):
    """Apply realistic costs to all trades."""
    df = trades_df.copy()
    
    print("Applying realistic trading costs...")
    print(f"  - IBKR Commissions: ${COMMISSION_PER_SHARE:.4f}/share, min ${MIN_COMMISSION_PER_ORDER:.2f}")
    print(f"  - Slippage: {SLIPPAGE_PCT_MIN*100:.2f}%-{SLIPPAGE_PCT_MAX*100:.2f}% per order")
    print(f"  - Entry delay: 1 bar drift simulation")
    print()
    
    # Apply one bar entry delay
    df['original_entry_price'] = df['entry_price'].copy()
    df['adjusted_entry_price'] = df.apply(
        lambda row: simulate_one_bar_delay(
            row['entry_price'], 
            row['exit_price'], 
            row['direction']
        ), 
        axis=1
    )
    
    # Recalculate P&L per share with adjusted entry
    df['pnl_per_share_adjusted'] = df.apply(
        lambda row: (row['exit_price'] - row['adjusted_entry_price']) 
                   if row['direction'] == 1 
                   else (row['adjusted_entry_price'] - row['exit_price']),
        axis=1
    )
    
    # Calculate realistic commissions (entry + exit)
    df['commission_entry'] = df['shares'].apply(calculate_realistic_commission)
    df['commission_exit'] = df['shares'].apply(calculate_realistic_commission)
    df['total_commission'] = df['commission_entry'] + df['commission_exit']
    
    # Calculate slippage (entry + exit)
    df['slippage_entry'] = df.apply(
        lambda row: calculate_slippage(row['adjusted_entry_price'], row['shares'], row['direction']),
        axis=1
    )
    df['slippage_exit'] = df.apply(
        lambda row: calculate_slippage(row['exit_price'], row['shares'], row['direction']),
        axis=1
    )
    df['total_slippage'] = df['slippage_entry'] + df['slippage_exit']
    
    # Calculate realistic net P&L
    df['gross_pnl_realistic'] = df['pnl_per_share_adjusted'] * df['shares']
    df['net_pnl_realistic'] = df['gross_pnl_realistic'] - df['total_commission'] - df['total_slippage']
    
    # Calculate total costs
    df['total_costs'] = df['total_commission'] + df['total_slippage']
    
    return df

def calculate_metrics(df, equity_col='net_pnl_realistic'):
    """Calculate performance metrics."""
    metrics = {}
    
    # Basic stats
    metrics['total_trades'] = len(df)
    metrics['winners'] = (df[equity_col] > 0).sum()
    metrics['losers'] = (df[equity_col] <= 0).sum()
    metrics['win_rate'] = metrics['winners'] / metrics['total_trades'] if metrics['total_trades'] > 0 else 0
    
    # P&L stats
    metrics['total_pnl'] = df[equity_col].sum()
    metrics['avg_pnl'] = df[equity_col].mean()
    metrics['avg_win'] = df[df[equity_col] > 0][equity_col].mean() if metrics['winners'] > 0 else 0
    metrics['avg_loss'] = df[df[equity_col] <= 0][equity_col].mean() if metrics['losers'] > 0 else 0
    
    # Profit factor
    gross_profit = df[df[equity_col] > 0][equity_col].sum()
    gross_loss = abs(df[df[equity_col] <= 0][equity_col].sum())
    metrics['profit_factor'] = gross_profit / gross_loss if gross_loss > 0 else 0
    
    # Equity curve (sort by entry_time for chronological order)
    df_sorted = df.sort_values('entry_time').copy()
    df_sorted['cumulative_pnl'] = df_sorted[equity_col].cumsum()
    df_sorted['equity'] = INITIAL_EQUITY + df_sorted['cumulative_pnl']
    
    metrics['initial_equity'] = INITIAL_EQUITY
    metrics['final_equity'] = df_sorted['equity'].iloc[-1]
    metrics['total_return_pct'] = ((metrics['final_equity'] / INITIAL_EQUITY) - 1) * 100
    
    # Max drawdown
    peak = df_sorted['equity'].expanding().max()
    drawdown = (df_sorted['equity'] - peak) / peak
    metrics['max_drawdown_pct'] = drawdown.min() * 100
    
    # CAGR (5 years)
    years = 5
    metrics['cagr'] = (((metrics['final_equity'] / INITIAL_EQUITY) ** (1/years)) - 1) * 100
    
    # Cost analysis (only if columns exist)
    if 'total_commission' in df.columns:
        metrics['total_commissions'] = df['total_commission'].sum()
        metrics['total_slippage'] = df['total_slippage'].sum()
        metrics['total_costs'] = df['total_costs'].sum()
        metrics['avg_cost_per_trade'] = df['total_costs'].mean()
    else:
        metrics['total_commissions'] = 0
        metrics['total_slippage'] = 0
        metrics['total_costs'] = 0
        metrics['avg_cost_per_trade'] = 0
    
    return metrics, df_sorted

def main():
    print("=" * 80)
    print("REALISTIC TRADING COSTS SIMULATION")
    print("=" * 80)
    print()
    
    # Load original trades
    results_dir = Path(__file__).parent.parent / "results" / "results_combined_top20"
    trades_path = results_dir / "all_trades.csv"
    trades = pd.read_csv(trades_path, parse_dates=['date', 'entry_time', 'exit_time'])
    
    print(f"Loaded {len(trades):,} trades from backtest")
    print()
    
    # Calculate original metrics
    print("ORIGINAL BACKTEST RESULTS:")
    print("-" * 80)
    original_metrics, _ = calculate_metrics(trades, equity_col='net_pnl')
    print(f"Initial Equity: ${original_metrics['initial_equity']:,.2f}")
    print(f"Final Equity: ${original_metrics['final_equity']:,.2f}")
    print(f"Total Return: {original_metrics['total_return_pct']:.2f}%")
    print(f"CAGR: {original_metrics['cagr']:.2f}%")
    print(f"Max Drawdown: {original_metrics['max_drawdown_pct']:.2f}%")
    print(f"Win Rate: {original_metrics['win_rate']*100:.2f}%")
    print(f"Profit Factor: {original_metrics['profit_factor']:.2f}")
    print(f"Avg Win: ${original_metrics['avg_win']:.2f}")
    print(f"Avg Loss: ${original_metrics['avg_loss']:.2f}")
    print()
    
    # Apply realistic costs
    print("=" * 80)
    trades_realistic = apply_realistic_costs(trades)
    
    # Calculate realistic metrics
    print()
    print("REALISTIC SIMULATION RESULTS:")
    print("-" * 80)
    realistic_metrics, equity_df = calculate_metrics(trades_realistic, equity_col='net_pnl_realistic')
    print(f"Initial Equity: ${realistic_metrics['initial_equity']:,.2f}")
    print(f"Final Equity: ${realistic_metrics['final_equity']:,.2f}")
    print(f"Total Return: {realistic_metrics['total_return_pct']:.2f}%")
    print(f"CAGR: {realistic_metrics['cagr']:.2f}%")
    print(f"Max Drawdown: {realistic_metrics['max_drawdown_pct']:.2f}%")
    print(f"Win Rate: {realistic_metrics['win_rate']*100:.2f}%")
    print(f"Profit Factor: {realistic_metrics['profit_factor']:.2f}")
    print(f"Avg Win: ${realistic_metrics['avg_win']:.2f}")
    print(f"Avg Loss: ${realistic_metrics['avg_loss']:.2f}")
    print()
    
    # Cost breakdown
    print("COST BREAKDOWN:")
    print("-" * 80)
    print(f"Total Commissions: ${realistic_metrics['total_commissions']:,.2f}")
    print(f"Total Slippage: ${realistic_metrics['total_slippage']:,.2f}")
    print(f"Total Costs: ${realistic_metrics['total_costs']:,.2f}")
    print(f"Avg Cost per Trade: ${realistic_metrics['avg_cost_per_trade']:.2f}")
    print()
    
    # Impact analysis
    print("IMPACT ANALYSIS:")
    print("-" * 80)
    pnl_reduction = original_metrics['final_equity'] - realistic_metrics['final_equity']
    pnl_reduction_pct = (pnl_reduction / original_metrics['final_equity']) * 100
    
    return_reduction = original_metrics['total_return_pct'] - realistic_metrics['total_return_pct']
    cagr_reduction = original_metrics['cagr'] - realistic_metrics['cagr']
    
    print(f"Equity Reduction: ${pnl_reduction:,.2f} ({pnl_reduction_pct:.2f}%)")
    print(f"Return Reduction: {return_reduction:.2f} percentage points")
    print(f"CAGR Reduction: {cagr_reduction:.2f} percentage points")
    print()
    
    # Costs as % of gross profit
    gross_profit_original = trades[trades['net_pnl'] > 0]['net_pnl'].sum()
    cost_pct_of_profit = (realistic_metrics['total_costs'] / gross_profit_original) * 100
    print(f"Costs as % of Gross Profit: {cost_pct_of_profit:.2f}%")
    print()
    
    # Save realistic trades
    output_path = results_dir / "trades_realistic_costs.csv"
    trades_realistic.to_csv(output_path, index=False)
    print(f"Saved realistic trades to: {output_path}")
    print()
    
    # Save summary to markdown
    summary_path = results_dir / "real_simulation_summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("# Realistic Trading Costs Simulation\n\n")
        f.write("## Methodology\n\n")
        f.write("This simulation applies real-world trading costs to backtest results:\n\n")
        f.write(f"1. **IBKR Commissions**: ${COMMISSION_PER_SHARE:.4f} per share, minimum ${MIN_COMMISSION_PER_ORDER:.2f} per order\n")
        f.write(f"2. **Slippage**: {SLIPPAGE_PCT_MIN*100:.2f}%-{SLIPPAGE_PCT_MAX*100:.2f}% per order (entry + exit)\n")
        f.write("3. **Entry Delay**: 1 bar delay simulating market drift (0.1-0.3% adverse movement)\n\n")
        
        f.write("## Results Comparison\n\n")
        f.write("| Metric | Original Backtest | Realistic Simulation | Difference |\n")
        f.write("|--------|------------------|---------------------|------------|\n")
        f.write(f"| Initial Equity | ${original_metrics['initial_equity']:,.2f} | ${realistic_metrics['initial_equity']:,.2f} | - |\n")
        f.write(f"| Final Equity | ${original_metrics['final_equity']:,.2f} | ${realistic_metrics['final_equity']:,.2f} | -${pnl_reduction:,.2f} ({pnl_reduction_pct:.1f}%) |\n")
        f.write(f"| Total Return | {original_metrics['total_return_pct']:.2f}% | {realistic_metrics['total_return_pct']:.2f}% | -{return_reduction:.2f}pp |\n")
        f.write(f"| CAGR | {original_metrics['cagr']:.2f}% | {realistic_metrics['cagr']:.2f}% | -{cagr_reduction:.2f}pp |\n")
        f.write(f"| Max Drawdown | {original_metrics['max_drawdown_pct']:.2f}% | {realistic_metrics['max_drawdown_pct']:.2f}% | {realistic_metrics['max_drawdown_pct'] - original_metrics['max_drawdown_pct']:.2f}pp |\n")
        f.write(f"| Win Rate | {original_metrics['win_rate']*100:.2f}% | {realistic_metrics['win_rate']*100:.2f}% | {(realistic_metrics['win_rate'] - original_metrics['win_rate'])*100:.2f}pp |\n")
        f.write(f"| Profit Factor | {original_metrics['profit_factor']:.2f} | {realistic_metrics['profit_factor']:.2f} | {realistic_metrics['profit_factor'] - original_metrics['profit_factor']:.2f} |\n")
        f.write(f"| Avg Win | ${original_metrics['avg_win']:.2f} | ${realistic_metrics['avg_win']:.2f} | ${realistic_metrics['avg_win'] - original_metrics['avg_win']:.2f} |\n")
        f.write(f"| Avg Loss | ${original_metrics['avg_loss']:.2f} | ${realistic_metrics['avg_loss']:.2f} | ${realistic_metrics['avg_loss'] - original_metrics['avg_loss']:.2f} |\n")
        
        f.write("\n## Cost Breakdown\n\n")
        f.write(f"- **Total Commissions**: ${realistic_metrics['total_commissions']:,.2f}\n")
        f.write(f"- **Total Slippage**: ${realistic_metrics['total_slippage']:,.2f}\n")
        f.write(f"- **Total Costs**: ${realistic_metrics['total_costs']:,.2f}\n")
        f.write(f"- **Average Cost per Trade**: ${realistic_metrics['avg_cost_per_trade']:.2f}\n")
        f.write(f"- **Costs as % of Gross Profit**: {cost_pct_of_profit:.2f}%\n\n")
        
        f.write("## Key Insights\n\n")
        
        if realistic_metrics['final_equity'] > original_metrics['initial_equity']:
            f.write("✅ **Strategy remains profitable** after realistic costs\n\n")
        else:
            f.write("❌ **Strategy becomes unprofitable** after realistic costs\n\n")
        
        f.write(f"- Realistic costs reduce final equity by **{pnl_reduction_pct:.1f}%**\n")
        f.write(f"- CAGR drops from **{original_metrics['cagr']:.1f}%** to **{realistic_metrics['cagr']:.1f}%**\n")
        f.write(f"- Trading costs consume **{cost_pct_of_profit:.1f}%** of gross profits\n")
        
        if realistic_metrics['cagr'] > 50:
            f.write(f"\n**Conclusion**: Despite costs, strategy shows strong performance with {realistic_metrics['cagr']:.1f}% CAGR\n")
        elif realistic_metrics['cagr'] > 20:
            f.write(f"\n**Conclusion**: Strategy remains viable with {realistic_metrics['cagr']:.1f}% CAGR after realistic costs\n")
        else:
            f.write(f"\n**Conclusion**: Strategy performance is significantly impacted by realistic costs ({realistic_metrics['cagr']:.1f}% CAGR)\n")
    
    print(f"Saved summary to: {summary_path}")
    print()
    print("=" * 80)
    print("Simulation Complete!")
    print("=" * 80)

if __name__ == "__main__":
    np.random.seed(42)  # For reproducibility
    main()
