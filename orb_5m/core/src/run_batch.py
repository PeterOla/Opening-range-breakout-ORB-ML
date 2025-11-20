import pandas as pd
from pathlib import Path
import sys
import datetime
from tqdm import tqdm
import warnings

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from orb_5m.core.src.strategy_orb import run_orb_single_symbol

def run_batch_2025():
    # Configuration
    START_DATE = "2025-01-01"
    END_DATE = "2025-12-31"
    USE_ML = True
    ML_THRESHOLD = 0.50  # Lowest threshold to capture all needed trades
    TARGET_THRESHOLDS = [0.5, 0.6, 0.65, 0.7]
    INITIAL_EQUITY = 1000.0
    
    # Realistic Simulation Settings
    SLIPPAGE_PER_SHARE = 0.01  # $0.01 slippage per share (entry + exit = $0.02 round trip impact)
    MIN_COMMISSION = 1.00      # Minimum $1.00 per trade
    COMMISSION_PER_SHARE = 0.005 # Slightly higher commission to be safe
    MIN_PRICE = 5.0            # Avoid penny stocks
    MIN_ATR = 0.50             # Avoid low volatility stocks
    
    # Data directory
    UNIVERSE_PATH = PROJECT_ROOT / "data" / "processed" / "universes" / "top50_rvol.parquet"
    RESULTS_DIR = PROJECT_ROOT / "orb_5m" / "core" / "results"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    if not UNIVERSE_PATH.exists():
        print(f"Universe file not found at {UNIVERSE_PATH}. Please run generate_universe.py first.")
        return

    print("Loading Universe (Top 50 RVOL)...")
    universe_df = pd.read_parquet(UNIVERSE_PATH)
    
    # Filter for date range
    universe_df['date'] = pd.to_datetime(universe_df['date'])
    mask = (universe_df['date'] >= pd.to_datetime(START_DATE)) & (universe_df['date'] <= pd.to_datetime(END_DATE))
    universe_df = universe_df[mask].copy()
    
    # Get unique symbols and their valid dates
    # Group by symbol and collect dates into a set/list
    symbol_dates = universe_df.groupby('symbol')['date'].apply(lambda x: set(x.dt.date)).to_dict()
    symbols = list(symbol_dates.keys())
    
    print(f"Found {len(symbols)} symbols in Top 50 Universe for 2025. Starting batch run with base threshold {ML_THRESHOLD}...")
    
    all_trades_list = []
    
    # Progress bar
    for symbol in tqdm(symbols):
        try:
            valid_dates = symbol_dates[symbol]
            
            # Suppress warnings for cleaner output
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                trades, daily_pnl = run_orb_single_symbol(
                    symbol=symbol,
                    start_date=START_DATE,
                    end_date=END_DATE,
                    use_ml=USE_ML,
                    ml_threshold=ML_THRESHOLD,
                    valid_dates=valid_dates, # Pass the specific dates
                    initial_equity=INITIAL_EQUITY,
                    slippage_per_share=SLIPPAGE_PER_SHARE,
                    min_commission_per_trade=MIN_COMMISSION,
                    commission_per_share=COMMISSION_PER_SHARE,
                    min_price=MIN_PRICE,
                    min_atr=MIN_ATR
                )
            
            if not trades.empty:
                all_trades_list.append(trades)
                
        except Exception as e:
            # print(f"Error processing {symbol}: {e}")
            continue
            
    # Create summary DataFrame
    if all_trades_list:
        full_df = pd.concat(all_trades_list, ignore_index=True)
        full_df['date'] = pd.to_datetime(full_df['date'])
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save raw trades first
        all_trades_path = RESULTS_DIR / f"all_trades_raw_2025_{timestamp}.csv"
        full_df.to_csv(all_trades_path, index=False)
        print(f"\nRaw trades saved to {all_trades_path}")

        for thresh in TARGET_THRESHOLDS:
            print(f"\n--- Processing results for Threshold >= {thresh} ---")
            
            # Filter trades by probability
            # Ensure ml_prob is float
            df_thresh = full_df[full_df['ml_prob'].astype(float) >= thresh].copy()
            
            if df_thresh.empty:
                print(f"No trades found for threshold {thresh}")
                continue
                
            # 1. Generate Per-Symbol Summary (Batch Results)
            def calc_pf(x):
                gross_win = x[x > 0].sum()
                gross_loss = abs(x[x < 0].sum())
                return gross_win / gross_loss if gross_loss > 0 else float('inf')

            symbol_stats = df_thresh.groupby('symbol').agg(
                trades=('net_pnl', 'count'),
                total_pnl=('net_pnl', 'sum'),
                avg_pnl=('net_pnl', 'mean'),
                wins=('net_pnl', lambda x: (x > 0).sum())
            ).reset_index()
            
            # Calculate Profit Factor separately
            pfs = df_thresh.groupby('symbol')['net_pnl'].apply(calc_pf).reset_index(name='profit_factor')
            symbol_stats = symbol_stats.merge(pfs, on='symbol')
            
            symbol_stats['win_rate'] = symbol_stats['wins'] / symbol_stats['trades']
            symbol_stats = symbol_stats.sort_values('total_pnl', ascending=False)
            
            # Save Batch Results
            batch_filename = f"batch_results_2025_thresh_{thresh}_{timestamp}.csv"
            symbol_stats.to_csv(RESULTS_DIR / batch_filename, index=False)
            
            # 2. Generate Daily Report
            daily_stats = df_thresh.groupby(df_thresh['date'].dt.date).agg(
                day_of_week=('date', lambda x: x.iloc[0].strftime('%A')),
                number_of_stocks_traded=('symbol', 'nunique'),
                total_trades=('symbol', 'count'),
                pnl=('net_pnl', 'sum'),
                wins=('net_pnl', lambda x: (x > 0).sum()),
                losses=('net_pnl', lambda x: (x <= 0).sum())
            ).reset_index()
            
            daily_stats['win_rate'] = daily_stats['wins'] / daily_stats['total_trades']
            daily_stats = daily_stats.sort_values('date')
            
            daily_filename = f"daily_report_2025_thresh_{thresh}_{timestamp}.csv"
            daily_stats.to_csv(RESULTS_DIR / daily_filename, index=False)
            
            print(f"Saved: {batch_filename}")
            print(f"Saved: {daily_filename}")
            
            # Calculate Aggregate Stats for Kelly
            total_trades_count = len(df_thresh)
            total_wins = df_thresh[df_thresh['net_pnl'] > 0]
            total_losses = df_thresh[df_thresh['net_pnl'] <= 0]
            
            win_rate = len(total_wins) / total_trades_count if total_trades_count > 0 else 0
            avg_win = total_wins['net_pnl'].mean() if not total_wins.empty else 0
            avg_loss = abs(total_losses['net_pnl'].mean()) if not total_losses.empty else 0
            
            payoff_ratio = avg_win / avg_loss if avg_loss > 0 else 0
            
            # Kelly Criterion: W - (1-W)/R
            kelly_pct = 0.0
            if payoff_ratio > 0:
                kelly_pct = win_rate - (1 - win_rate) / payoff_ratio
            
            summary_text = (
                f"--- Threshold {thresh} ---\n"
                f"Trades: {total_trades_count}\n"
                f"Win Rate: {win_rate:.2%}\n"
                f"Profit Factor: {symbol_stats['profit_factor'].replace([float('inf')], float('nan')).mean():.2f}\n"
                f"Avg Win: ${avg_win:.2f}\n"
                f"Avg Loss: ${avg_loss:.2f}\n"
                f"Payoff Ratio: {payoff_ratio:.2f}\n"
                f"Kelly Criterion: {kelly_pct:.2%}\n"
                f"Half Kelly: {kelly_pct/2:.2%}\n"
                f"Total PnL: ${symbol_stats['total_pnl'].sum():,.2f}\n"
                f"--------------------------\n\n"
            )
            
            print(summary_text)
            
            # Append to summary file
            with open(RESULTS_DIR / f"summary_report_2025_{timestamp}.txt", "a") as f:
                f.write(summary_text)

    else:
        print("\nNo trades generated for any symbol.")

if __name__ == "__main__":
    run_batch_2025()
