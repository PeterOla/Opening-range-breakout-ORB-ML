"""
Fast strategy backtester using pre-built universe cache.
(Backtest Engine)

Reads universe parquet, applies strategy rules, simulates trades.

Usage:
    python ORB_Live_Trader/backtest/fast_backtest.py --universe research_2021_sentiment_ROLLING24H/universe_sentiment_0.9.parquet \\
        --stop-atr-scale 0.05 --run-name stop_atr005
"""
import sys
import argparse
from pathlib import Path
from datetime import time
from typing import List
import pandas as pd
import numpy as np
from tqdm import tqdm
import json

# Setup Paths
BACKTEST_DIR = Path(__file__).resolve().parent
DATA_DIR = BACKTEST_DIR / "data"
ORB_UNIVERSE_DIR = DATA_DIR / "universe"
ORB_RUNS_DIR = DATA_DIR / "runs"
ORB_RUNS_DIR.mkdir(parents=True, exist_ok=True)

OR_START = time(9, 30)

# Defaults
INITIAL_CAPITAL = 1500.0 
LEVERAGE = 6.0 
SPREAD_PCT = 0.001
RISK_PER_TRADE = 0.10 

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
    limit_retest: bool = False,
    entry_cutoff: time = None
) -> dict:
    """Simulate trade execution with stop, EOD exit, and spread costs."""
    trade_bars = bars[bars['time'] > OR_START].copy()
    if trade_bars.empty:
        return {'entered': False, 'exit_reason': 'NO_BARS'}
    
    total_daily_volume = bars['volume'].sum()
    max_allowed_shares = total_daily_volume * max_pct_volume
    
    in_trade = False
    entry_price = None
    entry_time = None
    exit_price = None
    exit_time = None
    exit_reason = None
    
    def get_execution_price(base_price, is_buy):
        spread_amt = max(base_price * spread_pct, min_tick)
        if is_buy:
            return base_price + spread_amt
        else:
            return base_price - spread_amt

    triggered = False
    for _, bar in trade_bars.iterrows():
        # Check Entry Cutoff (only if not in trade)
        if not in_trade and entry_cutoff and bar['time'] >= entry_cutoff:
             # Cancel order if not filled by cutoff
             # If we were waiting for limit_retest trigger, it's also cancelled
             return {'entered': False, 'exit_reason': 'CUTOFF_CANCEL'}

        if not in_trade:
            if not limit_retest:
                if direction == 1 and bar['high'] >= entry_level:
                    in_trade = True
                    entry_time = bar['time']
                    entry_price = get_execution_price(entry_level, is_buy=True)
                elif direction == -1 and bar['low'] <= entry_level:
                    in_trade = True
                    entry_time = bar['time']
                    entry_price = get_execution_price(entry_level, is_buy=False)
            else:
                if not triggered:
                    if (direction == 1 and bar['high'] >= entry_level) or (direction == -1 and bar['low'] <= entry_level):
                        triggered = True
                    continue

                if direction == 1 and bar['low'] <= entry_level:
                    in_trade = True
                    entry_time = bar['time']
                    entry_price = float(entry_level)
                elif direction == -1 and bar['high'] >= entry_level:
                    in_trade = True
                    entry_time = bar['time']
                    entry_price = float(entry_level)
        else:
            if direction == 1 and bar['low'] <= stop_level:
                exit_time = bar['time']
                exit_reason = 'STOP_LOSS'
                exit_price = get_execution_price(stop_level, is_buy=False)
                break
            elif direction == -1 and bar['high'] >= stop_level:
                exit_time = bar['time']
                exit_reason = 'STOP_LOSS'
                exit_price = get_execution_price(stop_level, is_buy=True)
                break
    
    if in_trade and exit_price is None:
        last = trade_bars.iloc[-1]
        exit_time = last['time']
        exit_reason = 'EOD'
        raw_close = float(last['close'])
        if direction == 1:
            exit_price = get_execution_price(raw_close, is_buy=False)
        else:
            exit_price = get_execution_price(raw_close, is_buy=True)
    
    if not in_trade:
        return {'entered': False, 'exit_reason': 'NO_ENTRY'}
    
    direction_sign = 1 if direction == 1 else -1
    price_move = (exit_price - entry_price) * direction_sign
    
    target_position_value = position_size * leverage if apply_leverage else position_size
    target_shares = max(1.0, target_position_value / entry_price)
    actual_shares = min(target_shares, max_allowed_shares)
    
    if max_share_cap is not None:
        actual_shares = min(actual_shares, max_share_cap)

    is_capped = actual_shares < target_shares
    
    actual_position_value = actual_shares * entry_price
    actual_margin_used = actual_position_value / leverage if apply_leverage else actual_position_value
    
    gross_dollar_pnl = actual_shares * price_move
    
    comm_entry = max(actual_shares * comm_share, comm_min)
    if free_exits:
        comm_exit = 0.0
    else:
        comm_exit = max(actual_shares * comm_share, comm_min)
    total_comm = comm_entry + comm_exit
    
    net_dollar_pnl = gross_dollar_pnl - total_comm
    net_pnl_pct = (net_dollar_pnl / actual_margin_used) * 100.0 if actual_margin_used > 0 else 0.0
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
    dow_filter: str = None,
    risk_scale: float = 1.0,
    stop_atr_scale: float = 0.10,
    spread_pct: float = None,
    free_exits: bool = False,
    max_share_cap: int = None,
    leverage: float = LEVERAGE,
    comm_share: float = 0.005,
    comm_min: float = 0.99,
    limit_retest: bool = False,
    sizing_mode: str = "equal",
    risk_per_trade_pct: float = 0.01,
    entry_cutoff: str = None 
):
    run_spread_pct = spread_pct if spread_pct is not None else SPREAD_PCT

    print(f"Loading universe: {universe_path}")
    df_universe = pd.read_parquet(universe_path)

    # Parse Entry Cutoff
    cutoff_time = None
    if entry_cutoff:
        try:
            h, m = map(int, entry_cutoff.split(":"))
            cutoff_time = time(h, m)
            print(f"Entry Cutoff Active: Orders cancel if not filled by {cutoff_time}")
        except:
             print(f"Warning: Invalid entry cutoff format {entry_cutoff}")

    # Normalize Date Column
    date_cols = ['date', 'trade_date', 'timestamp', 'datetime', 'day']
    found_date = False
    for col in date_cols:
        if col in df_universe.columns:
            df_universe = df_universe.rename(columns={col: 'trade_date'})
            found_date = True
            break
            
    if not found_date:
        print(f"CRITICAL ERROR: No recognized date column in universe. Columns: {df_universe.columns}")
        return

    # Normalize Ticker Column
    if 'symbol' in df_universe.columns and 'ticker' not in df_universe.columns:
        df_universe = df_universe.rename(columns={'symbol': 'ticker'})

    print(f"  Total candidates: {len(df_universe):,}")

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
    
    df_filtered = df_universe[
        (df_universe['atr_14'] >= min_atr) &
        (df_universe['avg_volume_14'] >= min_volume)
    ].copy()
    print(f"  After runtime filters (ATR >= {min_atr}, Vol >= {min_volume:,}): {len(df_filtered):,}")
    
    if side_filter == 'long':
        df_filtered = df_filtered[df_filtered['direction'] == 1].copy()
    elif side_filter == 'short':
        df_filtered = df_filtered[df_filtered['direction'] == -1].copy()
    
    df_filtered = df_filtered.sort_values(['trade_date', 'rvol'], ascending=[True, False])
    df_filtered = df_filtered.groupby('trade_date').head(top_n).reset_index(drop=True)
    print(f"  After Top-{top_n} per day: {len(df_filtered):,}")
    
    if df_filtered.empty:
        print("No candidates after filters.")
        return
    
    results = []
    equity_curve = []
    yearly_results = []
    current_equity = initial_capital
    current_year = None
    year_start_equity = initial_capital
    
    mode_str = "COMPOUND" if compound else "FIXED"
    print(f"Simulating trades (Stop: {stop_atr_scale*100:.1f}% ATR, mode={mode_str}, vol_cap={max_pct_volume*100:.1f}%, start_equity=${initial_capital:,.2f})...")
    
    date_groups = df_filtered.groupby('trade_date')
    
    for trade_date, day_df in tqdm(date_groups, desc="Processing days"):
        current_date_ts = pd.to_datetime(trade_date)
        
        trade_year = current_date_ts.year
        if compound and current_year is not None and trade_year != current_year:
            year_pnl = current_equity - year_start_equity
            yearly_results.append({
                'year': current_year,
                'start_equity': year_start_equity,
                'end_equity': current_equity,
                'year_pnl': year_pnl,
                'year_return_pct': (year_pnl / year_start_equity) * 100 if year_start_equity > 0 else 0,
            })
            year_start_equity = current_equity
        
        current_year = trade_year
        
        day_equity_start = current_equity
        day_pnl = 0.0
        
        num_trades_today = len(day_df)
        effective_bp = current_equity * leverage 
        allocation_pool = effective_bp * risk_scale
        allocation_per_trade = allocation_pool / num_trades_today if num_trades_today > 0 else 0
        
        for _, row in day_df.iterrows():
            bars = deserialize_bars(row['bars_json'])
            
            entry_level = row['or_high'] if row['direction'] == 1 else row['or_low']
            atr_stop_dist = stop_atr_scale * row['atr_14']
            stop_level = (entry_level - atr_stop_dist) if row['direction'] == 1 else (entry_level + atr_stop_dist)
            
            # Position logic
            stop_dist_abs = abs(entry_level - stop_level)
            
            if compound:
                if sizing_mode == 'risk' and stop_dist_abs > 0:
                    risk_amt = current_equity * risk_per_trade_pct
                    shares = risk_amt / stop_dist_abs
                    position_size = shares * entry_level
                    max_pos = current_equity * leverage
                    if position_size > max_pos:
                        position_size = max_pos
                    apply_lev = False 
                else:
                    position_size = allocation_per_trade
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
                limit_retest=limit_retest,
                entry_cutoff=cutoff_time
            )
            
            trade_pnl = sim.get('dollar_pnl', 0.0) or 0.0
            if compound and sim.get('entered'):
                day_pnl += trade_pnl
            
            results.append({
                'trade_date': row['trade_date'],
                'ticker': row['ticker'],
                'side': 'LONG' if row['direction'] == 1 else 'SHORT',
                'rvol': round(row['rvol'], 2),
                'pnl_pct': sim.get('pnl_pct'),
                'shares': sim.get('shares'),
                'entry_price': sim.get('entry_price'),
                'exit_price': sim.get('exit_price'),
                'dollar_pnl': sim.get('dollar_pnl'),
                'base_dollar_pnl': sim.get('base_dollar_pnl'),
                'commission': sim.get('commission'),
                'exit_reason': sim.get('exit_reason', 'NO_ENTRY')
            })
        
        if compound:
            current_equity = day_equity_start + day_pnl
            if current_equity <= 0:
                print(f"[ALERT] Account blown on {trade_date}!")
                current_equity = 0.01
            
        equity_curve.append({
            'date': trade_date,
            'equity': round(current_equity, 2),
            'day_pnl': round(day_pnl, 2),
        })
    
    if compound and current_year is not None:
        year_pnl = current_equity - year_start_equity
        yearly_results.append({
            'year': current_year,
            'start_equity': year_start_equity,
            'end_equity': current_equity,
            'year_pnl': year_pnl,
            'year_return_pct': (year_pnl / year_start_equity) * 100 if year_start_equity > 0 else 0,
        })
    
    df_trades = pd.DataFrame(results)
    run_dir = resolve_run_dir(run_name, compound=compound)
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Save Run Config with cutoff
    run_config = {
        "run_name": run_name,
        "entry_cutoff": str(cutoff_time) if cutoff_time else None
    }
    # ... (simplified)

    trades_path = run_dir / "simulated_trades.parquet"
    df_trades.to_parquet(trades_path, index=False)
    
    print(f"\nRun: {run_name}")
    print(f"Total Trades: {len(df_trades):,}")
    
    if compound:
        print(f"Final Equity: ${current_equity:,.2f}")
        for yr in yearly_results:
             print(f"  {yr['year']}: {yr['year_return_pct']:+.1f}%")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--universe', type=str, required=True, help='Universe parquet filename relative to ORB_UNIVERSE_DIR')
    ap.add_argument('--run-name', type=str, required=True)
    ap.add_argument('--min-atr', type=float, default=0.50)
    ap.add_argument('--min-volume', type=int, default=100_000)
    ap.add_argument('--start-date', type=str, default=None)
    ap.add_argument('--end-date', type=str, default=None)
    ap.add_argument('--stop-atr-scale', type=float, default=0.10)
    ap.add_argument('--leverage', type=float, default=LEVERAGE)
    ap.add_argument('--initial-capital', type=float, default=INITIAL_CAPITAL)
    ap.add_argument('--entry-cutoff', type=str, default=None, help='Entry cutoff time (HH:MM). Cancel orders if no entry by this time.')
    
    args = ap.parse_args()
    
    # Try finding universe path
    universe_path = ORB_UNIVERSE_DIR / args.universe
    if not universe_path.exists():
        # Fallback to absolute if user provided valid path
        if Path(args.universe).exists():
             universe_path = Path(args.universe)
        else:
             print(f"Universe not found: {universe_path}")
             return
            
    run_strategy(
        universe_path,
        min_atr=args.min_atr,
        min_volume=args.min_volume,
        top_n=5,
        side_filter='long',
        run_name=args.run_name,
        compound=True,
        stop_atr_scale=args.stop_atr_scale,
        start_date=args.start_date,
        end_date=args.end_date,
        leverage=args.leverage,
        initial_capital=args.initial_capital,
        entry_cutoff=args.entry_cutoff
    )

if __name__ == "__main__":
    main()
