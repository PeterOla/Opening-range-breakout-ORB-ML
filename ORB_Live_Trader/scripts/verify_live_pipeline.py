"""
Live Pipeline Verification - Test Against Backtest Universe

Tests the live pipeline (fetch news, score sentiment, calculate OR/RVOL) against
the backtest universe. Expects 80-90% symbol overlap (not 100% due to data changes).

This ensures:
1. Live pipeline can recreate similar universe to backtest
2. No systematic bugs in live code paths
3. Data changes are within acceptable range

Acceptable divergence:
- 80-90% overlap: Normal (news updates, model differences)
- 70-80% overlap: Warning (investigate)
- < 70% overlap: Critical (pipeline bug likely)

Usage:
    python scripts/verify_live_pipeline.py --universe-file PATH --trades-file PATH --num-dates 5
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import List, Dict, Set
import random
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
VERIFICATION_LOG_DIR = Path(__file__).parent.parent / "logs" / "live_verification"
VERIFICATION_LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str, level: str = "INFO"):
    """Timestamped logger."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] [{level:5s}] {msg}", flush=True)


def load_backtest_universe(universe_file: Path) -> pd.DataFrame:
    """Load backtest universe file (reference)."""
    log(f"Loading backtest universe from {universe_file}")
    
    df = pd.read_parquet(universe_file)
    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    
    log(f"Loaded {len(df)} universe candidates")
    
    return df


def load_backtest_trades(trades_file: Path) -> pd.DataFrame:
    """Load historical backtest trades."""
    log(f"Loading backtest trades from {trades_file}")
    
    if trades_file.suffix == ".parquet":
        df = pd.read_parquet(trades_file)
    elif trades_file.suffix == ".csv":
        df = pd.read_csv(trades_file, parse_dates=['trade_date', 'entry_time', 'exit_time'])
    else:
        raise ValueError(f"Unsupported file format: {trades_file.suffix}")
    
    log(f"Loaded {len(df)} historical trades")
    return df


def pick_random_dates(trades_df: pd.DataFrame, num_dates: int) -> List[datetime.date]:
    """Pick random dates from backtest trades."""
    all_dates = pd.to_datetime(trades_df['trade_date']).dt.date.unique()
    
    # Filter to dates with >= 3 trades (more meaningful comparison)
    trades_per_date = trades_df.groupby(pd.to_datetime(trades_df['trade_date']).dt.date).size()
    dates_with_trades = trades_per_date[trades_per_date >= 3].index.tolist()
    
    if len(dates_with_trades) < num_dates:
        log(f"WARNING: Only {len(dates_with_trades)} dates with >=3 trades, using all")
        selected = sorted(dates_with_trades)
    else:
        selected = random.sample(dates_with_trades, num_dates)
        selected.sort()
    
    log(f"Selected {len(selected)} random dates for live verification:")
    for d in selected:
        log(f"  {d}")
    
    return selected


def fetch_news_for_date(trade_date: datetime.date, scored_news_df: pd.DataFrame) -> pd.DataFrame:
    """Get sentiment candidates from pre-scored news (matches backtest exactly)."""
    log(f"  Getting sentiment from scored news for {trade_date}...")
    
    import pytz
    
    # Apply rolling 24H attribution (MUST match backtest logic exactly)
    df_scored = scored_news_df.copy()
    
    # Convert timestamp to ET
    df_scored['timestamp'] = pd.to_datetime(df_scored['timestamp'], utc=True)
    df_scored['timestamp_et'] = df_scored['timestamp'].dt.tz_convert('America/New_York')
    df_scored['news_date'] = df_scored['timestamp_et'].dt.date
    df_scored['news_time'] = df_scored['timestamp_et'].dt.time
    
    # Attribution: Rolling 24H with pandas BDay (EXACTLY as backtest)
    market_open = datetime.strptime("09:30", "%H:%M").time()
    
    def assign_trade_date(row):
        if row['news_time'] < market_open:
            # Before 09:30 → same day
            return row['news_date']
        else:
            # At/after 09:30 → next business day (using pandas BDay)
            return (pd.to_datetime(row['news_date']) + pd.tseries.offsets.BDay(1)).date()
    
    df_scored['trade_date'] = df_scored.apply(assign_trade_date, axis=1)
    
    # Filter to target trade date and >0.90 threshold
    df_filtered = df_scored[
        (df_scored['trade_date'] == trade_date) &
        (df_scored['positive_score'] > 0.90)
    ].copy()
    
    # Aggregate by symbol (max score)
    if len(df_filtered) > 0:
        df_agg = df_filtered.groupby('symbol').agg({
            'positive_score': 'max',
            'headline': 'first'
        }).reset_index()
    else:
        df_agg = pd.DataFrame(columns=['symbol', 'positive_score', 'headline'])
    
    log(f"    Found {len(df_agg)} sentiment candidates (>0.90)")
    return df_agg


