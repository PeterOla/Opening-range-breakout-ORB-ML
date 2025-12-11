"""
Ross Cameron Bull Flag Backtest Engine (Revised).

Strategy: "First Candle to Make a New High"
1. Impulse: +4% move within first 30 mins (9:30-10:00 ET).
2. Pullback: Price holds above 65% of impulse move.
3. Entry: Buy the first candle that breaks the HIGH of the PREVIOUS candle (1-bar breakout).
   - This gets us in *during* the pullback reversal, not at the top.
4. Stop: Lowest low of the pullback.
5. Target: 2:1 Reward/Risk.

Usage:
    python scripts/backtest_ross_cameron.py --universe data/backtest/ross_cameron/universe_rc_*.parquet --run-name rc_1bar_breakout
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import datetime, time, timedelta
from typing import Optional, Dict, List
import pandas as pd
import numpy as np
import json
from dataclasses import dataclass, asdict
from tqdm import tqdm

OUT_DIR = Path(__file__).resolve().parents[4] / "data" / "backtest" / "ross_cameron"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Strategy Parameters
IMPULSE_THRESHOLD_PCT = 4.0
IMPULSE_WINDOW_BARS = 6  # 30 mins
FLAG_HOLD_PCT = 65.0     # Must hold 65% of move
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

@dataclass
class Trade:
    trade_date: str
    ticker: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    exit_reason: str
    pnl: float
    pnl_pct: float
    impulse_high: float
    pullback_low: float
    prev_candle_high: float  # The level we broke to enter

def parse_bars_json(bars_json: str) -> pd.DataFrame:
    """Deserialize 5-min bars from JSON string."""
    bars = json.loads(bars_json)
    df = pd.DataFrame(bars)
    if 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'], utc=False)
    elif 'timestamp' in df.columns:
        df['datetime'] = pd.to_datetime(df['timestamp'], utc=False)
    else:
        raise ValueError("No datetime column")
    
    df = df.sort_values('datetime').reset_index(drop=True)
    df['time'] = df['datetime'].dt.time
    
    # Filter Market Hours (9:30 - 16:00)
    df = df[(df['time'] >= MARKET_OPEN) & (df['time'] <= MARKET_CLOSE)].reset_index(drop=True)
    return df

def detect_and_simulate(bars: pd.DataFrame) -> Optional[Trade]:
    """
    Scans the day for the FIRST valid setup.
    
    Logic:
    1. Find Impulse Peak (Highest High in first 30m).
    2. Verify Impulse > 4%.
    3. Scan bars AFTER Impulse Peak for Pullback.
    4. Entry Trigger: Current High > Previous High.
    """
    if len(bars) < 3:
        return None

    # 1. Identify Impulse (First 30 mins / 6 bars)
    impulse_window = bars.iloc[:IMPULSE_WINDOW_BARS]
    if impulse_window.empty:
        return None
        
    impulse_high_idx = impulse_window['high'].idxmax()
    impulse_high = impulse_window.loc[impulse_high_idx, 'high']
    
    # Impulse Start (Open of 9:30 bar)
    impulse_open = bars.iloc[0]['open']
    
    # Check 4% Move
    impulse_gain_pct = ((impulse_high - impulse_open) / impulse_open) * 100.0
    if impulse_gain_pct < IMPULSE_THRESHOLD_PCT:
        return None

    # Calculate Support (Must hold 65% of move)
    move_size = impulse_high - impulse_open
    support_level = impulse_high - (move_size * (FLAG_HOLD_PCT / 100.0)) # Actually this logic was "Hold above 65%", so max drawdown is 35%. 
    # Wait, "Holds above 65% of impulse" usually means it retains 65% of the gain.
    # So it drops max 35%.
    # Let's stick to the previous logic: Retracement allowed is 35%.
    # Support = Open + (Move * 0.65)
    support_level = impulse_open + (move_size * 0.65)

    # 2. Scan for Pullback & Entry
    # Start scanning from the bar AFTER the impulse peak
    # We need at least 1 bar of pullback (High < Impulse High) to define a "pullback"
    
    pullback_low = impulse_high # Initialize
    
    for i in range(impulse_high_idx + 1, len(bars)):
        current_bar = bars.iloc[i]
        prev_bar = bars.iloc[i-1]
        
        # Update Pullback Low (Lowest low since peak)
        if current_bar['low'] < pullback_low:
            pullback_low = current_bar['low']
            
        # FAIL CONDITION: Broke Support
        if current_bar['low'] < support_level:
            return None # Pattern failed
            
        # ENTRY CONDITION: "First candle to make a new high"
        # We break the High of the PREVIOUS candle.
        # We also want to ensure we are actually in a pullback (i.e., we are not just extending the impulse immediately).
        # So we require that at least one bar (prev_bar) had a High < Impulse High.
        
        if prev_bar['high'] < impulse_high:
            # We are/were in a pullback/consolidation below the peak
            
            # Check for 1-Bar Breakout
            if current_bar['high'] > prev_bar['high']:
                # TRIGGER!
                entry_price = prev_bar['high'] + 0.01
                
                # Stop Loss = Lowest point of the pullback so far
                # (which is either current bar low or prev lows)
                stop_price = min(pullback_low, current_bar['low'])
                
                # Sanity Check: Risk > 0
                if entry_price <= stop_price:
                    continue 
                    
                # Execute Trade
                return execute_trade(bars, i, entry_price, stop_price, impulse_high, pullback_low, prev_bar['high'])
                
    return None

def execute_trade(bars, entry_idx, entry_price, stop_price, impulse_high, pullback_low, prev_high):
    risk = entry_price - stop_price
    target_price = entry_price + (2.0 * risk)
    
    entry_bar = bars.iloc[entry_idx]
    entry_time = entry_bar['datetime']
    
    # Scan future bars for exit
    for i in range(entry_idx, len(bars)):
        bar = bars.iloc[i]
        
        # Check Stop (Low hits stop)
        # Note: On entry bar, we assume we enter on the way up. If it reverses same bar, we stop out.
        if bar['low'] <= stop_price:
            # Did we hit target first? (High >= Target)
            # Conservative: Assume Stop hit first if both happen in same bar, unless Open was close to Target.
            # Let's assume Stop hit first for safety.
            return Trade(
                trade_date=entry_time.strftime('%Y-%m-%d'),
                ticker=bars.iloc[0]['symbol'] if 'symbol' in bars.columns else 'UNKNOWN',
                entry_time=entry_time.strftime('%H:%M:%S'),
                entry_price=entry_price,
                exit_time=bar['datetime'].strftime('%H:%M:%S'),
                exit_price=stop_price,
                exit_reason='STOP',
                pnl=stop_price - entry_price,
                pnl_pct=((stop_price - entry_price)/entry_price)*100,
                impulse_high=impulse_high,
                pullback_low=pullback_low,
                prev_candle_high=prev_high
            )
            
        # Check Target
        if bar['high'] >= target_price:
            return Trade(
                trade_date=entry_time.strftime('%Y-%m-%d'),
                ticker=bars.iloc[0]['symbol'] if 'symbol' in bars.columns else 'UNKNOWN',
                entry_time=entry_time.strftime('%H:%M:%S'),
                entry_price=entry_price,
                exit_time=bar['datetime'].strftime('%H:%M:%S'),
                exit_price=target_price,
                exit_reason='TARGET',
                pnl=target_price - entry_price,
                pnl_pct=((target_price - entry_price)/entry_price)*100,
                impulse_high=impulse_high,
                pullback_low=pullback_low,
                prev_candle_high=prev_high
            )
            
    # EOD Exit
    last_bar = bars.iloc[-1]
    return Trade(
        trade_date=entry_time.strftime('%Y-%m-%d'),
        ticker=bars.iloc[0]['symbol'] if 'symbol' in bars.columns else 'UNKNOWN',
        entry_time=entry_time.strftime('%H:%M:%S'),
        entry_price=entry_price,
        exit_time=last_bar['datetime'].strftime('%H:%M:%S'),
        exit_price=last_bar['close'],
        exit_reason='EOD',
        pnl=last_bar['close'] - entry_price,
        pnl_pct=((last_bar['close'] - entry_price)/entry_price)*100,
        impulse_high=impulse_high,
        pullback_low=pullback_low,
        prev_candle_high=prev_high
    )

def backtest_universe(universe_path: str, run_name: str, capital: float = 30000.0):
    print(f"Loading universe: {universe_path}")
    df_universe = pd.read_parquet(universe_path)
    
    all_trades = []
    for _, row in tqdm(df_universe.iterrows(), total=len(df_universe), desc="Backtesting"):
        try:
            bars = parse_bars_json(row['bars_json'])
            bars['symbol'] = row['ticker']
            trade = detect_and_simulate(bars)
            if trade:
                all_trades.append(trade)
        except Exception as e:
            continue
            
    if not all_trades:
        print("No trades generated.")
        return

    # Save Results
    df_trades = pd.DataFrame([asdict(t) for t in all_trades])
    trades_path = OUT_DIR / f"trades_{run_name}.parquet"
    df_trades.to_parquet(trades_path)
    
    # Daily Performance
    df_trades['date'] = pd.to_datetime(df_trades['trade_date'])
    daily_perf = df_trades.groupby('date').agg(
        trades=('ticker', 'count'),
        wins=('pnl', lambda x: (x > 0).sum()),
        total_pnl=('pnl', 'sum')
    ).reset_index()
    daily_perf.to_parquet(OUT_DIR / f"daily_performance_{run_name}.parquet")
    
    # Equity Curve
    daily_perf['equity'] = capital + daily_perf['total_pnl'].cumsum()
    daily_perf.to_parquet(OUT_DIR / f"equity_curve_{run_name}.parquet")
    
    print(f"✓ Saved {len(df_trades)} trades to {trades_path}")
    print(f"  Win Rate: {len(df_trades[df_trades['pnl']>0]) / len(df_trades) * 100:.1f}%")
    print(f"  Total PnL: ${df_trades['pnl'].sum():.2f}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--capital", type=float, default=30000.0)
    args = parser.parse_args()
    
    backtest_universe(args.universe, args.run_name, args.capital)

if __name__ == "__main__":
    main()
