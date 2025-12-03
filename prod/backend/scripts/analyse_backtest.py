"""
Comprehensive backtest analytics with visualisations and markdown report.

Usage:
    python analyse_backtest.py --run orb_atr_atr050
    python analyse_backtest.py --run orb_atr_atr050 --rolling 50

Outputs:
    - data/backtest/{run}/images/*.png
    - data/backtest/{run}/backtest_report.md
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

# ============ CONFIG ============

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "backtest"
STARTING_CAPITAL = 1000.0

# Matplotlib settings
plt.rcParams['figure.figsize'] = (14, 7)
plt.rcParams['font.size'] = 12
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['axes.labelsize'] = 12
sns.set_style("whitegrid")


# ============ DATA LOADING ============

def load_data(run_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load trade and daily performance data."""
    run_dir = DATA_DIR / run_name
    
    trades_file = run_dir / "simulated_trades.parquet"
    daily_file = run_dir / "daily_performance.parquet"
    
    if not trades_file.exists():
        raise FileNotFoundError(f"Trades file not found: {trades_file}")
    if not daily_file.exists():
        raise FileNotFoundError(f"Daily file not found: {daily_file}")
    
    trades = pd.read_parquet(trades_file)
    daily = pd.read_parquet(daily_file)
    
    # Ensure date columns are datetime
    trades['trade_date'] = pd.to_datetime(trades['trade_date'])
    daily['date'] = pd.to_datetime(daily['date'])
    
    return trades, daily


# ============ SUMMARY STATS ============

def compute_summary(trades: pd.DataFrame, daily: pd.DataFrame) -> dict:
    """Compute comprehensive summary statistics."""
    entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()
    
    # Basic counts
    total_trades = len(trades)
    trades_entered = len(entered)
    entry_rate = trades_entered / total_trades * 100 if total_trades > 0 else 0
    
    # Win/Loss
    winners = entered[entered['pnl_pct'] > 0]
    losers = entered[entered['pnl_pct'] < 0]
    win_rate = len(winners) / trades_entered * 100 if trades_entered > 0 else 0
    
    # P&L
    total_pnl = entered['base_dollar_pnl'].sum()
    total_pnl_leveraged = entered['dollar_pnl'].sum()
    gross_profit = winners['base_dollar_pnl'].sum() if len(winners) > 0 else 0
    gross_loss = abs(losers['base_dollar_pnl'].sum()) if len(losers) > 0 else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Averages
    avg_winner = winners['pnl_pct'].mean() if len(winners) > 0 else 0
    avg_loser = losers['pnl_pct'].mean() if len(losers) > 0 else 0
    avg_trade = entered['pnl_pct'].mean() if trades_entered > 0 else 0
    avg_winner_dollars = winners['base_dollar_pnl'].mean() if len(winners) > 0 else 0
    avg_loser_dollars = losers['base_dollar_pnl'].mean() if len(losers) > 0 else 0
    
    # Expectancy
    win_prob = len(winners) / trades_entered if trades_entered > 0 else 0
    loss_prob = len(losers) / trades_entered if trades_entered > 0 else 0
    expectancy = (win_prob * avg_winner_dollars) + (loss_prob * avg_loser_dollars)
    
    # Best/Worst trades
    best_trade = entered.loc[entered['pnl_pct'].idxmax()] if trades_entered > 0 else None
    worst_trade = entered.loc[entered['pnl_pct'].idxmin()] if trades_entered > 0 else None
    
    # Daily stats
    daily_sorted = daily.sort_values('date').copy()
    daily_sorted['cumulative_pnl'] = daily_sorted['total_base_pnl'].cumsum()
    daily_sorted['equity'] = STARTING_CAPITAL + daily_sorted['cumulative_pnl']
    
    # Drawdown
    daily_sorted['peak'] = daily_sorted['equity'].cummax()
    daily_sorted['drawdown'] = (daily_sorted['peak'] - daily_sorted['equity']) / daily_sorted['peak'] * 100
    max_drawdown = daily_sorted['drawdown'].max()
    max_dd_idx = daily_sorted['drawdown'].idxmax()
    max_dd_date = daily_sorted.loc[max_dd_idx, 'date'] if max_drawdown > 0 else None
    
    # Best/Worst days
    best_day = daily_sorted.loc[daily_sorted['total_base_pnl'].idxmax()]
    worst_day = daily_sorted.loc[daily_sorted['total_base_pnl'].idxmin()]
    
    # Winning/Losing days
    winning_days = (daily_sorted['total_base_pnl'] > 0).sum()
    losing_days = (daily_sorted['total_base_pnl'] < 0).sum()
    daily_win_rate = winning_days / len(daily_sorted) * 100 if len(daily_sorted) > 0 else 0
    
    # Sharpe ratio (annualised, assuming 252 trading days)
    daily_returns = daily_sorted['total_base_pnl'] / STARTING_CAPITAL
    sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if daily_returns.std() > 0 else 0
    
    # Streak analysis
    streaks = compute_streaks(daily_sorted)
    
    return {
        # Counts
        'total_trades': total_trades,
        'trades_entered': trades_entered,
        'entry_rate': entry_rate,
        'trading_days': len(daily_sorted),
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': win_rate,
        
        # P&L
        'total_pnl': total_pnl,
        'total_pnl_leveraged': total_pnl_leveraged,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'profit_factor': profit_factor,
        
        # Averages
        'avg_winner_pct': avg_winner,
        'avg_loser_pct': avg_loser,
        'avg_trade_pct': avg_trade,
        'avg_winner_dollars': avg_winner_dollars,
        'avg_loser_dollars': avg_loser_dollars,
        'expectancy': expectancy,
        
        # Best/Worst
        'best_trade_pct': best_trade['pnl_pct'] if best_trade is not None else 0,
        'best_trade_ticker': best_trade['ticker'] if best_trade is not None else '',
        'best_trade_date': best_trade['trade_date'] if best_trade is not None else '',
        'worst_trade_pct': worst_trade['pnl_pct'] if worst_trade is not None else 0,
        'worst_trade_ticker': worst_trade['ticker'] if worst_trade is not None else '',
        'worst_trade_date': worst_trade['trade_date'] if worst_trade is not None else '',
        'best_day_pnl': best_day['total_base_pnl'],
        'best_day_date': best_day['date'],
        'worst_day_pnl': worst_day['total_base_pnl'],
        'worst_day_date': worst_day['date'],
        
        # Risk
        'max_drawdown': max_drawdown,
        'max_dd_date': max_dd_date,
        'sharpe_ratio': sharpe,
        'winning_days': winning_days,
        'losing_days': losing_days,
        'daily_win_rate': daily_win_rate,
        
        # Streaks
        **streaks,
    }