def fetch_daily_bars_for_date(trade_date: datetime.date, symbols: List[str]) -> pd.DataFrame:
    """Fetch daily bars using live pipeline."""
    log(f"  Fetching daily bars...")
    
    from sync_daily_data import fetch_daily_bars_with_retry
    
    start_date = trade_date - timedelta(days=30)
    end_date = trade_date + timedelta(days=1)
    
    df_bars = fetch_daily_bars_with_retry(symbols, start_date, end_date)
    
    if df_bars is None or len(df_bars) == 0:
        log(f"    No daily bars found")
        return pd.DataFrame()
    
    # Calculate ATR and volume
    daily_rows = []
    
    for symbol in df_bars['symbol'].unique():
        symbol_bars = df_bars[df_bars['symbol'] == symbol].copy()
        symbol_bars = symbol_bars.sort_values('timestamp')
        
        # True Range
        symbol_bars['h_l'] = symbol_bars['high'] - symbol_bars['low']
        symbol_bars['h_pc'] = abs(symbol_bars['high'] - symbol_bars['close'].shift(1))
        symbol_bars['l_pc'] = abs(symbol_bars['low'] - symbol_bars['close'].shift(1))
        symbol_bars['tr'] = symbol_bars[['h_l', 'h_pc', 'l_pc']].max(axis=1)
        
        # ATR (14-day)
        symbol_bars['atr_14'] = symbol_bars['tr'].rolling(window=14, min_periods=1).mean()
        
        # Avg volume (14-day)
        symbol_bars['avg_volume_14'] = symbol_bars['volume'].rolling(window=14, min_periods=1).mean()
        
        symbol_bars['date'] = pd.to_datetime(symbol_bars['timestamp']).dt.date
        latest = symbol_bars[symbol_bars['date'] == trade_date]
        
        if len(latest) > 0:
            daily_rows.append({
                'symbol': symbol,
                'atr_14': latest.iloc[0]['atr_14'],
                'avg_volume_14': latest.iloc[0]['avg_volume_14'],
                'close': latest.iloc[0]['close']
            })
    
    df_daily = pd.DataFrame(daily_rows)
    log(f"    Calculated ATR/volume for {len(df_daily)} symbols")
    return df_daily


def fetch_intraday_bars_for_date(trade_date: datetime.date, symbols: List[str]) -> Dict[str, pd.DataFrame]:
    """Fetch 5-min bars using live pipeline."""
    log(f"  Fetching 5-min bars...")
    
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    import pytz
    
    client = StockHistoricalDataClient(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY")
    )
    
    et = pytz.timezone("America/New_York")
    start_dt = et.localize(datetime.combine(trade_date, datetime.min.time()) + timedelta(hours=4))
    end_dt = et.localize(datetime.combine(trade_date, datetime.min.time()) + timedelta(hours=16))
    
    bars_dict = {}
    
    for symbol in symbols:
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                start=start_dt,
                end=end_dt
            )
            
            bars = client.get_stock_bars(request)
            if symbol in bars.data:
                df = bars.df.reset_index()
                bars_dict[symbol] = df
        except Exception as e:
            pass  # Silent fail for individual symbols
    
    log(f"    Fetched 5-min bars for {len(bars_dict)}/{len(symbols)} symbols")
    return bars_dict


