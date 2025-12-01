"""
Bulk historical backtest orchestrator (DuckDB + Parquet, local only).

Reads daily and 5-min parquet files, simulates ORB trades, writes results to:
- data/backtest/simulated_trades.parquet
- data/backtest/daily_performance.parquet

Usage:
    python scripts/bulk_backtest.py --start 2021-01-01 --end 2025-11-28 --top-n 20
"""
import sys
sys.path.insert(0, ".")

import argparse
from pathlib import Path
from datetime import date, time, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
from tqdm import tqdm
import duckdb

# Position sizing
CAPITAL = 1000.0
LEVERAGE = 2.0

# Data dirs
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DATA_DIR_5MIN = DATA_DIR / "processed" / "5min"
DATA_DIR_DAILY = DATA_DIR / "processed" / "daily"
OUT_DIR = DATA_DIR / "backtest"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TRADES_PARQUET = OUT_DIR / "simulated_trades.parquet"
DAILY_PARQUET = OUT_DIR / "daily_performance.parquet"

# Opening range time (Eastern)
OR_START = time(9, 30)


def list_trading_days(start: str, end: str) -> List[date]:
    """Build trading days from daily parquet data."""
    con = duckdb.connect()
    df_dates = con.execute(f"""
      SELECT DISTINCT CAST(date AS DATE) AS d
      FROM read_parquet('{DATA_DIR_DAILY.as_posix()}/**/*.parquet', union_by_name=true)
      WHERE date >= DATE '{start}' AND date <= DATE '{end}'
      ORDER BY d
    """).df()
    con.close()
    return list(df_dates['d'])


def load_daily(symbol: str) -> Optional[pd.DataFrame]:
    p = DATA_DIR_DAILY / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:
        return None
    if 'date' not in df.columns or df.empty:
        return None
    # Keep as date objects, don't convert
    return df


def load_5min(symbol: str, trading_date: date) -> Optional[pd.DataFrame]:
    p = DATA_DIR_5MIN / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:
        return None
    if df.empty:
        return None
    ts_col = 'timestamp' if 'timestamp' in df.columns else ('date' if 'date' in df.columns else None)
    if ts_col is None:
        return None
    dt = pd.to_datetime(df[ts_col])
    df['datetime'] = dt
    df['date_only'] = df['datetime'].dt.date
    day = df[df['date_only'] == trading_date].copy()
    if day.empty:
        return None
    day['time'] = day['datetime'].dt.time
    return day.sort_values('datetime').reset_index(drop=True)


def extract_or(bars: pd.DataFrame) -> Optional[dict]:
    """Extract the 9:30 ET bar as the Opening Range (single bar)."""
    or_row = bars[bars['time'] == OR_START]
    if or_row.empty:
        return None
    r = or_row.iloc[0]
    return {
        'or_open': float(r['open']),
        'or_high': float(r['high']),
        'or_low': float(r['low']),
        'or_close': float(r['close']),
        'or_volume': float(r['volume']),
    }


def compute_rvol(or_volume: float, avg_volume_14: float) -> float:
    if not avg_volume_14 or avg_volume_14 <= 0:
        return 0.0
    return (or_volume * 78.0) / avg_volume_14


def simulate_trade(bars: pd.DataFrame, direction: int, entry_level: float, stop_level: float) -> dict:
    trade_bars = bars[bars['time'] > OR_START].copy()
    if trade_bars.empty:
        return {'entered': False, 'exit_reason': 'NO_BARS'}
    in_trade = False
    entry_price = None
    entry_time = None
    exit_price = None
    exit_time = None
    exit_reason = None
    for _, bar in trade_bars.iterrows():
        if not in_trade:
            if direction == 1 and bar['high'] >= entry_level:
                in_trade, entry_price, entry_time = True, entry_level, bar['time']
            elif direction == -1 and bar['low'] <= entry_level:
                in_trade, entry_price, entry_time = True, entry_level, bar['time']
        else:
            if direction == 1 and bar['low'] <= stop_level:
                exit_price, exit_time, exit_reason = stop_level, bar['time'], 'STOP_LOSS'
                break
            elif direction == -1 and bar['high'] >= stop_level:
                exit_price, exit_time, exit_reason = stop_level, bar['time'], 'STOP_LOSS'
                break
    if in_trade and exit_price is None:
        last = trade_bars.iloc[-1]
        exit_price, exit_time, exit_reason = float(last['close']), last['time'], 'EOD'
    if not in_trade:
        return {'entered': False, 'exit_reason': 'NO_ENTRY'}
    direction_sign = 1 if direction == 1 else -1
    price_move = (exit_price - entry_price) * direction_sign
    pnl_pct = (price_move / entry_price) * 100.0
    position_value = CAPITAL * LEVERAGE
    shares = position_value / entry_price
    dollar_pnl = shares * price_move
    base_dollar_pnl = (CAPITAL / entry_price) * price_move
    first_bar, last_bar = bars.iloc[0], bars.iloc[-1]
    day_change_pct = round((float(last_bar['close']) - float(first_bar['open'])) / float(first_bar['open']) * 100.0, 2)
    return {
        'entered': True,
        'entry_price': round(entry_price, 4),
        'entry_time': entry_time.strftime('%H:%M'),
        'exit_price': round(exit_price, 4),
        'exit_time': exit_time.strftime('%H:%M'),
        'exit_reason': exit_reason,
        'pnl_pct': round(pnl_pct, 2),
        'dollar_pnl': round(dollar_pnl, 2),
        'base_dollar_pnl': round(base_dollar_pnl, 2),
        'day_change_pct': day_change_pct,
    }


