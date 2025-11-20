import pandas as pd
from pathlib import Path
from tqdm import tqdm
import sys

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.indicators.relative_volume import compute_or_rvol_for_symbol

def generate_universe():
    FIVEMIN_DIR = PROJECT_ROOT / "data" / "processed" / "5min"
    OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "universes"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    files = list(FIVEMIN_DIR.glob("*.parquet"))
    all_rvol = []
    
    print(f"Scanning {len(files)} symbols for RVOL...")
    
    for f in tqdm(files):
        symbol = f.stem
        try:
            # Calculate RVOL
            # Note: This reads the 5min file. It's IO intensive but we only do it once.
            df = compute_or_rvol_for_symbol(symbol, period=14)
            
            # Filter for 2024-2025 to keep size manageable if needed, 
            # but user might want history. Let's keep all.
            # Keep only needed columns to save memory
            df = df[['date', 'symbol', 'or_rvol_14']].dropna()
            
            # Optimization: Don't store low RVOLs that have no chance of being in top 20
            # If RVOL < 1.0, it's unlikely to be in top 20 of thousands of stocks?
            # Maybe safe to filter < 0.5, but let's be safe and keep > 1.0 if we want to be strict,
            # or just keep all. Memory might be an issue with 5000 symbols * 1000 days.
            # 5M rows is fine for pandas.
            
            all_rvol.append(df)
        except Exception as e:
            # print(f"Error {symbol}: {e}")
            continue
            
    if not all_rvol:
        print("No data found.")
        return

    print("Concatenating data...")
    full_df = pd.concat(all_rvol, ignore_index=True)
    
    print("Selecting Top 20 per day...")
    # Group by date, sort by rvol desc, take top 20
    top20 = (
        full_df
        .sort_values(['date', 'or_rvol_14'], ascending=[True, False])
        .groupby('date')
        .head(20)
    )
    
    output_path = OUTPUT_DIR / "top20_rvol.parquet"
    top20.to_parquet(output_path)
    print(f"Saved universe to {output_path}")

    print("Selecting Top 50 per day...")
    top50 = (
        full_df
        .sort_values(['date', 'or_rvol_14'], ascending=[True, False])
        .groupby('date')
        .head(50)
    )
    
    output_path_50 = OUTPUT_DIR / "top50_rvol.parquet"
    top50.to_parquet(output_path_50)
    print(f"Saved universe to {output_path_50}")
    
    # Stats
    print(f"Total Universe Rows (Top 20): {len(top20)}")
    print(f"Total Universe Rows (Top 50): {len(top50)}")
    print(f"Unique Symbols (Top 50): {top50['symbol'].nunique()}")

if __name__ == "__main__":
    generate_universe()