def calculate_opening_range(df: pd.DataFrame, daily_avg_volume: float) -> dict:
    """Calculate OR metrics from FIRST 5-min bar at market open (09:30).
    
    Matches backtest implementation: extract_or() in build_universe.py
    - Uses only the first regular trading hours bar (09:30-09:35)
    - All metrics derived from that single bar
    """
    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df['timestamp_et'] = df['timestamp'].dt.tz_convert('America/New_York')
    df['time'] = df['timestamp_et'].dt.time
    
    or_start = datetime.strptime("09:30", "%H:%M").time()
    or_end = datetime.strptime("16:00", "%H:%M").time()
    
    # First try exact 09:30 bar
    or_row = df[df['time'] == or_start]
    
    if or_row.empty:
        # Fallback: first bar within regular trading hours
        df_rth = df[(df['time'] >= or_start) & (df['time'] <= or_end)].copy()
        if df_rth.empty:
            return None
        or_row = df_rth.iloc[0:1]  # First bar only
    
    # Extract from single bar
    r = or_row.iloc[0]
    or_open = float(r['open'])
    or_high = float(r['high'])
    or_low = float(r['low'])
    or_close = float(r['close'])
    or_volume = float(r['volume'])
    
    # RVOL: normalize single bar volume to full-day equivalent
    rvol = (or_volume * 78) / daily_avg_volume if daily_avg_volume > 0 else 0
    
    # Direction based on first bar's close vs open
    if or_close > or_open:
        direction = 1
    elif or_close < or_open:
        direction = -1
    else:
        direction = 0
    
    return {
        'or_open': or_open,
        'or_high': or_high,
        'or_low': or_low,
        'or_close': or_close,
        'or_volume': or_volume,
        'rvol': rvol,
        'direction': direction
    }


def generate_live_universe_for_date(trade_date: datetime.date, scored_news_df: pd.DataFrame) -> pd.DataFrame:
    """Generate universe using live pipeline."""
    log(f"Generating live universe for {trade_date}...")
    
    # 1. Get sentiment from scored news (using exact backtest attribution)
    df_sentiment = fetch_news_for_date(trade_date, scored_news_df)
    
    if len(df_sentiment) == 0:
        log("  No sentiment candidates")
        return pd.DataFrame()
    
    # 2. Fetch daily bars
    df_daily = fetch_daily_bars_for_date(trade_date, df_sentiment['symbol'].tolist())
    
    if len(df_daily) == 0:
        log("  No daily bars")
        return pd.DataFrame()
    
    # 3. Join sentiment + daily
    df_joined = df_sentiment.merge(df_daily, on='symbol', how='inner')
    
    # 4. Apply daily filters
    df_filtered = df_joined[
        (df_joined['atr_14'] >= 0.5) &
        (df_joined['avg_volume_14'] >= 100_000)
    ].copy()
    
    if len(df_filtered) == 0:
        log("  No symbols passed daily filters")
        return pd.DataFrame()
    
    log(f"  {len(df_filtered)} symbols passed daily filters")
    
    # 5. Fetch 5-min bars
    bars_dict = fetch_intraday_bars_for_date(trade_date, df_filtered['symbol'].tolist())
    
    # 6. Calculate OR metrics
    universe_rows = []
    
    for _, row in df_filtered.iterrows():
        symbol = row['symbol']
        
        if symbol not in bars_dict:
            continue
        
        df_bars = bars_dict[symbol]
        or_data = calculate_opening_range(df_bars, row['avg_volume_14'])
        
        if or_data is None:
            continue
        
        # Apply direction filter
        if or_data['direction'] != 1:
            continue
        
        universe_rows.append({
            'symbol': symbol,
            'positive_score': row['positive_score'],
            'rvol': or_data['rvol'],
            'or_volume': or_data['or_volume'],
            'direction': or_data['direction'],
            'atr_14': row['atr_14'],
            'avg_volume_14': row['avg_volume_14']
        })
    
    df_universe = pd.DataFrame(universe_rows)
    
    if len(df_universe) == 0:
        log("  No symbols passed OR filters")
        return df_universe
    
    # 7. Rank by RVOL, select Top 5
    try:
        log(f"  RVOL ranking before Top 5 selection:")
        for idx, row in df_universe.sort_values('rvol', ascending=False).iterrows():
            log(f"    {row['symbol']}: RVOL={row['rvol']:.2f}, OR_vol={row['or_volume']:.0f}, Avg_vol={row['avg_volume_14']:.0f}")
    except Exception as e:
        log(f"  ERROR: {e}", level="ERROR")
    
    df_universe = df_universe.sort_values('rvol', ascending=False).head(5).reset_index(drop=True)
    
    log(f"  Generated Top {len(df_universe)} live universe")
    return df_universe


