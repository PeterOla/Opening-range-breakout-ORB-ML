import pandas as pd
import numpy as np
from pathlib import Path
import json
import matplotlib.pyplot as plt
import seaborn as sns

def deserialize_last_price(bars_data):
    """Extract close price from the last bar in JSON/List."""
    if isinstance(bars_data, str):
        data = json.loads(bars_data)
        if not data: return np.nan
        return data[-1]['close']
    else:
        # Assuming list of dicts or list of lists structure from fast_backtest
        # fast_backtest: columns=['datetime', 'open', 'high', 'low', 'close', 'volume']
        if not bars_data: return np.nan
        # If it's a list of lists/tuples, index 4 is close
        return bars_data[-1][4]

def analyze_news_impact():
    # Load Universe
    path = Path(r"data/backtest/orb/universe/universe_micro_small_enriched.parquet")
    print(f"Loading {path}...")
    df = pd.read_parquet(path)
    
    # Feature Engineering
    print("Calculating metrics...")
    df['gap_pct'] = ((df['or_open'] - df['prev_close']) / df['prev_close']) * 100.0
    df['atr_pct'] = (df['atr_14'] / df['prev_close']) * 100.0
    
    # We can approximate "Day Trend" by (OR_Close - OR_Open) just for speed, 
    # but OR_Close is just the 9:30-9:35 close.
    # For true "Day Return", we need the EOD close. 
    # Let's extract EOD Close from bars_json for a random sample of 10,000 to keep it fast.
    
    # Sampling for expensive parsing
    sample_size = min(20000, len(df))
    print(f"Sampling {sample_size} rows for EOD parsing...")
    df_sample = df.sample(n=sample_size, random_state=42).copy()
    
    # Parse EOD
    # Note: 'bars_json' format in universe varies (string vs object). fast_backtest handles both.
    # We will assume list-of-lists (compact) or json string.
    
    def get_eod_return(row):
        try:
            bars = row['bars_json']
            if isinstance(bars, str):
                bars = json.loads(bars)
            
            if not bars: return np.nan
            
            # Check format: dict vs list
            first_bar = bars[0]
            last_bar = bars[-1]
            
            if isinstance(first_bar, dict):
                open_price = first_bar['close'] # Approximate open with first close if needed, or match logic
                close_price = last_bar['close']
            else:
                # compact list: [dt, o, h, l, c, v]
                close_price = last_bar[4]
            
            prev = row['prev_close']
            return ((close_price - prev) / prev) * 100.0
        except:
            return np.nan

    tqdm_avail = True
    try:
        from tqdm import tqdm
        tqdm.pandas()
        df_sample['day_return'] = df_sample.progress_apply(get_eod_return, axis=1)
    except ImportError:
        print("tqdm not found, running plain apply...")
        df_sample['day_return'] = df_sample.apply(get_eod_return, axis=1)

    # ---------------------------------------------------------
    # Comparison: News vs No News
    # ---------------------------------------------------------
    print("\n" + "="*50)
    print("BASELINE STATS: News vs No News")
    print("="*50)
    
    # 1. Counts
    total = len(df)
    news_count = df['has_news'].sum()
    no_news_count = total - news_count
    print(f"Total Rows:     {total:,}")
    print(f"Has News:       {news_count:,} ({news_count/total:.1%})")
    print(f"No News:        {no_news_count:,}")
    
    # 2. RVOL (Relative Volume)
    print("\n[RVOL Analysis]")
    rvol_news = df[df['has_news']]['rvol'].mean()
    rvol_no = df[~df['has_news']]['rvol'].mean()
    print(f"Avg RVOL (News):    {rvol_news:.2f}")
    print(f"Avg RVOL (No News): {rvol_no:.2f}")
    print(f"Ratio:              {rvol_news/rvol_no:.2f}x")

    # 3. Gap %
    print("\n[Gap % Analysis]")
    gap_news = df[df['has_news']]['gap_pct'].abs().mean()
    gap_no = df[~df['has_news']]['gap_pct'].abs().mean()
    print(f"Avg Abs Gap (News):    {gap_news:.2f}%")
    print(f"Avg Abs Gap (No News): {gap_no:.2f}%")
    
    # 4. Volatility (ATR %)
    print("\n[Volatility - ATR % Analysis]")
    atr_news = df[df['has_news']]['atr_pct'].mean()
    atr_no = df[~df['has_news']]['atr_pct'].mean()
    print(f"Avg ATR % (News):    {atr_news:.2f}%")
    print(f"Avg ATR % (No News): {atr_no:.2f}%")
    
    # 5. Outcome (Day Return Stability) on Sample
    print("\n[Outcome - Day Return StdDev (Risk)]")
    ret_news = df_sample[df_sample['has_news']]['day_return'].std()
    ret_no = df_sample[~df_sample['has_news']]['day_return'].std()
    print(f"Return StdDev (News):    {ret_news:.2f}")
    print(f"Return StdDev (No News): {ret_no:.2f}")
    
    # 6. Win Rate Proxy (Close > Open for Longs)
    # We'll use the sample for this
    print("\n[Win Rate Proxy: Close > PrevClose]")
    sample_news = df_sample[df_sample['has_news']]
    sample_no = df_sample[~df_sample['has_news']]
    
    wr_news = (sample_news['day_return'] > 0).mean() * 100
    wr_no = (sample_no['day_return'] > 0).mean() * 100
    
    print(f"Green Day % (News):    {wr_news:.1f}%")
    print(f"Green Day % (No News): {wr_no:.1f}%")

if __name__ == "__main__":
    analyze_news_impact()