def compute_streaks(daily: pd.DataFrame) -> dict:
    """Compute winning and losing streaks at daily level."""
    daily = daily.sort_values('date').copy()
    
    # Track streaks
    max_win_streak = 0
    max_win_streak_pnl = 0.0
    max_win_streak_start = None
    max_win_streak_end = None
    
    max_loss_streak = 0
    max_loss_streak_pnl = 0.0
    max_loss_streak_start = None
    max_loss_streak_end = None
    
    current_win_streak = 0
    current_win_streak_pnl = 0.0
    current_win_streak_start = None
    
    current_loss_streak = 0
    current_loss_streak_pnl = 0.0
    current_loss_streak_start = None
    
    for _, row in daily.iterrows():
        pnl = row['total_base_pnl']
        date = row['date']
        
        if pnl > 0:
            # Winning day
            if current_win_streak == 0:
                current_win_streak_start = date
            current_win_streak += 1
            current_win_streak_pnl += pnl
            
            if current_win_streak > max_win_streak:
                max_win_streak = current_win_streak
                max_win_streak_pnl = current_win_streak_pnl
                max_win_streak_start = current_win_streak_start
                max_win_streak_end = date
            
            # Reset loss streak
            current_loss_streak = 0
            current_loss_streak_pnl = 0.0
            current_loss_streak_start = None
            
        elif pnl < 0:
            # Losing day
            if current_loss_streak == 0:
                current_loss_streak_start = date
            current_loss_streak += 1
            current_loss_streak_pnl += pnl
            
            if current_loss_streak > max_loss_streak:
                max_loss_streak = current_loss_streak
                max_loss_streak_pnl = current_loss_streak_pnl
                max_loss_streak_start = current_loss_streak_start
                max_loss_streak_end = date
            
            # Reset win streak
            current_win_streak = 0
            current_win_streak_pnl = 0.0
            current_win_streak_start = None
    
    return {
        'max_win_streak_days': max_win_streak,
        'max_win_streak_pnl': max_win_streak_pnl,
        'max_win_streak_start': max_win_streak_start,
        'max_win_streak_end': max_win_streak_end,
        'max_loss_streak_days': max_loss_streak,
        'max_loss_streak_pnl': max_loss_streak_pnl,
        'max_loss_streak_start': max_loss_streak_start,
        'max_loss_streak_end': max_loss_streak_end,
    }


# ============ MILESTONE TABLES ============