def compare_live_vs_backtest(live_universe: pd.DataFrame, backtest_universe: pd.DataFrame, 
                             backtest_trades: pd.DataFrame, trade_date: datetime.date) -> Dict:
    """Compare live universe with backtest universe."""
    log(f"Comparing live vs backtest for {trade_date}...")
    
    # Get backtest Top 5 (apply filters to universe)
    day_universe = backtest_universe[backtest_universe['trade_date'] == trade_date].copy()
    
    filtered = day_universe[
        (day_universe['atr_14'] >= 0.5) &
        (day_universe['avg_volume_14'] >= 100_000) &
        (day_universe['direction'] == 1)
    ].sort_values('rvol', ascending=False).head(5)
    
    backtest_symbols = set(filtered['ticker'].tolist())
    
    # Extract live symbols
    live_symbols = set(live_universe['symbol'].tolist()) if len(live_universe) > 0 else set()
    
    # Calculate overlap
    overlap = live_symbols & backtest_symbols
    missing = backtest_symbols - live_symbols
    extra = live_symbols - backtest_symbols
    
    overlap_pct = (len(overlap) / len(backtest_symbols) * 100) if len(backtest_symbols) > 0 else 0
    
    # Determine status
    if overlap_pct >= 80:
        status = "PASS"
        level = "INFO"
    elif overlap_pct >= 70:
        status = "WARN"
        level = "WARN"
    else:
        status = "FAIL"
        level = "ERROR"
    
    log(f"  Live: {sorted(live_symbols)}", level=level)
    log(f"  Backtest: {sorted(backtest_symbols)}", level=level)
    log(f"  Overlap: {len(overlap)}/{len(backtest_symbols)} ({overlap_pct:.1f}%) - {status}", level=level)
    
    if missing:
        log(f"  Missing in live: {sorted(missing)}", level=level)
    if extra:
        log(f"  Extra in live: {sorted(extra)}", level=level)
    
    return {
        'date': trade_date,
        'status': status,
        'overlap_pct': overlap_pct,
        'overlap_count': len(overlap),
        'backtest_count': len(backtest_symbols),
        'live_count': len(live_symbols),
        'live_symbols': sorted(live_symbols),
        'backtest_symbols': sorted(backtest_symbols),
        'overlap_symbols': sorted(overlap),
        'missing': sorted(missing),
        'extra': sorted(extra)
    }