def compute_daily_metrics(df_daily: pd.DataFrame, target_date: date) -> Optional[dict]:
    # Get last 20 trading days before target_date
    hist = df_daily[df_daily['date'] < target_date].sort_values('date').tail(20)
    if hist.empty:
        return None
    hist = hist.copy()
    hist['prev_close_calc'] = hist['close'].shift(1)
    hist = hist.dropna(subset=['prev_close_calc'])
    if len(hist) < 14:
        return None
    tr = np.maximum(hist['high'] - hist['prev_close_calc'],
                    np.maximum(hist['prev_close_calc'] - hist['low'], hist['high'] - hist['low']))
    atr14 = pd.Series(tr).rolling(14).mean().iloc[-1] if len(tr) >= 14 else np.nan
    avg_vol14 = hist['volume'].rolling(14).mean().iloc[-1] if len(hist) >= 14 else np.nan
    prev_row = df_daily[df_daily['date'] < target_date].sort_values('date').tail(1)
    prev_close = float(prev_row['close'].iloc[0]) if not prev_row.empty else np.nan
    return {
        'atr_14': float(atr14) if not np.isnan(atr14) else None,
        'avg_volume_14': float(avg_vol14) if not np.isnan(avg_vol14) else None,
        'prev_close': prev_close if not np.isnan(prev_close) else None,
    }

def process_day(trading_date: date, top_n: int) -> dict:
    # Convert pandas Timestamp to date if needed
    if hasattr(trading_date, 'date'):
        trading_date = trading_date.date()
    
    trades = []
    symbols = [p.stem for p in DATA_DIR_DAILY.glob("*.parquet")]
    print(f"\n[DEBUG] {trading_date} (type={type(trading_date)}): {len(symbols)} daily parquet files")
    
    # Sample a few symbols to check ATR calculation
    sample_checked = 0
    for sym in symbols[:10]:
        df = load_daily(sym)
        if df is not None and trading_date in set(df['date']):
            m = compute_daily_metrics(df, trading_date)
            if m and m['atr_14']:
                avg_vol_str = f"{m['avg_volume_14']:.0f}" if m['avg_volume_14'] else "0"
                print(f"[DEBUG] {sym}: ATR={m['atr_14']:.4f}, AvgVol={avg_vol_str}")
                sample_checked += 1
                if sample_checked >= 3:
                    break
    
    stats = {'total': len(symbols), 'no_daily': 0, 'no_date': 0, 'no_metrics': 0, 
             'no_5min': 0, 'no_or': 0, 'price_filter': 0, 'atr_filter': 0, 
             'vol_filter': 0, 'doji': 0, 'rvol_filter': 0}
    
    for symbol in symbols:
        df_daily = load_daily(symbol)
        if df_daily is None:
            stats['no_daily'] += 1
            continue
        if trading_date not in set(df_daily['date']):
            stats['no_date'] += 1
            continue
        metrics = compute_daily_metrics(df_daily, trading_date)
        if not metrics:
            stats['no_metrics'] += 1
            continue
        bars = load_5min(symbol, trading_date)
        if bars is None:
            stats['no_5min'] += 1
            continue
        or_data = extract_or(bars)
        if or_data is None:
            stats['no_or'] += 1
            continue
        if or_data['or_open'] < 5.0:
            stats['price_filter'] += 1
            continue
        if not metrics['atr_14'] or metrics['atr_14'] < 0.50:  # Restored to research spec 0.50
            stats['atr_filter'] += 1
            continue
        # Volume filter per research spec
        if not metrics['avg_volume_14'] or metrics['avg_volume_14'] < 1_000_000:
            stats['vol_filter'] += 1
            continue
        if or_data['or_close'] > or_data['or_open']:
            direction = 1
        elif or_data['or_close'] < or_data['or_open']:
            direction = -1
        else:
            stats['doji'] += 1
            continue
        rvol = compute_rvol(or_data['or_volume'], metrics['avg_volume_14'])
        if rvol < 1.0:
            stats['rvol_filter'] += 1
            continue
        trades.append({
            'symbol': symbol,
            'direction': direction,
            'rvol': rvol,
            'bars': bars,
            **or_data,
            **metrics,
        })
    
    print(f"[DEBUG] Filters: no_daily={stats['no_daily']}, no_date={stats['no_date']}, no_metrics={stats['no_metrics']}, "
          f"no_5min={stats['no_5min']}, no_or={stats['no_or']}, price={stats['price_filter']}, atr={stats['atr_filter']}, "
          f"vol={stats['vol_filter']}, doji={stats['doji']}, rvol={stats['rvol_filter']}")
    print(f"[DEBUG] Candidates after filters: {len(trades)}")
    
    if not trades:
        return {'status': 'no_candidates', 'trades': []}
    trades = sorted(trades, key=lambda x: x['rvol'], reverse=True)[:top_n]
    results = []
    for rank, c in enumerate(trades, 1):
        entry_level = c['or_high'] if c['direction'] == 1 else c['or_low']
        # Research spec: Stop loss = 10% of ATR(14) from entry price
        atr_stop = 0.10 * float(c['atr_14']) if c.get('atr_14') is not None else 0.0
        stop_level = (entry_level - atr_stop) if c['direction'] == 1 else (entry_level + atr_stop)
        sim = simulate_trade(c['bars'], c['direction'], entry_level, stop_level)
        stop_distance_pct = abs(entry_level - stop_level) / entry_level * 100.0
        results.append({
            'trade_date': trading_date,
            'ticker': c['symbol'],
            'side': 'LONG' if c['direction'] == 1 else 'SHORT',
            'rvol_rank': rank,
            'rvol': round(c['rvol'], 2),
            'or_open': c['or_open'],
            'or_high': c['or_high'],
            'or_low': c['or_low'],
            'or_close': c['or_close'],
            'or_volume': c['or_volume'],
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
            'atr_14': c['atr_14'],
            'avg_volume_14': c['avg_volume_14'],
            'prev_close': c['prev_close'],
        })
    return {'status': 'success', 'trades': results}

