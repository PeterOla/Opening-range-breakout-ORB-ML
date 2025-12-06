"""
Ross Cameron bull flag backtest engine.

Detects bull flags on 5-min bars (impulse + flag + breakout) and simulates:
- Entry: First bar above flag high + $0.01
- Stop: Flag low
- Target: Entry + (2 × risk)
- Exit: Hit target, stop, or 16:00 ET

Output:
- simulated_trades.parquet: entry_time, entry_price, exit_time, exit_price, exit_reason, pnl_pct
- daily_performance.parquet: trade_date, num_trades, win_count, loss_count, win_rate, total_pnl_pct, pnl_per_trade
- equity_curve.parquet: trade_date, cumulative_pnl_pct, cumulative_capital

Usage:
    python scripts/backtest_ross_cameron.py \\
        --universe data/backtest/universe_rc_*.parquet \\
        --run-name rc_top50_compound \\
        --capital 30000 \\
        --compound
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import datetime, time
from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np
import json
from dataclasses import dataclass, asdict
from tqdm import tqdm

OUT_DIR = Path(__file__).resolve().parents[3] / "data" / "backtest"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Bull flag detection params
IMPULSE_THRESHOLD_PCT = 4.0  # At least 4% gain in impulse
IMPULSE_BARS = 6  # Within 6 bars (30 mins)
FLAG_HOLD_PCT = 65.0  # Flag holds at least 65% of impulse gain
FLAG_MIN_BARS = 3  # Minimum flag duration


@dataclass
class Trade:
    trade_date: str
    ticker: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    exit_reason: str  # TARGET, STOP, EOD
    pnl: float
    pnl_pct: float
    risk_reward_ratio: float


def parse_bars_json(bars_json: str) -> pd.DataFrame:
    """Deserialize bars from JSON string."""
    bars = json.loads(bars_json)
    df = pd.DataFrame(bars)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df['time'] = df['datetime'].dt.time
    return df.sort_values('datetime').reset_index(drop=True)


def detect_bull_flag(bars: pd.DataFrame, or_data: dict) -> Optional[dict]:
    """
    Detect bull flag pattern:
    1. Impulse: At least 4% gain within first 6 bars (9:30-10:00)
    2. Flag: Price pulls back but holds at least 65% of impulse
    3. Entry trigger: First bar that closes above flag high

    Returns dict with entry_bar_index or None if no valid flag.
    """
    if len(bars) < IMPULSE_BARS + FLAG_MIN_BARS:
        return None
    
    # Impulse phase (first 6 bars from 9:30)
    impulse = bars.iloc[:IMPULSE_BARS].copy()
    if len(impulse) < IMPULSE_BARS:
        return None
    
    impulse_start = impulse.iloc[0]['open']
    impulse_high = impulse['high'].max()
    impulse_gain_pct = ((impulse_high - impulse_start) / impulse_start) * 100.0
    
    if impulse_gain_pct < IMPULSE_THRESHOLD_PCT:
        return None
    
    impulse_low = impulse['low'].min()
    impulse_gain_abs = impulse_high - impulse_start
    flag_support = impulse_high - (impulse_gain_abs * FLAG_HOLD_PCT / 100.0)
    
    # Flag phase (bars after impulse, until breakout)
    flag_start_idx = IMPULSE_BARS
    
    entry_idx = None
    for i in range(flag_start_idx, len(bars)):
        bar = bars.iloc[i]
        
        # Check if bar holds above support (flag condition)
        if bar['low'] < flag_support:
            # Flag broken to downside, reset detection
            return None
        
        # Check if bar closes above impulse high (entry trigger)
        if bar['close'] > impulse_high:
            entry_idx = i
            break
    
    if entry_idx is None:
        return None
    
    # Validate minimum flag duration
    flag_duration = entry_idx - flag_start_idx
    if flag_duration < FLAG_MIN_BARS:
        return None
    
    return {
        'impulse_start': float(impulse_start),
        'impulse_high': float(impulse_high),
        'impulse_gain_pct': float(impulse_gain_pct),
        'flag_support': float(flag_support),
        'entry_bar_idx': entry_idx,
    }


def simulate_trade(bars: pd.DataFrame, flag_data: dict, or_data: dict) -> Optional[Trade]:
    """
    Simulate single trade from entry trigger through exit.
    
    Entry: First bar above impulse high + $0.01
    Stop: Flag support
    Target: Entry + (2 × risk)
    Exit: Target hit, stop hit, or 16:00 ET
    """
    entry_bar_idx = flag_data['entry_bar_idx']
    entry_bar = bars.iloc[entry_bar_idx]
    entry_price = flag_data['impulse_high'] + 0.01
    
    stop_price = flag_data['flag_support']
    risk = entry_price - stop_price
    target_price = entry_price + (2.0 * risk)
    
    # Check if target/stop is realistic given bar range
    if entry_price > entry_bar['high'] or entry_price < entry_bar['low']:
        return None  # Entry not possible in this bar
    
    # Simulate from entry bar onwards
    for i in range(entry_bar_idx, len(bars)):
        bar = bars.iloc[i]
        bar_time = bar['datetime'].time()
        
        # Stop loss hit
        if bar['low'] <= stop_price:
            exit_price = stop_price
            exit_idx = i
            exit_reason = 'STOP'
            break
        
        # Target hit
        if bar['high'] >= target_price:
            exit_price = target_price
            exit_idx = i
            exit_reason = 'TARGET'
            break
        
        # End of day (16:00 ET)
        if bar_time >= MARKET_CLOSE:
            exit_price = bar['close']
            exit_idx = i
            exit_reason = 'EOD'
            break
    else:
        # Reached end of bars without exit signal
        exit_price = bars.iloc[-1]['close']
        exit_idx = len(bars) - 1
        exit_reason = 'EOD'
    
    exit_bar = bars.iloc[exit_idx]
    pnl = exit_price - entry_price
    pnl_pct = (pnl / entry_price) * 100.0
    rrr = risk / abs(pnl) if pnl != 0 else np.nan
    
    return Trade(
        trade_date=str(entry_bar['datetime'].date()),
        ticker='',  # Set by caller
        entry_time=entry_bar['datetime'].strftime('%Y-%m-%d %H:%M:%S'),
        entry_price=float(entry_price),
        exit_time=exit_bar['datetime'].strftime('%Y-%m-%d %H:%M:%S'),
        exit_price=float(exit_price),
        exit_reason=exit_reason,
        pnl=float(pnl),
        pnl_pct=float(pnl_pct),
        risk_reward_ratio=float(rrr),
    )


def backtest_universe(universe_path: str, capital: float = 30000, compound: bool = True) -> Tuple[list, dict]:
    """
    Run backtest on universe parquet file.
    
    Returns: (trades_list, daily_stats_dict)
    """
    df_universe = pd.read_parquet(universe_path)
    
    trades = []
    daily_stats = {}
    current_capital = capital
    
    print(f"Backtesting {len(df_universe)} candidates from {universe_path.split('/')[-1]}")
    
    for idx, row in tqdm(df_universe.iterrows(), total=len(df_universe), desc="Simulating"):
        trade_date = row['trade_date']
        ticker = row['ticker']
        
        # Deserialize bars
        try:
            bars = parse_bars_json(row['bars_json'])
        except Exception:
            continue
        
        if bars.empty or len(bars) < IMPULSE_BARS + FLAG_MIN_BARS:
            continue
        
        # Detect bull flag
        or_data = {
            'or_open': row['or_open'],
            'or_high': row['or_high'],
            'or_low': row['or_low'],
            'or_close': row['or_close'],
        }
        
        flag_data = detect_bull_flag(bars, or_data)
        if flag_data is None:
            continue
        
        # Simulate trade
        trade = simulate_trade(bars, flag_data, or_data)
        if trade is None:
            continue
        
        trade.ticker = ticker
        trades.append(trade)
        
        # Accumulate daily stats
        if trade_date not in daily_stats:
            daily_stats[trade_date] = {'trades': [], 'pnls': []}
        daily_stats[trade_date]['trades'].append(trade)
        daily_stats[trade_date]['pnls'].append(trade.pnl_pct)
        
        # Update capital if compounding
        if compound:
            current_capital += (current_capital * trade.pnl_pct / 100.0)
    
    return trades, daily_stats


def save_results(trades: list, daily_stats: dict, run_name: str, capital: float = 30000):
    """Save backtest results to parquets + markdown report."""
    out_dir = OUT_DIR / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Trades
    if trades:
        df_trades = pd.DataFrame([asdict(t) for t in trades])
        df_trades.to_parquet(out_dir / "simulated_trades.parquet", index=False)
    
    # 2. Daily performance
    daily_perf = []
    cumulative_pnl_pct = 0.0
    cumulative_capital = capital
    
    for trade_date in sorted(daily_stats.keys()):
        day_trades = daily_stats[trade_date]['trades']
        day_pnls = daily_stats[trade_date]['pnls']
        
        if day_pnls:
            num_trades = len(day_pnls)
            win_count = sum(1 for p in day_pnls if p > 0)
            loss_count = sum(1 for p in day_pnls if p < 0)
            win_rate = (win_count / num_trades * 100.0) if num_trades > 0 else 0.0
            avg_pnl_pct = np.mean(day_pnls)
            total_pnl_pct = np.sum(day_pnls)
            
            cumulative_pnl_pct += total_pnl_pct
            cumulative_capital *= (1.0 + total_pnl_pct / 100.0)
            
            daily_perf.append({
                'trade_date': trade_date,
                'num_trades': num_trades,
                'win_count': win_count,
                'loss_count': loss_count,
                'win_rate_pct': win_rate,
                'total_pnl_pct': total_pnl_pct,
                'avg_pnl_pct': avg_pnl_pct,
                'cumulative_pnl_pct': cumulative_pnl_pct,
                'cumulative_capital': cumulative_capital,
            })
    
    if daily_perf:
        df_daily = pd.DataFrame(daily_perf)
        df_daily.to_parquet(out_dir / "daily_performance.parquet", index=False)
    
    # 3. Summary stats
    summary = compute_summary(trades, daily_perf, capital)
    
    # 4. Markdown report
    generate_report(out_dir / "backtest_report.md", summary, daily_perf, trades)
    
    print(f"✓ Results saved to {out_dir}/")
    return summary


def compute_summary(trades: list, daily_perf: list, capital: float) -> dict:
    """Compute summary statistics."""
    if not trades:
        return {
            'total_trades': 0,
            'total_days': 0,
            'win_count': 0,
            'loss_count': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'sharpe_ratio': 0.0,
            'max_drawdown': 0.0,
            'final_capital': capital,
            'total_return_pct': 0.0,
        }
    
    pnls = [t.pnl_pct for t in trades]
    win_count = sum(1 for p in pnls if p > 0)
    loss_count = sum(1 for p in pnls if p < 0)
    total_pnl_pct = sum(pnls)
    
    # Profit factor
    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    pf = gains / losses if losses > 0 else np.inf
    
    # Sharpe (daily returns)
    if daily_perf:
        daily_returns = [d['total_pnl_pct'] / 100.0 for d in daily_perf]
        sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252) if np.std(daily_returns) > 0 else 0.0
    else:
        sharpe = 0.0
    
    # Max drawdown
    if daily_perf:
        cumul = [d['cumulative_capital'] for d in daily_perf]
        running_max = np.maximum.accumulate(cumul)
        drawdown = (cumul - running_max) / running_max
        max_dd = np.min(drawdown) if len(drawdown) > 0 else 0.0
    else:
        max_dd = 0.0
    
    final_capital = capital * (1.0 + total_pnl_pct / 100.0)
    
    return {
        'total_trades': len(trades),
        'total_days': len(daily_perf),
        'win_count': win_count,
        'loss_count': loss_count,
        'win_rate': (win_count / len(trades) * 100.0) if trades else 0.0,
        'profit_factor': float(pf),
        'sharpe_ratio': float(sharpe),
        'max_drawdown': float(max_dd * 100.0),
        'final_capital': final_capital,
        'total_return_pct': (final_capital - capital) / capital * 100.0,
    }


def generate_report(report_path: Path, summary: dict, daily_perf: list, trades: list):
    """Generate markdown backtest report."""
    lines = [
        "# Ross Cameron Bull Flag Backtest Report\n",
        f"**Test Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        "\n## Summary\n",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Trades | {summary['total_trades']} |",
        f"| Trading Days | {summary['total_days']} |",
        f"| Win Rate | {summary['win_rate']:.2f}% |",
        f"| Wins / Losses | {summary['win_count']} / {summary['loss_count']} |",
        f"| Profit Factor | {summary['profit_factor']:.2f}x |",
        f"| Sharpe Ratio | {summary['sharpe_ratio']:.2f} |",
        f"| Max Drawdown | {summary['max_drawdown']:.2f}% |",
        f"| Total Return | {summary['total_return_pct']:.2f}% |",
        f"| Final Capital | ${summary['final_capital']:.0f} |",
    ]
    
    if daily_perf:
        lines.extend([
            "\n## Daily Performance\n",
            f"| Date | Trades | Wins | W% | PnL% | Cumul% |",
            f"|------|--------|------|-----|------|--------|",
        ])
        for day in daily_perf[:30]:  # Show first 30 days
            lines.append(
                f"| {day['trade_date']} | {day['num_trades']} | {day['win_count']} | {day['win_rate_pct']:.0f}% | {day['total_pnl_pct']:.2f}% | {day['cumulative_pnl_pct']:.2f}% |"
            )
    
    report_path.write_text('\n'.join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--universe', type=str, required=True, help='Path to universe parquet')
    ap.add_argument('--run-name', type=str, required=True, help='Output directory name')
    ap.add_argument('--capital', type=float, default=30000, help='Starting capital')
    ap.add_argument('--compound', action='store_true', help='Compound returns')
    args = ap.parse_args()
    
    trades, daily_stats = backtest_universe(args.universe, args.capital, args.compound)
    summary = save_results(trades, daily_stats, args.run_name, args.capital)
    
    print(f"\n{'='*60}")
    print(f"Win Rate: {summary['win_rate']:.1f}% | PF: {summary['profit_factor']:.2f}x | Sharpe: {summary['sharpe_ratio']:.2f}")
    print(f"Return: {summary['total_return_pct']:.1f}%")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