def compute_monthly_performance(trades: pd.DataFrame) -> pd.DataFrame:
    """Compute monthly P&L breakdown."""
    entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()
    entered['month'] = entered['trade_date'].dt.to_period('M')
    
    monthly = entered.groupby('month').agg(
        trades=('ticker', 'count'),
        winners=('pnl_pct', lambda x: (x > 0).sum()),
        losers=('pnl_pct', lambda x: (x < 0).sum()),
        pnl=('base_dollar_pnl', 'sum'),
        pnl_pct=('pnl_pct', 'sum'),
    ).reset_index()
    
    monthly['win_rate'] = monthly['winners'] / monthly['trades'] * 100
    monthly['cumulative_pnl'] = monthly['pnl'].cumsum()
    monthly['month_str'] = monthly['month'].astype(str)
    
    return monthly


def compute_yearly_performance(trades: pd.DataFrame) -> pd.DataFrame:
    """Compute yearly P&L breakdown."""
    entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()
    entered['year'] = entered['trade_date'].dt.year
    
    yearly = entered.groupby('year').agg(
        trades=('ticker', 'count'),
        winners=('pnl_pct', lambda x: (x > 0).sum()),
        losers=('pnl_pct', lambda x: (x < 0).sum()),
        pnl=('base_dollar_pnl', 'sum'),
        pnl_pct=('pnl_pct', 'sum'),
        trading_days=('trade_date', lambda x: x.dt.date.nunique()),
    ).reset_index()
    
    yearly['win_rate'] = yearly['winners'] / yearly['trades'] * 100
    yearly['avg_daily_pnl'] = yearly['pnl'] / yearly['trading_days']
    
    return yearly


def compute_dow_performance(trades: pd.DataFrame) -> pd.DataFrame:
    """Compute day-of-week performance."""
    entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()
    entered['dow'] = entered['trade_date'].dt.dayofweek
    entered['dow_name'] = entered['trade_date'].dt.day_name()
    
    dow = entered.groupby(['dow', 'dow_name']).agg(
        trades=('ticker', 'count'),
        winners=('pnl_pct', lambda x: (x > 0).sum()),
        pnl=('base_dollar_pnl', 'sum'),
    ).reset_index()
    
    dow['win_rate'] = dow['winners'] / dow['trades'] * 100
    dow = dow.sort_values('dow')
    
    return dow


def compute_direction_performance(trades: pd.DataFrame) -> pd.DataFrame:
    """Compute LONG vs SHORT performance."""
    entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()
    
    direction = entered.groupby('side').agg(
        trades=('ticker', 'count'),
        winners=('pnl_pct', lambda x: (x > 0).sum()),
        losers=('pnl_pct', lambda x: (x < 0).sum()),
        pnl=('base_dollar_pnl', 'sum'),
        avg_pnl_pct=('pnl_pct', 'mean'),
    ).reset_index()
    
    direction['win_rate'] = direction['winners'] / direction['trades'] * 100
    
    return direction


def compute_exit_reason_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    """Compute exit reason breakdown."""
    entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()
    
    breakdown = entered.groupby('exit_reason').agg(
        trades=('ticker', 'count'),
        pnl=('base_dollar_pnl', 'sum'),
        avg_pnl_pct=('pnl_pct', 'mean'),
        win_rate=('pnl_pct', lambda x: (x > 0).mean() * 100),
    ).reset_index()
    
    return breakdown


def compute_rank_performance(trades: pd.DataFrame) -> pd.DataFrame:
    """Compute performance by RVOL rank bucket."""
    entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()
    
    # Create rank buckets
    max_rank = entered['rvol_rank'].max()
    if max_rank <= 20:
        bins = [0, 5, 10, 15, 20]
        labels = ['1-5', '6-10', '11-15', '16-20']
    else:
        bins = [0, 5, 10, 15, 20, 30, 40, 50]
        labels = ['1-5', '6-10', '11-15', '16-20', '21-30', '31-40', '41-50']
    
    entered['rank_bin'] = pd.cut(entered['rvol_rank'], bins=bins, labels=labels[:len(bins)-1])
    
    rank_perf = entered.groupby('rank_bin', observed=True).agg(
        trades=('ticker', 'count'),
        winners=('pnl_pct', lambda x: (x > 0).sum()),
        pnl=('base_dollar_pnl', 'sum'),
        avg_pnl_pct=('pnl_pct', 'mean'),
    ).reset_index()
    
    rank_perf['win_rate'] = rank_perf['winners'] / rank_perf['trades'] * 100
    
    return rank_perf


