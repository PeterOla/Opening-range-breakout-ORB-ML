"""
Run Live Pipeline for Historical Date

Runs the full live pipeline for a given date and saves results.
This is completely independent - no backtest files needed.

Usage:
    python run_for_date.py --date 2021-02-22

Output saved to: ORB_Live_Trader/data/test_runs/{date}/
"""
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
import pandas as pd
import pytz
import json

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
TEST_RUNS_DIR = DATA_DIR / "test_runs"
REFERENCE_DIR = DATA_DIR / "reference"

# Config (matches backtest)
SENTIMENT_THRESHOLD = 0.90
ATR_MIN = 0.5
VOLUME_MIN = 100_000
TOP_N = 5


def log(msg: str, level: str = "INFO"):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {msg}", flush=True)


def get_micro_universe() -> list:
    """Load micro-cap symbol list."""
    universe_path = REFERENCE_DIR / "universe_micro_full.parquet"
    df = pd.read_parquet(universe_path)
    return df['symbol'].unique().tolist()


def fetch_news_for_date(trade_date, symbols: list) -> pd.DataFrame:
    """Fetch news for the 24h window ending at 09:30 on trade_date."""
    from alpaca.data.historical.news import NewsClient
    
    log(f"Fetching news for {trade_date}...")
    
    client = NewsClient(
        os.getenv("ALPACA_API_KEY"),
        os.getenv("ALPACA_SECRET_KEY")
    )
    
    et_tz = pytz.timezone("America/New_York")
    
    # Build 09:30→09:30 window (matches backtest)
    today_0930 = et_tz.localize(datetime.combine(trade_date, dt_time(9, 30)))
    yesterday = trade_date - timedelta(days=1)
    yesterday_0930 = et_tz.localize(datetime.combine(yesterday, dt_time(9, 30)))
    
    start_time = yesterday_0930.astimezone(pytz.UTC)
    end_time = today_0930.astimezone(pytz.UTC)
    
    log(f"  Window: {yesterday_0930.strftime('%Y-%m-%d %H:%M')} → {today_0930.strftime('%Y-%m-%d %H:%M')} ET")
    
    from alpaca.data.requests import NewsRequest
    
    all_items = []
    batch_size = 40
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        symbols_str = ",".join(batch)
        
        try:
            request = NewsRequest(
                symbols=symbols_str,
                start=start_time,
                end=end_time,
                limit=50
            )
            
            news_batch = client.get_news(request)
            
            # Extract items
            items = []
            if hasattr(news_batch, "news"):
                items = news_batch.news
            elif hasattr(news_batch, "data"):
                data_obj = news_batch.data
                if isinstance(data_obj, dict) and "news" in data_obj:
                    items = data_obj["news"]
                elif isinstance(data_obj, list):
                    items = data_obj
            
            # Map to requested symbols only
            for item in items:
                item_symbols = getattr(item, "symbols", []) if hasattr(item, "symbols") else item.get("symbols", [])
                matched = [s for s in batch if s in item_symbols]
                
                for symbol in matched:
                    all_items.append({
                        "symbol": symbol,
                        "timestamp": getattr(item, "created_at", None) or item.get("created_at"),
                        "headline": getattr(item, "headline", None) or item.get("headline", ""),
                    })
                    
        except Exception as e:
            log(f"  Batch {i//batch_size + 1} failed: {e}", level="WARN")
    
    df = pd.DataFrame(all_items)
    log(f"  Fetched {len(df)} news items")
    return df