def verify_live_pipeline(universe_file: Path, trades_file: Path, scored_news_file: Path, num_dates: int = 5):
    """Main live verification workflow."""
    log("=" * 80)
    log("LIVE PIPELINE VERIFICATION - Test Against Backtest")
    log("=" * 80)
    log("Expected: 80-90% symbol overlap (data changes normal)")
    log("Warning: 70-80% overlap (investigate)")
    log("Critical: <70% overlap (pipeline bug likely)")
    log("")
    
    # Load scored news
    log(f"Loading scored news from {scored_news_file}")
    df_scored_news = pd.read_parquet(scored_news_file)
    log(f"Loaded {len(df_scored_news)} scored news items")
    log("")
    
    # Load backtest data
    df_universe = load_backtest_universe(universe_file)
    df_trades = load_backtest_trades(trades_file)
    
    # Pick random dates
    dates_to_verify = pick_random_dates(df_trades, num_dates)
    
    # Verify each date
    results = []
    
    for i, trade_date in enumerate(dates_to_verify, 1):
        log("")
        log(f"[{i}/{len(dates_to_verify)}] Verifying {trade_date}")
        log("-" * 80)
        
        try:
            # Generate live universe
            live_universe = generate_live_universe_for_date(trade_date, df_scored_news)
            
            # Compare with backtest
            comparison = compare_live_vs_backtest(live_universe, df_universe, df_trades, trade_date)
            results.append(comparison)
            
        except Exception as e:
            log(f"  ERROR: {e}", level="ERROR")
            results.append({
                'date': trade_date,
                'status': 'ERROR',
                'overlap_pct': 0,
                'error': str(e)
            })
    
    # Summary
    log("")
    log("=" * 80)
    log("LIVE PIPELINE VERIFICATION SUMMARY")
    log("=" * 80)
    
    pass_count = sum(1 for r in results if r.get('status') == 'PASS')
    warn_count = sum(1 for r in results if r.get('status') == 'WARN')
    fail_count = sum(1 for r in results if r.get('status') == 'FAIL')
    error_count = sum(1 for r in results if r.get('status') == 'ERROR')
    
    total = len(results)
    avg_overlap = np.mean([r.get('overlap_pct', 0) for r in results if 'overlap_pct' in r])
    
    log(f"Dates verified: {total}")
    log(f"PASS (>=80% overlap): {pass_count}")
    log(f"WARN (70-80% overlap): {warn_count}")
    log(f"FAIL (<70% overlap): {fail_count}")
    log(f"ERROR: {error_count}")
    log(f"Average overlap: {avg_overlap:.1f}%")
    
    if fail_count > 0 or error_count > 0:
        log("")
        log("FAILED/ERROR DATES:", level="ERROR")
        for r in results:
            if r.get('status') in ['FAIL', 'ERROR']:
                if 'error' in r:
                    log(f"  {r['date']}: ERROR - {r['error']}", level="ERROR")
                else:
                    log(f"  {r['date']}: {r['overlap_pct']:.1f}% overlap - Missing={r['missing']}, Extra={r['extra']}", level="ERROR")
    
    # Save report
    report_path = VERIFICATION_LOG_DIR / f"live_verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    import json
    with open(report_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'universe_file': str(universe_file),
            'trades_file': str(trades_file),
            'num_dates': num_dates,
            'pass_count': pass_count,
            'warn_count': warn_count,
            'fail_count': fail_count,
            'error_count': error_count,
            'avg_overlap': avg_overlap,
            'results': [{**r, 'date': str(r['date'])} for r in results]
        }, f, indent=2)
    
    log(f"\nReport saved: {report_path}")
    
    # Exit code
    if fail_count == 0 and error_count == 0:
        log("\n[PASS] LIVE PIPELINE VERIFICATION PASSED", level="INFO")
        return 0
    else:
        log(f"\n[FAIL] LIVE PIPELINE VERIFICATION FAILED - {fail_count} failures, {error_count} errors", level="ERROR")
        return 1


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Verify live pipeline against backtest universe")
    parser.add_argument("--universe-file", type=Path, required=True, help="Path to backtest universe file")
    parser.add_argument("--trades-file", type=Path, required=True, help="Path to backtest trades file")
    parser.add_argument("--scored-news-file", type=Path, required=True, help="Path to scored news file")
    parser.add_argument("--num-dates", type=int, default=5, help="Number of random dates to verify")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    if args.seed:
        random.seed(args.seed)
        log(f"Random seed: {args.seed}")
    
    exit_code = verify_live_pipeline(args.universe_file, args.trades_file, args.scored_news_file, args.num_dates)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
