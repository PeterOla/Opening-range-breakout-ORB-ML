"""
Generate trade charts for Ross Cameron backtest.

Reads trades and universe data, plots 5-min candles with entry/stop/target levels.
Saves charts to data/backtest/ross_cameron/trade_charts/

Usage:
    python scripts/generate_trade_charts.py --trades data/backtest/ross_cameron/trades_rc_schwag_full_2021_2025.parquet --universe data/backtest/ross_cameron/universe_rc_20210101_20251231.parquet
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
import pandas as pd
import mplfinance as mpf
import json
import numpy as np

def parse_bars_json(json_str):
    """Parse JSON string of bars into DataFrame."""
    try:
        data = json.loads(json_str)
        df = pd.DataFrame(data)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        return pd.DataFrame()

def plot_trade(trade, bars_df, output_dir):
    """Plot a single trade."""
    symbol = trade['ticker']
    date_str = trade['entry_time'].strftime('%Y-%m-%d')
    
    # Filter bars for the trade date
    day_bars = bars_df[bars_df.index.date == trade['entry_time'].date()].copy()
    
    if day_bars.empty:
        print(f"No bars found for {symbol} on {date_str}")
        return

    # Create addplots for entry, stop, target
    apds = []
    
    # Entry line (Green)
    entry_line = [trade['entry_price']] * len(day_bars)
    apds.append(mpf.make_addplot(entry_line, color='green', linestyle='--', width=1))
    
    # Exit line (Blue)
    exit_line = [trade['exit_price']] * len(day_bars)
    apds.append(mpf.make_addplot(exit_line, color='blue', linestyle='--', width=1))

    # Impulse High (Orange)
    if 'impulse_high' in trade and trade['impulse_high'] > 0:
        impulse_line = [trade['impulse_high']] * len(day_bars)
        apds.append(mpf.make_addplot(impulse_line, color='orange', linestyle=':', width=1))

    # Previous Candle High (Purple) - The breakout level
    if 'prev_candle_high' in trade and trade['prev_candle_high'] > 0:
        prev_high_line = [trade['prev_candle_high']] * len(day_bars)
        apds.append(mpf.make_addplot(prev_high_line, color='purple', linestyle=':', width=1))

    # Markers for Entry and Exit
    # Find the closest bar index for entry and exit times
    entry_idx = day_bars.index.searchsorted(trade['entry_time'])
    exit_idx = day_bars.index.searchsorted(trade['exit_time'])
    
    # Ensure indices are within bounds
    entry_idx = min(entry_idx, len(day_bars) - 1)
    exit_idx = min(exit_idx, len(day_bars) - 1)

    # Create marker arrays (NaN everywhere except event)
    entry_marker = [np.nan] * len(day_bars)
    exit_marker = [np.nan] * len(day_bars)
    
    entry_marker[entry_idx] = trade['entry_price']
    exit_marker[exit_idx] = trade['exit_price']
    
    apds.append(mpf.make_addplot(entry_marker, type='scatter', markersize=100, marker='^', color='green'))
    apds.append(mpf.make_addplot(exit_marker, type='scatter', markersize=100, marker='v', color='red'))

    # Plot
    filename = f"{symbol}_{date_str}_{trade['exit_reason']}.png"
    filepath = output_dir / filename
    
    title = f"{symbol} {date_str} ({trade['exit_reason']}) PnL: ${trade['pnl']:.2f}"
    
    mpf.plot(
        day_bars,
        type='candle',
        style='charles',
        title=title,
        ylabel='Price',
        volume=True,
        addplot=apds,
        savefig=dict(fname=str(filepath), dpi=100, bbox_inches='tight')
    )
    print(f"Saved chart: {filepath}")

def main():
    parser = argparse.ArgumentParser(description="Generate trade charts")
    parser.add_argument("--trades", required=True, help="Path to trades parquet file")
    parser.add_argument("--universe", required=True, help="Path to universe parquet file")
    args = parser.parse_args()

    trades_path = Path(args.trades)
    universe_path = Path(args.universe)
    
    if not trades_path.exists():
        print(f"Trades file not found: {trades_path}")
        return
    if not universe_path.exists():
        print(f"Universe file not found: {universe_path}")
        return

    # Load data
    print("Loading trades...")
    trades_df = pd.read_parquet(trades_path)
    
    # Combine trade_date and entry_time/exit_time to get full datetime
    # trade_date is YYYY-MM-DD string, entry_time is HH:MM:SS string
    trades_df['entry_time'] = pd.to_datetime(trades_df['trade_date'] + ' ' + trades_df['entry_time'])
    trades_df['exit_time'] = pd.to_datetime(trades_df['trade_date'] + ' ' + trades_df['exit_time'])
        
    print(f"Loaded {len(trades_df)} trades")
    
    print("Loading universe...")
    universe_df = pd.read_parquet(universe_path)
    print(f"Loaded {len(universe_df)} universe candidates")

    # Ensure output directory exists
    output_dir = trades_path.parent / "trade_charts"
    output_dir.mkdir(exist_ok=True)
    
    # Select trades to plot
    # 1. Top 3 Winners
    winners = trades_df.nlargest(3, 'pnl')
    # 2. Top 3 Losers
    losers = trades_df.nsmallest(3, 'pnl')
    # 3. Random 3 EOD exits
    eod_exits_df = trades_df[trades_df['exit_reason'] == 'EOD']
    if not eod_exits_df.empty:
        eod_exits = eod_exits_df.sample(min(3, len(eod_exits_df)))
    else:
        eod_exits = pd.DataFrame()
    
    trades_to_plot = pd.concat([winners, losers, eod_exits]).drop_duplicates()
    
    print(f"Generating charts for {len(trades_to_plot)} trades...")
    
    # Ensure universe trade_date is datetime
    if not pd.api.types.is_datetime64_any_dtype(universe_df['trade_date']):
         universe_df['trade_date'] = pd.to_datetime(universe_df['trade_date'])

    print(f"Universe dates range: {universe_df['trade_date'].min()} to {universe_df['trade_date'].max()}")
    if not trades_df.empty:
        print(f"Trades dates range: {trades_df['entry_time'].dt.date.min()} to {trades_df['entry_time'].dt.date.max()}")

    for _, trade in trades_to_plot.iterrows():
        # Find corresponding universe row to get bars
        # Match on symbol and date
        trade_date = trade['entry_time'].date()
        
        candidate = universe_df[
            (universe_df['ticker'] == trade['ticker']) & 
            (universe_df['trade_date'].dt.date == trade_date)
        ]
        
        if candidate.empty:
            print(f"Warning: No universe data found for {trade['ticker']} on {trade_date}")
            continue
            
        bars_json = candidate.iloc[0]['bars_json']
        bars_df = parse_bars_json(bars_json)
        
        if bars_df.empty:
            print(f"Warning: Empty bars for {trade['ticker']} on {trade_date}")
            continue
            
        plot_trade(trade, bars_df, output_dir)

if __name__ == "__main__":
    main()