def compute_top_tickers(trades: pd.DataFrame, n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute top and bottom performing tickers."""
    entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()
    
    ticker_perf = entered.groupby('ticker').agg(
        trades=('pnl_pct', 'count'),
        pnl=('base_dollar_pnl', 'sum'),
        win_rate=('pnl_pct', lambda x: (x > 0).mean() * 100),
    ).reset_index()
    
    top = ticker_perf.nlargest(n, 'pnl')
    bottom = ticker_perf.nsmallest(n, 'pnl')
    
    return top, bottom


# ============ VISUALISATIONS ============

def plot_equity_curve(daily: pd.DataFrame, summary: dict, out_dir: Path) -> str:
    """Plot equity curve with drawdown shading."""
    daily = daily.sort_values('date').copy()
    daily['cumulative_pnl'] = daily['total_base_pnl'].cumsum()
    daily['equity'] = STARTING_CAPITAL + daily['cumulative_pnl']
    daily['peak'] = daily['equity'].cummax()
    daily['drawdown'] = (daily['peak'] - daily['equity']) / daily['peak'] * 100
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), height_ratios=[3, 1], sharex=True)
    
    # Equity curve
    ax1.plot(daily['date'], daily['equity'], linewidth=2, color='steelblue', label='Equity')
    ax1.fill_between(daily['date'], STARTING_CAPITAL, daily['equity'], alpha=0.3, color='steelblue')
    ax1.axhline(STARTING_CAPITAL, color='gray', linestyle='--', alpha=0.5, label='Starting Capital')
    ax1.set_ylabel('Equity ($)')
    ax1.set_title(f'Equity Curve (${STARTING_CAPITAL:,.0f} → ${daily["equity"].iloc[-1]:,.2f})')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    # Drawdown
    ax2.fill_between(daily['date'], 0, -daily['drawdown'], alpha=0.7, color='crimson')
    ax2.set_ylabel('Drawdown (%)')
    ax2.set_xlabel('Date')
    ax2.set_ylim(-summary['max_drawdown'] * 1.1, 0)
    ax2.grid(True, alpha=0.3)
    
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    path = out_dir / 'equity_curve.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return 'equity_curve.png'


def plot_monthly_pnl(monthly: pd.DataFrame, out_dir: Path) -> str:
    """Plot monthly P&L bar chart."""
    fig, ax = plt.subplots(figsize=(16, 7))
    
    colors = ['green' if x > 0 else 'red' for x in monthly['pnl']]
    bars = ax.bar(range(len(monthly)), monthly['pnl'], color=colors, alpha=0.7, edgecolor='black')
    
    ax.axhline(0, color='black', linewidth=0.5)
    ax.set_xticks(range(len(monthly)))
    ax.set_xticklabels(monthly['month_str'], rotation=45, ha='right')
    ax.set_xlabel('Month')
    ax.set_ylabel('P&L ($)')
    ax.set_title(f'Monthly P&L (Total: ${monthly["pnl"].sum():,.2f})')
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    path = out_dir / 'monthly_pnl.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return 'monthly_pnl.png'


def plot_yearly_pnl(yearly: pd.DataFrame, out_dir: Path) -> str:
    """Plot yearly P&L bar chart."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    colors = ['green' if x > 0 else 'red' for x in yearly['pnl']]
    bars = ax.bar(yearly['year'].astype(str), yearly['pnl'], color=colors, alpha=0.7, edgecolor='black')
    
    for bar, val in zip(bars, yearly['pnl']):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, height, f'${val:,.0f}', 
                ha='center', va='bottom' if height > 0 else 'top', fontsize=11)
    
    ax.axhline(0, color='black', linewidth=0.5)
    ax.set_xlabel('Year')
    ax.set_ylabel('P&L ($)')
    ax.set_title('Yearly P&L')
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    path = out_dir / 'yearly_pnl.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return 'yearly_pnl.png'


def plot_rolling_winrate(daily: pd.DataFrame, window: int, out_dir: Path) -> str:
    """Plot rolling win rate."""
    daily = daily.sort_values('date').copy()
    daily['is_winner'] = (daily['total_base_pnl'] > 0).astype(int)
    daily['rolling_winrate'] = daily['is_winner'].rolling(window=window, min_periods=window).mean() * 100
    
    fig, ax = plt.subplots(figsize=(14, 6))
    
    ax.plot(daily['date'], daily['rolling_winrate'], linewidth=2, color='steelblue')
    ax.axhline(50, color='gray', linestyle='--', alpha=0.7, label='50%')
    ax.axhline(daily['rolling_winrate'].mean(), color='orange', linestyle='--', alpha=0.7, 
               label=f'Mean: {daily["rolling_winrate"].mean():.1f}%')
    
    ax.set_xlabel('Date')
    ax.set_ylabel('Win Rate (%)')
    ax.set_title(f'{window}-Day Rolling Win Rate')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    path = out_dir / f'rolling_winrate_{window}d.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return f'rolling_winrate_{window}d.png'


