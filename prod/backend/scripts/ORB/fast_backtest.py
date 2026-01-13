"""
Fast strategy backtester using pre-built universe cache.

Reads universe parquet, applies strategy rules (stop mode/thresholds), simulates trades.
Runs in seconds vs minutes.

Usage:
    python scripts/fast_backtest.py --universe universe_20210101_20251231.parquet \\
        --stop-mode or --min-atr 0.50 --run-name stop_or_atr050
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import time
from typing import List
import pandas as pd
import numpy as np
from tqdm import tqdm
import json

from scripts.ORB.analyse_run import write_run_summary_md
from core.config import settings

# Position sizing defaults (Permanent Reality Lock)
INITIAL_CAPITAL = 1500.0 
LEVERAGE = 6.0 # Implied from $1500 Equity -> $9000 BP
SPREAD_PCT = 0.001
RISK_PER_TRADE = 0.10 # 10% of equity per trade (aggressive small account growth)

# Compounding settings
INITIAL_CAPITAL = 1500.0 # User specified
SPREAD_PCT = 0.001  # 0.1% per side (0.2% round trip) - Conservative spread betting cost

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
ORB_UNIVERSE_DIR = DATA_DIR / "backtest" / "orb" / "universe"
ORB_RUNS_DIR = DATA_DIR / "backtest" / "orb" / "runs"
ORB_RUNS_DIR.mkdir(parents=True, exist_ok=True)

OR_START = time(9, 30)


def resolve_run_dir(run_name: str, *, compound: bool) -> Path:
    lowered = (run_name or "").lower()
    if lowered.startswith(("test_", "exp_", "experiment_", "rc_test_")):
        group = "experiments"
    elif compound:
        group = "compound"
    else:
        group = "atr_stop"
    return ORB_RUNS_DIR / group / run_name


def deserialize_bars(bars_data) -> pd.DataFrame:
    """Deserialize bars from list or JSON string."""
    if isinstance(bars_data, str):
        # Legacy JSON format
        import json
        data = json.loads(bars_data)
        df = pd.DataFrame(data)
        df['datetime'] = pd.to_datetime(df['datetime'])
    else:
        # New compact list format
        df = pd.DataFrame(bars_data, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['datetime'])
    
    df['time'] = df['datetime'].dt.time
    return df


def simulate_trade(
    bars: pd.DataFrame, 
    direction: int, 
    entry_level: float, 
    stop_level: float,
    position_size: float = INITIAL_CAPITAL,
    leverage: float = LEVERAGE,
    apply_leverage: bool = True,
    spread_pct: float = SPREAD_PCT,
    max_pct_volume: float = 1.0,
    min_tick: float = 0.01,
    comm_share: float = 0.005,
    comm_min: float = 0.99,
    free_exits: bool = False,
    max_share_cap: int = None,
    limit_retest: bool = False
) -> dict:
    """Simulate trade execution with stop, EOD exit, and spread costs.
    
    Args:
        apply_leverage: If True, multiply position_size by leverage. 
        spread_pct: Percentage cost added to entry and subtracted from exit (half-spread).
        max_share_cap: Absolute maximum number of shares per trade (e.g. 199).
        max_pct_volume: Max percentage of daily volume allowed for position size (0.01 = 1%).
    """
    trade_bars = bars[bars['time'] > OR_START].copy()
    if trade_bars.empty:
        return {'entered': False, 'exit_reason': 'NO_BARS'}
    
    # Calculate volume cap
    total_daily_volume = bars['volume'].sum()
    max_allowed_shares = total_daily_volume * max_pct_volume
    
    in_trade = False
    entry_price = None
    entry_time = None
    exit_price = None
    exit_time = None
    exit_reason = None
    
    # Adjust entry/stop levels for spread and tick logic
    # Spread is effectively: Max(Percentage, Minimum Tick)
    
    # Helper to calculate execution price with spread impact
    def get_execution_price(base_price, is_buy):
        # Base spread amount
        spread_amt = max(base_price * spread_pct, min_tick)
        if is_buy:
            return base_price + spread_amt
        else:
            return base_price - spread_amt

    triggered = False
    for _, bar in trade_bars.iterrows():
        if not in_trade:
            if not limit_retest:
                # Standard breakout entry (assume marketable execution).
                if direction == 1 and bar['high'] >= entry_level:
                    in_trade = True
                    entry_time = bar['time']
                    # Long: Buy at Ask
                    entry_price = get_execution_price(entry_level, is_buy=True)
                elif direction == -1 and bar['low'] <= entry_level:
                    in_trade = True
                    entry_time = bar['time']
                    # Short: Sell at Bid
                    entry_price = get_execution_price(entry_level, is_buy=False)
            else:
                # Experiment: limit "retest" entry (maker-ish fill).
                # Conservative assumption: signal triggers first; entry can only fill on a later bar.
                if not triggered:
                    if (direction == 1 and bar['high'] >= entry_level) or (direction == -1 and bar['low'] <= entry_level):
                        triggered = True
                    continue

                # After trigger, wait for price to come back to the entry level.
                if direction == 1 and bar['low'] <= entry_level:
                    in_trade = True
                    entry_time = bar['time']
                    # Limit fill at the entry level (no spread penalty on entry).
                    entry_price = float(entry_level)
                elif direction == -1 and bar['high'] >= entry_level:
                    in_trade = True
                    entry_time = bar['time']
                    entry_price = float(entry_level)
        else:
            if direction == 1 and bar['low'] <= stop_level:
                exit_time = bar['time']
                exit_reason = 'STOP_LOSS'
                # Long Stop: Sell at Bid
                exit_price = get_execution_price(stop_level, is_buy=False)
                break
            elif direction == -1 and bar['high'] >= stop_level:
                exit_time = bar['time']
                exit_reason = 'STOP_LOSS'
                # Short Stop: Buy at Ask
                exit_price = get_execution_price(stop_level, is_buy=True)
                break
    
    if in_trade and exit_price is None:
        last = trade_bars.iloc[-1]
        exit_time = last['time']
        exit_reason = 'EOD'
        raw_close = float(last['close'])
        # EOD Exit
        if direction == 1:
            exit_price = get_execution_price(raw_close, is_buy=False)
        else:
            exit_price = get_execution_price(raw_close, is_buy=True)
    
    if not in_trade:
        return {'entered': False, 'exit_reason': 'NO_ENTRY'}
    
    direction_sign = 1 if direction == 1 else -1
    price_move = (exit_price - entry_price) * direction_sign
    
    # Apply leverage
    # position_size is the MARGIN allocated
    target_position_value = position_size * leverage if apply_leverage else position_size
    
    # Shares = Notional / Entry Price
    # Ensure at least 1 share
    target_shares = max(1.0, target_position_value / entry_price)
    
    # Apply Volume Cap (Liquidity)
    actual_shares = min(target_shares, max_allowed_shares)
    
    # Apply Hard Share Cap (Risk/Fees)
    if max_share_cap is not None:
        actual_shares = min(actual_shares, max_share_cap)

    is_capped = actual_shares < target_shares
    
    # Recalculate actual position value and margin used
    actual_position_value = actual_shares * entry_price
    actual_margin_used = actual_position_value / leverage if apply_leverage else actual_position_value
    
    # Gross Dollar PnL
    gross_dollar_pnl = actual_shares * price_move
    
    # Calculate Commissions
    # Entry Commission (Buy/Sell to Open)
    comm_entry = max(actual_shares * comm_share, comm_min)
    # Exit Commission (Sell/Buy to Close) - Free if Limit Exits used
    if free_exits:
        comm_exit = 0.0
    else:
        comm_exit = max(actual_shares * comm_share, comm_min)
    total_comm = comm_entry + comm_exit
    
    # Net Dollar PnL
    net_dollar_pnl = gross_dollar_pnl - total_comm
    
    # Net PnL % (ROIC on Margin Used)
    # Note: Traditional PnL% is strictly price move, but we want Net ROI here for proper modeling
    net_pnl_pct = (net_dollar_pnl / actual_margin_used) * 100.0 if actual_margin_used > 0 else 0.0
    
    # Keep Base PnL as Unleveraged Return for stats consistency, but NET of fees now
    base_dollar_pnl = net_dollar_pnl / leverage if apply_leverage else net_dollar_pnl
    
    first_bar, last_bar = bars.iloc[0], bars.iloc[-1]
    day_change_pct = round((float(last_bar['close']) - float(first_bar['open'])) / float(first_bar['open']) * 100.0, 2)
    
    return {
        'entered': True,
        'entry_price': round(entry_price, 4),
        'entry_time': entry_time.strftime('%H:%M'),
        'exit_price': round(exit_price, 4),
        'exit_time': exit_time.strftime('%H:%M'),
        'exit_reason': exit_reason,
        'pnl_pct': round(net_pnl_pct, 2),
        'dollar_pnl': round(net_dollar_pnl, 2),
        'base_dollar_pnl': round(base_dollar_pnl, 2),
        'commission': round(total_comm, 2),
        'day_change_pct': day_change_pct,
        'position_size': round(actual_margin_used, 2),
        'is_capped': is_capped,
        'cap_ratio': round(actual_shares / target_shares, 2) if target_shares > 0 else 1.0,
        'shares': round(actual_shares, 0)
    }


def run_strategy(
    universe_path: Path,
    min_atr: float,
    min_volume: int,
    top_n: int,
    side_filter: str,
    run_name: str,
    compound: bool = False,
    risk_per_trade: float = 0.01,
    verbose: bool = False,
    max_pct_volume: float = 1.0,
    initial_capital: float = INITIAL_CAPITAL,
    regime_file: str = None,
    start_date: str = None,
    end_date: str = None,
    dow_filter: str = None,  # 'skip_midweek', 'skip_tue'
    risk_scale: float = 1.0, # 1.0 = 100% allocation, 0.5 = 50% allocation (cash buffer)
    stop_atr_scale: float = 0.10, # Stop loss as fraction of ATR (0.10 = 10% of ATR)
    spread_pct: float = None, # Override global spread pct
    free_exits: bool = False, # If True, assume Limit Order exits with 0 commission
    max_share_cap: int = None,
    leverage: float = LEVERAGE,
    comm_share: float = 0.005,
    comm_min: float = 0.99,
    limit_retest: bool = False
):
    """Run strategy on pre-built universe."""
    
    # Use global DEFAULT if no override provided
    run_spread_pct = spread_pct if spread_pct is not None else SPREAD_PCT

    # Load Regime Data if present
    regime_data = None
    if regime_file:
        print(f"Loading regime filter: {regime_file}")
        try:
            regime_df = pd.read_parquet(regime_file)
            regime_df['date'] = pd.to_datetime(regime_df['date']).dt.normalize()
            regime_data = regime_df.set_index('date')['is_bullish'].to_dict()
        except Exception as e:
            print(f"Warning: Failed to load regime file: {e}")

    print(f"Loading universe: {universe_path}")
    df_universe = pd.read_parquet(universe_path)

    # Standardize column names (handle 'date' vs 'trade_date', 'symbol' vs 'ticker')
    if 'date' in df_universe.columns and 'trade_date' not in df_universe.columns:
        df_universe = df_universe.rename(columns={'date': 'trade_date'})
    if 'symbol' in df_universe.columns and 'ticker' not in df_universe.columns:
        df_universe = df_universe.rename(columns={'symbol': 'ticker'})

    print(f"  Total candidates: {len(df_universe):,}")

    # Optional date range filter (inclusive). Expects YYYY-MM-DD.
    if start_date or end_date:
        df_universe = df_universe.copy()
        df_universe['trade_date'] = pd.to_datetime(df_universe['trade_date']).dt.date
        if start_date:
            start_dt = pd.to_datetime(start_date).date()
            df_universe = df_universe[df_universe['trade_date'] >= start_dt]
        if end_date:
            end_dt = pd.to_datetime(end_date).date()
            df_universe = df_universe[df_universe['trade_date'] <= end_dt]
        print(f"  After date filter ({start_date or '...'} -> {end_date or '...'}): {len(df_universe):,}")
    
    # Apply runtime filters (ATR/volume thresholds can be tighter than universe build)
    df_filtered = df_universe[
        (df_universe['atr_14'] >= min_atr) &
        (df_universe['avg_volume_14'] >= min_volume)
    ].copy()
    print(f"  After runtime filters (ATR >= {min_atr}, Vol >= {min_volume:,}): {len(df_filtered):,}")
    
    # Apply side filter
    if side_filter == 'long':
        df_filtered = df_filtered[df_filtered['direction'] == 1].copy()
        print(f"  After LONG-only filter: {len(df_filtered):,}")
    elif side_filter == 'short':
        df_filtered = df_filtered[df_filtered['direction'] == -1].copy()
        print(f"  After SHORT-only filter: {len(df_filtered):,}")
    
    # Re-rank by RVOL per day and take Top-N
    df_filtered = df_filtered.sort_values(['trade_date', 'rvol'], ascending=[True, False])
    df_filtered = df_filtered.groupby('trade_date').head(top_n).reset_index(drop=True)
    print(f"  After Top-{top_n} per day: {len(df_filtered):,}")
    
    if df_filtered.empty:
        print("No candidates after filters.")
        return
    
    # Simulate trades
    results = []
    equity_curve = []
    yearly_results = []  # Track yearly performance
    current_equity = initial_capital
    current_year = None
    year_start_equity = initial_capital
    
    mode_str = "COMPOUND" if compound else "FIXED"
    print(f"Simulating trades (Stop: {stop_atr_scale*100:.1f}% ATR, mode={mode_str}, vol_cap={max_pct_volume*100:.1f}%, start_equity=${initial_capital:,.2f})...")
    
    # Group by date for compounding
    date_groups = df_filtered.groupby('trade_date')
    
    for trade_date, day_df in tqdm(date_groups, desc="Processing days"):
        current_date_ts = pd.to_datetime(trade_date)
        
        # ----------------------------------------------------
        # EXPERIMENT: Regime Filter
        # ----------------------------------------------------
        if regime_data:
            # Check if date exists in regime data
            # normalize to be safe
            ts_norm = current_date_ts.normalize()
            if ts_norm in regime_data:
                is_bullish = regime_data[ts_norm]
                # If regime is bearish (False), SKIP trading this day
                if not is_bullish:
                    # Record empty day stats? 
                    # For now just skip logic, equity remains, day_pnl=0
                    # We continue the loop to next year logic if needed? 
                    # Ah, year logic is above. Let's move year logic inside loop properly.
                    pass
            else:
                # If no data for this date, assume trading allowed? or block?
                # Assume allowed to avoid over-blocking
                pass
                
        # ----------------------------------------------------
        # EXPERIMENT: Day of Week Filter
        # ----------------------------------------------------
        # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
        dow = current_date_ts.dayofweek
        midweek_days = [1, 2, 3] # Tue, Wed, Thu
        
        skip_day = False
        if dow_filter == 'skip_midweek' and dow in midweek_days:
            skip_day = True
        elif dow_filter == 'skip_tue' and dow == 1:
            skip_day = True
            
        if regime_data and ts_norm in regime_data and not regime_data[ts_norm]:
             skip_day = True

        # Check for year change - just for reporting, NO RESET
        trade_year = current_date_ts.year
        if compound and current_year is not None and trade_year != current_year:
            # Save previous year's result
            year_pnl = current_equity - year_start_equity
            yearly_results.append({
                'year': current_year,
                'start_equity': year_start_equity,
                'end_equity': current_equity,
                'year_pnl': year_pnl,
                'year_return_pct': (year_pnl / year_start_equity) * 100 if year_start_equity > 0 else 0,
            })
            # Update start equity for next year (continuous compounding)
            year_start_equity = current_equity
        
        current_year = trade_year
        
        if skip_day:
            # Record 0 pnl day
            equity_curve.append({
                 'date': trade_date,
                 'trades': 0,
                 'entered': 0,
                 'winners': 0,
                 'losers': 0,
                 'total_base_pnl': 0.0,
                 'total_leveraged_pnl': 0.0,
                 'daily_pnl': 0.0,
                 'equity': current_equity 
            })
            continue

        day_equity_start = current_equity
        day_pnl = 0.0
        
        # Determine allocation per trade (Equal Split)
        # If we have N candidates for the day, we split equity into N parts.
        # Note: day_df contains the Top-N candidates.
        num_trades_today = len(day_df)
        
        # ----------------------------------------------------
        # EXPERIMENT: Risk Scaling (Position Sizing)
        # ----------------------------------------------------
        # If risk_scale is 0.5, we only allocate 50% of available equity to trades.
        # The rest sits as cash.
        
        # NOTE: Using LEVERAGE variable to simulate Buying Power
        # Capital for Sizing = Equity * Leverage * Risk_Scale
        # We assume full use of Buying Power for the allocated portion 
        # (This matches the $9,500 BP on $1,500 Equity scenario)
        
        effective_bp = current_equity * leverage 
        allocation_pool = effective_bp * risk_scale
        allocation_per_trade = allocation_pool / num_trades_today if num_trades_today > 0 else 0
        
        for _, row in day_df.iterrows():
            bars = deserialize_bars(row['bars_json'])
            
            # Determine entry and stop
            # Entry: Break of OR High (Long) or OR Low (Short)
            entry_level = row['or_high'] if row['direction'] == 1 else row['or_low']
            
            # Stop: Scaled ATR from entry
            atr_stop_dist = stop_atr_scale * row['atr_14']
            stop_level = (entry_level - atr_stop_dist) if row['direction'] == 1 else (entry_level + atr_stop_dist)
            
            stop_distance_pct = abs(entry_level - stop_level) / entry_level * 100.0
            
            # Calculate position size
            if compound:
                # Equal Split Sizing: Margin = Equity / N
                position_size = allocation_per_trade
                # Leverage is applied via 'allocation_pool' calculation above, so don't double count inside simulate_trade
                # Actually, simulate_trade takes 'position_size' as the BASE amount and applies LEVERAGE if apply_leverage=True
                # If we pass the LEVERAGED amount as position_size, we should set apply_leverage=False
                apply_lev = False 
            else:
                position_size = initial_capital
                apply_lev = True
            
            sim = simulate_trade(
                bars, row['direction'], entry_level, stop_level,
                position_size=position_size, 
                leverage=leverage,
                apply_leverage=apply_lev,
                spread_pct=run_spread_pct,
                max_pct_volume=max_pct_volume,
                min_tick=0.01,
                comm_share=comm_share,
                comm_min=comm_min,
                free_exits=free_exits,
                max_share_cap=max_share_cap,
                limit_retest=limit_retest
            )
            
            trade_pnl = sim.get('dollar_pnl', 0.0) or 0.0
            if compound and sim.get('entered'):
                day_pnl += trade_pnl
            
            results.append({
                'trade_date': row['trade_date'],
                'ticker': row['ticker'],
                'side': 'LONG' if row['direction'] == 1 else 'SHORT',
                'rvol_rank': row['rvol_rank'],
                'rvol': round(row['rvol'], 2),
                'or_open': row['or_open'],
                'or_high': row['or_high'],
                'or_low': row['or_low'],
                'or_close': row['or_close'],
                'or_volume': row['or_volume'],
                'entry_price': entry_level,
                'stop_price': stop_level,
                'exit_price': sim.get('exit_price'),
                'exit_reason': sim.get('exit_reason', 'NO_ENTRY'),
                'entry_time': sim.get('entry_time'),
                'exit_time': sim.get('exit_time'),
                'pnl_pct': sim.get('pnl_pct'),
                'day_change_pct': sim.get('day_change_pct'),
                'stop_distance_pct': round(stop_distance_pct, 3),
                'leverage': LEVERAGE,
                'dollar_pnl': sim.get('dollar_pnl'),
                'base_dollar_pnl': sim.get('base_dollar_pnl'),
                'position_size': sim.get('position_size'),
                'atr_14': row['atr_14'],
                'avg_volume_14': row['avg_volume_14'],
                'prev_close': row['prev_close'],
                'is_capped': sim.get('is_capped', False),
                'cap_ratio': sim.get('cap_ratio', 1.0),
                'shares': sim.get('shares', 0),
                'comm_total': sim.get('commission', 0.0),
                'pnl_net': sim.get('dollar_pnl', 0.0),
                # Gross = Net + Comm
                'pnl_gross': sim.get('dollar_pnl', 0.0) + sim.get('commission', 0.0)
            })
        
        # Update equity at end of day (for compounding)
        if compound:
            current_equity = day_equity_start + day_pnl
            # Prevent negative equity
            if current_equity <= 0:
                print(f"\n[ALERT] Account blown on {trade_date}! Equity: ${current_equity:.2f}")
                current_equity = 0.01  # minimum to continue
            
        equity_curve.append({
            'date': trade_date,
            'equity': round(current_equity, 2),
            'day_pnl': round(day_pnl, 2),
        })
    
    # Capture final year's result (for compounding)
    if compound and current_year is not None:
        year_pnl = current_equity - year_start_equity
        yearly_results.append({
            'year': current_year,
            'start_equity': year_start_equity,
            'end_equity': current_equity,
            'year_pnl': year_pnl,
            'year_return_pct': (year_pnl / year_start_equity) * 100 if year_start_equity > 0 else 0,
        })
    
    # Save trades
    df_trades = pd.DataFrame(results)
    run_dir = resolve_run_dir(run_name, compound=compound)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Save run config for human-readable reporting
    run_config = {
        "run_name": run_name,
        "universe_file": universe_path.name,
        "min_atr": float(min_atr),
        "min_volume": int(min_volume),
        "top_n": int(top_n),
        "side": side_filter,
        "compound": bool(compound),
        "max_pct_volume": float(max_pct_volume),
        "leverage": float(leverage),
        "stop_atr_scale": float(stop_atr_scale),
        "spread_pct": float(run_spread_pct),
        "comm_share": float(comm_share),
        "comm_min": float(comm_min),
        "free_exits": bool(free_exits),
        "limit_retest": bool(limit_retest),
    }
    (run_dir / "run_config.json").write_text(json.dumps(run_config, indent=2), encoding="utf-8")

    trades_path = run_dir / "simulated_trades.parquet"
    df_trades.to_parquet(trades_path, index=False)
    
    # Save equity curve (for compounding)
    if compound:
        df_equity = pd.DataFrame(equity_curve)
        equity_path = run_dir / "equity_curve.parquet"
        df_equity.to_parquet(equity_path, index=False)
        
        # Save yearly results
        df_yearly = pd.DataFrame(yearly_results)
        yearly_path = run_dir / "yearly_results.parquet"
        df_yearly.to_parquet(yearly_path, index=False)
    
    # Compute daily performance
    entered = df_trades[df_trades['exit_reason'] != 'NO_ENTRY']
    daily_groups = entered.groupby('trade_date')
    daily_perf = []
    
    for date, group in daily_groups:
        winners = group[group['pnl_pct'] > 0]
        losers = group[group['pnl_pct'] < 0]
        daily_perf.append({
            'date': date,
            'trades': len(group),
            'entered': len(group),
            'winners': len(winners),
            'losers': len(losers),
            'total_base_pnl': float(group['base_dollar_pnl'].fillna(0).sum()),
            'total_leveraged_pnl': float(group['dollar_pnl'].fillna(0).sum()),
        })
    
    df_daily = pd.DataFrame(daily_perf)
    daily_path = run_dir / "daily_performance.parquet"
    df_daily.to_parquet(daily_path, index=False)

    # Write human-readable summary for the run directory
    write_run_summary_md(run_dir)
    
    # Summary stats
    total_entered = len(entered)
    winners = entered[entered['pnl_pct'] > 0]
    losers = entered[entered['pnl_pct'] < 0]
    win_rate = (len(winners) / total_entered * 100) if total_entered else 0
    total_pnl_base = entered['base_dollar_pnl'].sum()
    total_pnl_leveraged = entered['dollar_pnl'].sum()
    
    # Profit factor
    gross_profit = winners['base_dollar_pnl'].sum() if not winners.empty else 0
    gross_loss = abs(losers['base_dollar_pnl'].sum()) if not losers.empty else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)
    
    print(f"\n{'='*60}")
    print(f"Run: {run_name}")
    print(f"{'='*60}")
    print(f"Mode: {'COMPOUNDING (yearly reset)' if compound else 'FIXED CAPITAL'}")
    print(f"Total Trades: {len(df_trades):,}")
    print(f"Entered: {total_entered:,}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Profit Factor: {profit_factor:.2f}")
    
    if compound:
        # Sum up yearly P&L (each year starts with $1,000)
        total_yearly_pnl = sum(yr['year_pnl'] for yr in yearly_results)
        print(f"\nYearly Results (Continuous Compounding):")
        for yr in yearly_results:
            print(f"  {yr['year']}: Started ${yr['start_equity']:,.2f} -> Ended ${yr['end_equity']:,.2f} ({yr['year_return_pct']:+.1f}%)")
        print(f"\nFinal Equity: ${current_equity:,.2f}")
        print(f"  {yearly_path}")
    else:
        print(f"Total P&L (1x): ${total_pnl_base:,.2f}")
        print(f"Total P&L (5x): ${total_pnl_leveraged:,.2f}")
    
    print(f"\nOutputs:")
    print(f"  {trades_path}")
    print(f"  {daily_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--universe', type=str, required=True, help='Universe parquet filename')
    ap.add_argument('--min-atr', type=float, default=0.50, help='Minimum ATR filter (default: 0.50)')
    ap.add_argument('--min-volume', type=int, default=100_000, help='Minimum Volume filter (default: 100k)')
    ap.add_argument('--top-n', type=int, default=20)
    ap.add_argument('--side', choices=['long', 'short', 'both'], default='both', help='Trade direction filter')
    ap.add_argument('--no-compound', action='store_false', dest='compound', help='Disable compounding (Compounding is ON by default)')
    ap.set_defaults(compound=True)
    ap.add_argument('--daily-risk', type=float, default=0.10, help='Daily risk target (0.10 = 10%%), auto-split across top-n trades')
    ap.add_argument('--run-name', type=str, required=True)
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--max-pct-volume', type=float, default=0.01, help='Max percentage of daily volume allowed for position size (0.01 = 1%%)')
    ap.add_argument('--initial-capital', type=float, default=INITIAL_CAPITAL, help='Initial capital for backtest')
    
    # New Arguments for Advanced Control
    ap.add_argument('--leverage', type=float, default=LEVERAGE, help='Leverage factor (default: 6.0)')
    ap.add_argument('--stop-atr-scale', type=float, default=0.10, help='Stop loss distance as fraction of ATR (default: 0.10)')
    ap.add_argument('--comm-share', type=float, default=0.005, help='Commission per share')
    ap.add_argument('--comm-min', type=float, default=0.99, help='Minimum commission per order')
    ap.add_argument('--free-exits', action='store_true', help='Assume 0 commission on exits (Limit orders)')
    ap.add_argument('--spread-pct', type=float, default=0.001, help='Bid-Ask Spread %% (default 0.001 = 0.1%%)')
    ap.add_argument('--limit-retest', action='store_true', help='Entry fills only on retest of breakout level (conservative limit fill)')
    ap.add_argument('--start-date', type=str, default=None, help='Start date (YYYY-MM-DD), inclusive')
    ap.add_argument('--end-date', type=str, default=None, help='End date (YYYY-MM-DD), inclusive')
    
    args = ap.parse_args()
    
    # Auto-calculate risk per trade from daily risk target
    risk_per_trade = args.daily_risk / args.top_n
    print(f"Risk model: Equal Dollar Allocation (Equity / {args.top_n} candidates)")
    print(f"Filters: ATR >= {args.min_atr}, Volume >= {args.min_volume:,}")
    print(f"Params: Stop={args.stop_atr_scale}xATR, Leverage={args.leverage}x, Comm=${args.comm_min} min / ${args.comm_share}/sh")
    
    # Prefer the new ORB universe location, fallback to legacy data/backtest root
    universe_path = ORB_UNIVERSE_DIR / args.universe
    if not universe_path.exists():
        legacy_path = DATA_DIR / "backtest" / args.universe
        if legacy_path.exists():
            universe_path = legacy_path
        else:
            print(f"Universe not found: {universe_path}")
            return
    
    run_strategy(
        universe_path,
        args.min_atr,
        args.min_volume,
        args.top_n,
        args.side,
        args.run_name,
        args.compound,
        risk_per_trade,
        args.verbose,
        args.max_pct_volume,
        args.initial_capital,
        leverage=args.leverage,
        stop_atr_scale=args.stop_atr_scale,
        comm_share=args.comm_share,
        comm_min=args.comm_min,
        free_exits=args.free_exits,
        spread_pct=args.spread_pct,
        limit_retest=args.limit_retest,
        start_date=args.start_date,
        end_date=args.end_date
    )


if __name__ == "__main__":
    main()