def score_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    """Score headlines with FinBERT."""
    import torch
    from transformers import BertTokenizer, BertForSequenceClassification
    
    log("Scoring sentiment with FinBERT...")
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = BertTokenizer.from_pretrained("ProsusAI/finbert")
    model = BertForSequenceClassification.from_pretrained("ProsusAI/finbert")
    model.to(device)
    model.eval()
    
    unique_headlines = df['headline'].unique()
    scores = {}
    
    with torch.no_grad():
        for i in range(0, len(unique_headlines), 32):
            batch = unique_headlines[i:i + 32]
            inputs = tokenizer(list(batch), padding=True, truncation=True, max_length=512, return_tensors="pt").to(device)
            outputs = model(**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
            positive_scores = probs[:, 2].cpu().numpy()
            
            for headline, score in zip(batch, positive_scores):
                scores[headline] = float(score)
    
    df['positive_score'] = df['headline'].map(scores)
    log(f"  Scored {len(unique_headlines)} headlines")
    return df


def apply_attribution(df: pd.DataFrame) -> pd.DataFrame:
    """Apply rolling 24H attribution (matches backtest exactly)."""
    log("Applying attribution...")
    
    et_tz = pytz.timezone("America/New_York")
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df['timestamp_et'] = df['timestamp'].dt.tz_convert(et_tz)
    df['news_date'] = df['timestamp_et'].dt.date
    df['news_time'] = df['timestamp_et'].dt.time
    
    market_open = dt_time(9, 30)
    
    def get_trade_date(row):
        if row['news_time'] < market_open:
            return row['news_date']
        else:
            return (pd.to_datetime(row['news_date']) + pd.tseries.offsets.BDay(1)).date()
    
    df['trade_date'] = df.apply(get_trade_date, axis=1)
    return df


def filter_and_aggregate(df: pd.DataFrame, trade_date) -> pd.DataFrame:
    """Filter by threshold and aggregate."""
    log(f"Filtering threshold > {SENTIMENT_THRESHOLD}...")
    
    filtered = df[
        (df['trade_date'] == trade_date) &
        (df['positive_score'] > SENTIMENT_THRESHOLD)
    ].copy()
    
    log(f"  {len(filtered)} items above threshold")
    
    # Aggregate by symbol (max score)
    if len(filtered) > 0:
        agg = filtered.groupby('symbol').agg({
            'positive_score': 'max',
            'headline': 'first'
        }).reset_index()
    else:
        agg = pd.DataFrame(columns=['symbol', 'positive_score', 'headline'])
    
    log(f"  {len(agg)} unique symbols")
    return agg


def fetch_daily_bars(trade_date, symbols: list) -> pd.DataFrame:
    """Fetch daily bars and calculate ATR/volume."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    
    log("Fetching daily bars...")
    
    client = StockHistoricalDataClient(
        os.getenv("ALPACA_API_KEY"),
        os.getenv("ALPACA_SECRET_KEY")
    )
    
    start_date = trade_date - timedelta(days=30)
    end_date = trade_date + timedelta(days=1)
    
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start_date,
        end=end_date
    )
    
    bars = client.get_stock_bars(request)
    df = bars.df.reset_index()
    
    # Calculate ATR and avg volume per symbol
    result = []
    for symbol in df['symbol'].unique():
        sym_df = df[df['symbol'] == symbol].sort_values('timestamp')
        
        # True Range
        sym_df['h_l'] = sym_df['high'] - sym_df['low']
        sym_df['h_pc'] = abs(sym_df['high'] - sym_df['close'].shift(1))
        sym_df['l_pc'] = abs(sym_df['low'] - sym_df['close'].shift(1))
        sym_df['tr'] = sym_df[['h_l', 'h_pc', 'l_pc']].max(axis=1)
        sym_df['atr_14'] = sym_df['tr'].rolling(14, min_periods=1).mean()
        sym_df['avg_volume_14'] = sym_df['volume'].rolling(14, min_periods=1).mean()
        
        sym_df['date'] = pd.to_datetime(sym_df['timestamp']).dt.date
        latest = sym_df[sym_df['date'] == trade_date]
        
        if len(latest) > 0:
            result.append({
                'symbol': symbol,
                'atr_14': latest.iloc[0]['atr_14'],
                'avg_volume_14': latest.iloc[0]['avg_volume_14']
            })
    
    result_df = pd.DataFrame(result)
    log(f"  Got metrics for {len(result_df)} symbols")
    return result_df


def fetch_5min_bars(trade_date, symbols: list) -> dict:
    """Fetch 5-min bars for OR calculation."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    
    log("Fetching 5-min bars...")
    
    client = StockHistoricalDataClient(
        os.getenv("ALPACA_API_KEY"),
        os.getenv("ALPACA_SECRET_KEY")
    )
    
    et = pytz.timezone("America/New_York")
    start_dt = et.localize(datetime.combine(trade_date, dt_time(9, 30)))
    end_dt = et.localize(datetime.combine(trade_date, dt_time(16, 0)))
    
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
                bars_dict[symbol] = bars.df.reset_index()
        except:
            pass
    
    log(f"  Got 5-min bars for {len(bars_dict)}/{len(symbols)} symbols")
    return bars_dict


def calculate_or_and_rvol(bars_dict: dict, daily_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Opening Range and RVOL."""
    log("Calculating OR and RVOL...")
    
    results = []
    
    for _, row in daily_df.iterrows():
        symbol = row['symbol']
        
        if symbol not in bars_dict:
            continue
        
        df = bars_dict[symbol]
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df['timestamp_et'] = df['timestamp'].dt.tz_convert('America/New_York')
        df['time'] = df['timestamp_et'].dt.time
        
        # First 09:30 bar
        or_target = dt_time(9, 30)
        or_row = df[df['time'] == or_target]
        
        if or_row.empty:
            # Fallback to first bar
            or_row = df.iloc[0:1]
        
        if or_row.empty:
            continue
        
        r = or_row.iloc[0]
        or_open = float(r['open'])
        or_high = float(r['high'])
        or_low = float(r['low'])
        or_close = float(r['close'])
        or_volume = float(r['volume'])
        
        # Direction
        direction = 1 if or_close > or_open else (-1 if or_close < or_open else 0)
        
        # RVOL
        avg_vol = row['avg_volume_14']
        rvol = (or_volume * 78) / avg_vol if avg_vol > 0 else 0
        
        results.append({
            'symbol': symbol,
            'or_open': or_open,
            'or_high': or_high,
            'or_low': or_low,
            'or_close': or_close,
            'or_volume': or_volume,
            'direction': direction,
            'rvol': rvol,
            'atr_14': row['atr_14'],
            'avg_volume_14': avg_vol
        })
    
    result_df = pd.DataFrame(results)
    log(f"  Calculated OR for {len(result_df)} symbols")
    return result_df


def apply_filters_and_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Apply filters and select Top N by RVOL."""
    log("Applying filters and ranking...")
    
    # Filters
    filtered = df[
        (df['atr_14'] >= ATR_MIN) &
        (df['avg_volume_14'] >= VOLUME_MIN) &
        (df['direction'] == 1)
    ].copy()
    
    log(f"  {len(filtered)} passed filters (ATR>={ATR_MIN}, Vol>={VOLUME_MIN}, Long)")
    
    # Rank by RVOL
    ranked = filtered.sort_values('rvol', ascending=False).head(TOP_N)
    
    log(f"  Top {len(ranked)} by RVOL:")
    for _, row in ranked.iterrows():
        log(f"    {row['symbol']}: RVOL={row['rvol']:.2f}")
    
    return ranked


def save_results(trade_date, news_df, sentiment_df, final_df, output_dir: Path):
    """Save all results."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save news
    if len(news_df) > 0:
        news_df.to_parquet(output_dir / "news.parquet", index=False)
    
    # Save sentiment candidates
    if len(sentiment_df) > 0:
        sentiment_df.to_parquet(output_dir / "sentiment_candidates.parquet", index=False)
    
    # Save final universe
    if len(final_df) > 0:
        final_df.to_parquet(output_dir / "final_universe.parquet", index=False)
    
    # Save summary JSON
    summary = {
        "date": str(trade_date),
        "news_count": len(news_df),
        "sentiment_candidates": len(sentiment_df),
        "final_symbols": final_df['symbol'].tolist() if len(final_df) > 0 else [],
        "config": {
            "sentiment_threshold": SENTIMENT_THRESHOLD,
            "atr_min": ATR_MIN,
            "volume_min": VOLUME_MIN,
            "top_n": TOP_N
        }
    }
    
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    log(f"Results saved to {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Run live pipeline for historical date")
    parser.add_argument("--date", type=str, required=True, help="Date to run (YYYY-MM-DD)")
    args = parser.parse_args()
    
    trade_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    output_dir = TEST_RUNS_DIR / args.date
    
    log("=" * 60)
    log(f"RUNNING LIVE PIPELINE FOR {trade_date}")
    log("=" * 60)
    
    # 1. Get universe
    symbols = get_micro_universe()
    log(f"Universe: {len(symbols)} symbols")
    
    # 2. Fetch news
    news_df = fetch_news_for_date(trade_date, symbols)
    
    if len(news_df) == 0:
        log("No news found - exiting")
        save_results(trade_date, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), output_dir)
        return
    
    # 3. Score sentiment
    news_df = score_sentiment(news_df)
    
    # 4. Apply attribution
    news_df = apply_attribution(news_df)
    
    # 5. Filter and aggregate
    sentiment_df = filter_and_aggregate(news_df, trade_date)
    
    if len(sentiment_df) == 0:
        log("No sentiment candidates - exiting")
        save_results(trade_date, news_df, pd.DataFrame(), pd.DataFrame(), output_dir)
        return
    
    # 6. Fetch daily bars
    daily_df = fetch_daily_bars(trade_date, sentiment_df['symbol'].tolist())
    
    # 7. Join
    merged = sentiment_df.merge(daily_df, on='symbol', how='inner')
    
    # 8. Fetch 5-min bars
    bars_dict = fetch_5min_bars(trade_date, merged['symbol'].tolist())
    
    # 9. Calculate OR and RVOL
    or_df = calculate_or_and_rvol(bars_dict, merged)
    
    # 10. Apply filters and rank
    final_df = apply_filters_and_rank(or_df)
    
    # 11. Save
    save_results(trade_date, news_df, sentiment_df, final_df, output_dir)
    
    log("=" * 60)
    log(f"FINAL TOP {TOP_N}: {final_df['symbol'].tolist()}")
    log("=" * 60)


if __name__ == "__main__":
    main()