def plot_dow_performance(dow: pd.DataFrame, out_dir: Path) -> str:
    """Plot day-of-week performance."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # P&L by day
    colors = ['green' if x > 0 else 'red' for x in dow['pnl']]
    ax1.bar(dow['dow_name'], dow['pnl'], color=colors, alpha=0.7, edgecolor='black')
    ax1.axhline(0, color='black', linewidth=0.5)
    ax1.set_xlabel('Day of Week')
    ax1.set_ylabel('Total P&L ($)')
    ax1.set_title('P&L by Day of Week')
    ax1.grid(True, alpha=0.3, axis='y')
    
    # Win rate by day
    ax2.bar(dow['dow_name'], dow['win_rate'], color='steelblue', alpha=0.7, edgecolor='black')
    ax2.axhline(dow['win_rate'].mean(), color='orange', linestyle='--', label=f'Mean: {dow["win_rate"].mean():.1f}%')
    ax2.set_xlabel('Day of Week')
    ax2.set_ylabel('Win Rate (%)')
    ax2.set_title('Win Rate by Day of Week')
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    path = out_dir / 'dow_performance.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return 'dow_performance.png'


def plot_direction_performance(direction: pd.DataFrame, out_dir: Path) -> str:
    """Plot LONG vs SHORT performance."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    # Trade count
    axes[0].bar(direction['side'], direction['trades'], color=['steelblue', 'coral'], alpha=0.7, edgecolor='black')
    axes[0].set_title('Trade Count')
    axes[0].set_ylabel('Count')
    
    # Win rate
    axes[1].bar(direction['side'], direction['win_rate'], color=['steelblue', 'coral'], alpha=0.7, edgecolor='black')
    axes[1].axhline(direction['win_rate'].mean(), color='gray', linestyle='--')
    axes[1].set_title('Win Rate (%)')
    axes[1].set_ylabel('Win Rate (%)')
    
    # P&L
    colors = ['green' if x > 0 else 'red' for x in direction['pnl']]
    axes[2].bar(direction['side'], direction['pnl'], color=colors, alpha=0.7, edgecolor='black')
    axes[2].axhline(0, color='black', linewidth=0.5)
    axes[2].set_title('Total P&L ($)')
    axes[2].set_ylabel('P&L ($)')
    
    plt.suptitle('LONG vs SHORT Performance', fontsize=14)
    plt.tight_layout()
    path = out_dir / 'direction_performance.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return 'direction_performance.png'


def plot_rank_performance(rank_perf: pd.DataFrame, out_dir: Path) -> str:
    """Plot performance by RVOL rank bucket."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # P&L by rank
    colors = ['green' if x > 0 else 'red' for x in rank_perf['pnl']]
    ax1.bar(rank_perf['rank_bin'].astype(str), rank_perf['pnl'], color=colors, alpha=0.7, edgecolor='black')
    ax1.axhline(0, color='black', linewidth=0.5)
    ax1.set_xlabel('RVOL Rank Bucket')
    ax1.set_ylabel('Total P&L ($)')
    ax1.set_title('P&L by RVOL Rank')
    ax1.grid(True, alpha=0.3, axis='y')
    
    # Win rate by rank
    ax2.bar(rank_perf['rank_bin'].astype(str), rank_perf['win_rate'], color='steelblue', alpha=0.7, edgecolor='black')
    ax2.axhline(rank_perf['win_rate'].mean(), color='orange', linestyle='--', label=f'Mean: {rank_perf["win_rate"].mean():.1f}%')
    ax2.set_xlabel('RVOL Rank Bucket')
    ax2.set_ylabel('Win Rate (%)')
    ax2.set_title('Win Rate by RVOL Rank')
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    path = out_dir / 'rank_performance.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return 'rank_performance.png'


def plot_exit_reasons(breakdown: pd.DataFrame, out_dir: Path) -> str:
    """Plot exit reason breakdown."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Count
    ax1.bar(breakdown['exit_reason'], breakdown['trades'], color='steelblue', alpha=0.7, edgecolor='black')
    ax1.set_xlabel('Exit Reason')
    ax1.set_ylabel('Trade Count')
    ax1.set_title('Exit Reason Distribution')
    ax1.tick_params(axis='x', rotation=45)
    
    # P&L
    colors = ['green' if x > 0 else 'red' for x in breakdown['pnl']]
    ax2.bar(breakdown['exit_reason'], breakdown['pnl'], color=colors, alpha=0.7, edgecolor='black')
    ax2.axhline(0, color='black', linewidth=0.5)
    ax2.set_xlabel('Exit Reason')
    ax2.set_ylabel('Total P&L ($)')
    ax2.set_title('P&L by Exit Reason')
    ax2.tick_params(axis='x', rotation=45)
    
    plt.tight_layout()
    path = out_dir / 'exit_reasons.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return 'exit_reasons.png'