def append_parquet(path: Path, df: pd.DataFrame):
    # Always overwrite - no append behavior
    df.to_parquet(path, index=False)

def run_backtest(start: str, end: str, top_n: int):
    days = list_trading_days(start, end)
    print(f"Trading days: {len(days)}")
    totals = {'days': 0, 'trades': 0, 'entered': 0, 'winners': 0, 'losers': 0, 'pnl_base': 0.0}
    for d in tqdm(days, desc="Processing days"):
        day_res = process_day(d, top_n)
        if day_res['status'] != 'success':
            continue
        df_trades = pd.DataFrame(day_res['trades'])
        append_parquet(TRADES_PARQUET, df_trades)
        entered = df_trades[df_trades['exit_reason'] != 'NO_ENTRY']
        winners = entered[entered['pnl_pct'] > 0]
        losers = entered[entered['pnl_pct'] < 0]
        day_perf = pd.DataFrame([{
            'date': d,
            'trades': len(df_trades),
            'entered': len(entered),
            'winners': len(winners),
            'losers': len(losers),
            'total_base_pnl': float(entered['base_dollar_pnl'].fillna(0).sum()),
            'total_leveraged_pnl': float(entered['dollar_pnl'].fillna(0).sum()),
        }])
        append_parquet(DAILY_PARQUET, day_perf)
        totals['days'] += 1
        totals['trades'] += len(df_trades)
        totals['entered'] += len(entered)
        totals['winners'] += len(winners)
        totals['losers'] += len(losers)
        totals['pnl_base'] += float(entered['base_dollar_pnl'].fillna(0).sum())
    print(f"\nDone. Days: {totals['days']}, Trades: {totals['trades']}, Entered: {totals['entered']}, WinRate: {(totals['winners']/totals['entered']*100 if totals['entered'] else 0):.1f}%")
    print(f"Total P&L (1x): ${totals['pnl_base']:,.2f} | (2x): ${totals['pnl_base']*LEVERAGE:,.2f}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=str, default='2021-01-03')
    ap.add_argument('--end', type=str, default='2021-01-05')
    ap.add_argument('--top-n', type=int, default=20)
    args = ap.parse_args()
    print(f"Bulk Backtest (local) {args.start} → {args.end} | Top {args.top_n}")
    run_backtest(args.start, args.end, args.top_n)

if __name__ == "__main__":
    main()
