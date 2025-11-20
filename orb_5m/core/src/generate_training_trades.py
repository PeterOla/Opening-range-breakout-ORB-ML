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

def generate_training_trades():
    # Configuration
    START_DATE = "2020-01-01"
    END_DATE = "2024-12-31"
    USE_ML = False # We want base trades to train the ML on
    
    # Data directory
    UNIVERSE_PATH = PROJECT_ROOT / "data" / "processed" / "universes" / "top50_rvol.parquet"
    RESULTS_DIR = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top50"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    if not UNIVERSE_PATH.exists():
        print(f"Universe file not found at {UNIVERSE_PATH}")
        return

    print("Loading Universe (Top 50 RVOL)...")
    universe_df = pd.read_parquet(UNIVERSE_PATH)
    
    # Filter for date range
    universe_df['date'] = pd.to_datetime(universe_df['date'])
    mask = (universe_df['date'] >= pd.to_datetime(START_DATE)) & (universe_df['date'] <= pd.to_datetime(END_DATE))
    universe_df = universe_df[mask].copy()
    
    # Get unique symbols and their valid dates
    symbol_dates = universe_df.groupby('symbol')['date'].apply(lambda x: set(x.dt.date)).to_dict()
    symbols = list(symbol_dates.keys())
    
    print(f"Found {len(symbols)} symbols in Top 50 Universe for {START_DATE} to {END_DATE}.")
    print("Generating base trades for ML training...")
    
    all_trades_list = []
    
    # Progress bar
    for symbol in tqdm(symbols):
        try:
            valid_dates = symbol_dates[symbol]
            
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                trades, _ = run_orb_single_symbol(
                    symbol=symbol,
                    start_date=START_DATE,
                    end_date=END_DATE,
                    use_ml=USE_ML,
                    valid_dates=valid_dates,
                    initial_equity=1000.0 # Equity doesn't matter for trade generation, just PnL
                )
            
            if not trades.empty:
                all_trades_list.append(trades)
                
        except Exception as e:
            # print(f"Error processing {symbol}: {e}")
            continue
            
    # Save combined trades
    if all_trades_list:
        full_df = pd.concat(all_trades_list, ignore_index=True)
        full_df['date'] = pd.to_datetime(full_df['date'])
        
        output_path = RESULTS_DIR / "all_trades.csv"
        full_df.to_csv(output_path, index=False)
        print(f"\nSaved {len(full_df)} trades to {output_path}")
    else:
        print("\nNo trades generated.")

if __name__ == "__main__":
    generate_training_trades()