def plot_pnl_histogram(trades: pd.DataFrame, out_dir: Path) -> str:
    """Plot P&L distribution histogram."""
    entered = trades[trades['exit_reason'] != 'NO_ENTRY'].copy()
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    ax.hist(entered['pnl_pct'].dropna(), bins=50, edgecolor='black', alpha=0.7, color='steelblue')
    ax.axvline(0, color='red', linestyle='--', linewidth=2)
    ax.axvline(entered['pnl_pct'].mean(), color='orange', linestyle='--', linewidth=2, 
               label=f'Mean: {entered["pnl_pct"].mean():.2f}%')
    
    ax.set_xlabel('P&L %')
    ax.set_ylabel('Frequency')
    ax.set_title(f'P&L Distribution (N={len(entered):,})')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    path = out_dir / 'pnl_histogram.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return 'pnl_histogram.png'


def plot_top_tickers(top: pd.DataFrame, bottom: pd.DataFrame, out_dir: Path) -> str:
    """Plot top and bottom tickers."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Top performers
    ax1.barh(top['ticker'], top['pnl'], color='green', alpha=0.7, edgecolor='black')
    ax1.set_xlabel('Total P&L ($)')
    ax1.set_title('Top 10 Tickers by P&L')
    ax1.invert_yaxis()
    ax1.grid(True, alpha=0.3, axis='x')
    
    # Bottom performers
    ax2.barh(bottom['ticker'], bottom['pnl'], color='red', alpha=0.7, edgecolor='black')
    ax2.set_xlabel('Total P&L ($)')
    ax2.set_title('Bottom 10 Tickers by P&L')
    ax2.invert_yaxis()
    ax2.grid(True, alpha=0.3, axis='x')
    
    plt.tight_layout()
    path = out_dir / 'top_bottom_tickers.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    return 'top_bottom_tickers.png'


# ============ MARKDOWN REPORT ============

def generate_report(
    run_name: str,
    summary: dict,
    monthly: pd.DataFrame,
    yearly: pd.DataFrame,
    dow: pd.DataFrame,
    direction: pd.DataFrame,
    exit_breakdown: pd.DataFrame,
    rank_perf: pd.DataFrame,
    top_tickers: pd.DataFrame,
    bottom_tickers: pd.DataFrame,
    images: list[str],
    out_dir: Path,
) -> str:
    """Generate comprehensive markdown report."""
    
    report = f"""# Backtest Report: {run_name}

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Total Trades** | {summary['total_trades']:,} |
| **Trades Entered** | {summary['trades_entered']:,} ({summary['entry_rate']:.1f}%) |
| **Trading Days** | {summary['trading_days']:,} |
| **Win Rate** | {summary['win_rate']:.1f}% |
| **Profit Factor** | {summary['profit_factor']:.2f} |
| **Total P&L (1x)** | ${summary['total_pnl']:,.2f} |
| **Total P&L (2x)** | ${summary['total_pnl_leveraged']:,.2f} |
| **Expectancy** | ${summary['expectancy']:.2f} per trade |
| **Sharpe Ratio** | {summary['sharpe_ratio']:.2f} |
| **Max Drawdown** | {summary['max_drawdown']:.1f}% |

---

## Win/Loss Statistics

| Metric | Value |
|--------|-------|
| Winners | {summary['winners']:,} |
| Losers | {summary['losers']:,} |
| Avg Winner | {summary['avg_winner_pct']:.2f}% (${summary['avg_winner_dollars']:.2f}) |
| Avg Loser | {summary['avg_loser_pct']:.2f}% (${summary['avg_loser_dollars']:.2f}) |
| Win/Loss Ratio | {abs(summary['avg_winner_pct'] / summary['avg_loser_pct']):.2f} |
| Winning Days | {summary['winning_days']} ({summary['daily_win_rate']:.1f}%) |
| Losing Days | {summary['losing_days']} |

---

## Streak Analysis

### Longest Winning Streak
- **Days:** {summary['max_win_streak_days']}
- **P&L:** ${summary['max_win_streak_pnl']:,.2f}
- **Period:** {summary['max_win_streak_start'].strftime('%Y-%m-%d') if summary['max_win_streak_start'] else 'N/A'} → {summary['max_win_streak_end'].strftime('%Y-%m-%d') if summary['max_win_streak_end'] else 'N/A'}

### Longest Losing Streak
- **Days:** {summary['max_loss_streak_days']}
- **P&L:** ${summary['max_loss_streak_pnl']:,.2f}
- **Period:** {summary['max_loss_streak_start'].strftime('%Y-%m-%d') if summary['max_loss_streak_start'] else 'N/A'} → {summary['max_loss_streak_end'].strftime('%Y-%m-%d') if summary['max_loss_streak_end'] else 'N/A'}

---

## Best & Worst

| Category | Value | Details |
|----------|-------|---------|
| **Best Trade** | {summary['best_trade_pct']:.2f}% | {summary['best_trade_ticker']} on {pd.Timestamp(summary['best_trade_date']).strftime('%Y-%m-%d') if summary['best_trade_date'] else 'N/A'} |
| **Worst Trade** | {summary['worst_trade_pct']:.2f}% | {summary['worst_trade_ticker']} on {pd.Timestamp(summary['worst_trade_date']).strftime('%Y-%m-%d') if summary['worst_trade_date'] else 'N/A'} |
| **Best Day** | ${summary['best_day_pnl']:,.2f} | {pd.Timestamp(summary['best_day_date']).strftime('%Y-%m-%d')} |
| **Worst Day** | ${summary['worst_day_pnl']:,.2f} | {pd.Timestamp(summary['worst_day_date']).strftime('%Y-%m-%d')} |
| **Max Drawdown** | {summary['max_drawdown']:.1f}% | {pd.Timestamp(summary['max_dd_date']).strftime('%Y-%m-%d') if summary['max_dd_date'] else 'N/A'} |

---

## Equity Curve

![Equity Curve](images/equity_curve.png)

---

## Yearly Performance

| Year | Trades | Win Rate | P&L | Avg Daily P&L |
|------|--------|----------|-----|---------------|
"""
    
    for _, row in yearly.iterrows():
        report += f"| {row['year']} | {row['trades']:,} | {row['win_rate']:.1f}% | ${row['pnl']:,.2f} | ${row['avg_daily_pnl']:.2f} |\n"
    
    report += f"""
![Yearly P&L](images/yearly_pnl.png)

---

## Monthly Performance

<details>
<summary>Click to expand monthly breakdown</summary>

| Month | Trades | Win Rate | P&L | Cumulative |
|-------|--------|----------|-----|------------|
"""
    
    for _, row in monthly.iterrows():
        report += f"| {row['month_str']} | {row['trades']:,} | {row['win_rate']:.1f}% | ${row['pnl']:,.2f} | ${row['cumulative_pnl']:,.2f} |\n"
    
    report += f"""
</details>

![Monthly P&L](images/monthly_pnl.png)

---

## Rolling Performance

![Rolling Win Rate](images/rolling_winrate_20d.png)

---

## Day of Week Analysis

| Day | Trades | Win Rate | P&L |
|-----|--------|----------|-----|
"""
    
    for _, row in dow.iterrows():
        report += f"| {row['dow_name']} | {row['trades']:,} | {row['win_rate']:.1f}% | ${row['pnl']:,.2f} |\n"
    
    report += f"""
![Day of Week](images/dow_performance.png)

---

## Direction Analysis (LONG vs SHORT)

| Side | Trades | Win Rate | P&L | Avg P&L % |
|------|--------|----------|-----|-----------|
"""
    
    for _, row in direction.iterrows():
        report += f"| {row['side']} | {row['trades']:,} | {row['win_rate']:.1f}% | ${row['pnl']:,.2f} | {row['avg_pnl_pct']:.2f}% |\n"
    
    report += f"""
![Direction Performance](images/direction_performance.png)

---

## Exit Reason Analysis

| Exit Reason | Trades | Win Rate | P&L | Avg P&L % |
|-------------|--------|----------|-----|-----------|
"""
    
    for _, row in exit_breakdown.iterrows():
        report += f"| {row['exit_reason']} | {row['trades']:,} | {row['win_rate']:.1f}% | ${row['pnl']:,.2f} | {row['avg_pnl_pct']:.2f}% |\n"
    
    report += f"""
![Exit Reasons](images/exit_reasons.png)

---

## RVOL Rank Analysis

| Rank Bucket | Trades | Win Rate | P&L | Avg P&L % |
|-------------|--------|----------|-----|-----------|
"""
    
    for _, row in rank_perf.iterrows():
        report += f"| {row['rank_bin']} | {row['trades']:,} | {row['win_rate']:.1f}% | ${row['pnl']:,.2f} | {row['avg_pnl_pct']:.2f}% |\n"
    
    report += f"""
![Rank Performance](images/rank_performance.png)

---

## Top Performing Tickers

| Ticker | Trades | Win Rate | P&L |
|--------|--------|----------|-----|
"""
    
    for _, row in top_tickers.iterrows():
        report += f"| {row['ticker']} | {row['trades']:,} | {row['win_rate']:.1f}% | ${row['pnl']:,.2f} |\n"
    
    report += f"""

## Bottom Performing Tickers

| Ticker | Trades | Win Rate | P&L |
|--------|--------|----------|-----|
"""
    
    for _, row in bottom_tickers.iterrows():
        report += f"| {row['ticker']} | {row['trades']:,} | {row['win_rate']:.1f}% | ${row['pnl']:,.2f} |\n"
    
    report += f"""
![Top/Bottom Tickers](images/top_bottom_tickers.png)

---

## P&L Distribution

![P&L Histogram](images/pnl_histogram.png)

---

*Report generated by `analyse_backtest.py`*
"""
    
    # Write report
    report_path = out_dir / 'backtest_report.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    return str(report_path)


# ============ MAIN ============

def main():
    parser = argparse.ArgumentParser(description='Analyse backtest results')
    parser.add_argument('--run', required=True, help='Run name (folder in data/backtest/)')
    parser.add_argument('--rolling', type=int, default=20, help='Rolling window size for metrics')
    args = parser.parse_args()
    
    run_name = args.run
    rolling_window = args.rolling
    
    print(f"═══════════════════════════════════════════════════════════════")
    print(f"  Analysing: {run_name}")
    print(f"  Rolling window: {rolling_window} days")
    print(f"═══════════════════════════════════════════════════════════════")
    
    # Load data
    print("\n📂 Loading data...")
    trades, daily = load_data(run_name)
    print(f"  Trades: {len(trades):,}")
    print(f"  Days: {len(daily):,}")
    
    # Setup output
    run_dir = DATA_DIR / run_name
    img_dir = run_dir / 'images'
    img_dir.mkdir(parents=True, exist_ok=True)
    
    # Compute stats
    print("\n📊 Computing summary statistics...")
    summary = compute_summary(trades, daily)
    print(f"  Win Rate: {summary['win_rate']:.1f}%")
    print(f"  Profit Factor: {summary['profit_factor']:.2f}")
    print(f"  Total P&L: ${summary['total_pnl']:,.2f}")
    print(f"  Entry Rate: {summary['entry_rate']:.1f}%")
    print(f"  Max Losing Streak: {summary['max_loss_streak_days']} days (${summary['max_loss_streak_pnl']:,.2f})")
    
    # Compute breakdowns
    print("\n📈 Computing performance breakdowns...")
    monthly = compute_monthly_performance(trades)
    yearly = compute_yearly_performance(trades)
    dow = compute_dow_performance(trades)
    direction = compute_direction_performance(trades)
    exit_breakdown = compute_exit_reason_breakdown(trades)
    rank_perf = compute_rank_performance(trades)
    top_tickers, bottom_tickers = compute_top_tickers(trades)
    
    # Generate plots
    print("\n🎨 Generating visualisations...")
    images = []
    
    img = plot_equity_curve(daily, summary, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    img = plot_monthly_pnl(monthly, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    img = plot_yearly_pnl(yearly, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    img = plot_rolling_winrate(daily, rolling_window, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    img = plot_dow_performance(dow, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    img = plot_direction_performance(direction, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    img = plot_rank_performance(rank_perf, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    img = plot_exit_reasons(exit_breakdown, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    img = plot_pnl_histogram(trades, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    img = plot_top_tickers(top_tickers, bottom_tickers, img_dir)
    images.append(img)
    print(f"  ✓ {img}")
    
    # Generate report
    print("\n📝 Generating markdown report...")
    report_path = generate_report(
        run_name, summary, monthly, yearly, dow, direction,
        exit_breakdown, rank_perf, top_tickers, bottom_tickers,
        images, run_dir
    )
    print(f"  ✓ {report_path}")
    
    print("\n" + "═" * 65)
    print("  ✅ Analysis complete!")
    print(f"  📁 Output: {run_dir}")
    print("═" * 65)


if __name__ == '__main__':
    main()
