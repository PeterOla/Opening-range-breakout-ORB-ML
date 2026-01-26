"""
Fetch 24h news and score sentiment with FinBERT.
Applies rolling 24H attribution (market hours → next business day).
Filters >0.90 positive sentiment threshold.

Run daily at 06:00 ET: python scripts/fetch_and_score_news.py
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from typing import Optional, List
import pandas as pd
import time as time_module
import pytz

# Add parent backend to path
BACKEND_PATH = Path(__file__).parent.parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_PATH))

from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest
import torch
from transformers import BertTokenizer, BertForSequenceClassification

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
NEWS_DIR = DATA_DIR / "news"
SENTIMENT_DIR = DATA_DIR / "sentiment"
REFERENCE_DIR = DATA_DIR / "reference"
LOG_DIR = Path(__file__).parent.parent / "logs" / "runs"

# Config
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY")
SENTIMENT_THRESHOLD = 0.90
RETENTION_DAYS = 30
BATCH_SIZE = 32

def log(message: str, level: str = "INFO"):
    """Terminal logger with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{level}] [FETCH_NEWS] {message}")
    sys.stdout.flush()

def get_micro_universe() -> List[str]:
    """Load micro-cap symbol list"""
    universe_path = REFERENCE_DIR / "universe_micro_full.parquet"
    df = pd.read_parquet(universe_path)
    symbols = df['symbol'].unique().tolist()
    log(f"Loaded {len(symbols)} micro-cap symbols")
    return symbols

def fetch_news_with_retry(
    symbols: List[str],
    start_time: datetime,
    end_time: datetime,
    max_retries: int = 3
) -> Optional[pd.DataFrame]:
    """Fetch news from Alpaca with retry logic"""

    client = NewsClient(ALPACA_KEY, ALPACA_SECRET)

    def _extract_items(news_batch):
        items = []
        if isinstance(news_batch, tuple):
            news_batch = news_batch[0]
        if hasattr(news_batch, "data"):
            data_obj = news_batch.data
            if isinstance(data_obj, dict) and "news" in data_obj:
                items = data_obj["news"]
            elif isinstance(data_obj, list):
                items = data_obj
        elif hasattr(news_batch, "news"):
            items = news_batch.news
        elif isinstance(news_batch, list):
            items = news_batch
        return items

    def _get_val(item, key):
        return item.get(key) if isinstance(item, dict) else getattr(item, key, None)

    for attempt in range(1, max_retries + 1):
        try:
            log(f"Fetching news for {len(symbols)} symbols (attempt {attempt}/{max_retries})")

            all_items = []
            batch_size = 40

            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i + batch_size]
                symbols_str = ",".join(batch)

                current_end = end_time
                while True:
                    request = NewsRequest(
                        symbols=symbols_str,
                        start=start_time,
                        end=current_end,
                        limit=50
                    )

                    news_batch = client.get_news(request)
                    items = _extract_items(news_batch)

                    if not items:
                        break

                    all_items.extend(items)

                    # Use oldest timestamp for time-based pagination
                    timestamps = [pd.to_datetime(_get_val(item, "created_at"), utc=True) for item in items]
                    timestamps = [t for t in timestamps if pd.notna(t)]
                    if not timestamps:
                        break

                    oldest_time = min(timestamps)

                    if len(items) < 50 or oldest_time <= start_time:
                        break

                    current_end = oldest_time - pd.Timedelta(microseconds=1)

                log(f"Batch {i//batch_size + 1}/{(len(symbols) + batch_size - 1)//batch_size}: fetched items")
                time_module.sleep(0.1)

            # Map news back to requested symbols only (avoid large-cap contamination)
            mapped_items = []
            for item in all_items:
                symbols_list = _get_val(item, "symbols") or []
                if not isinstance(symbols_list, list):
                    symbols_list = [str(symbols_list)]

                matched_symbols = [s for s in symbols if s in symbols_list]
                for symbol in matched_symbols:
                    mapped_items.append({
                        "symbol": symbol,
                        "timestamp": _get_val(item, "created_at"),
                        "headline": _get_val(item, "headline"),
                        "summary": _get_val(item, "summary") or "",
                        "url": _get_val(item, "url") or ""
                    })

            df = pd.DataFrame(mapped_items)
            log(f"Fetched {len(df)} news items for {df['symbol'].nunique() if len(df) > 0 else 0} symbols")
            return df

        except Exception as e:
            log(f"Fetch failed (attempt {attempt}/{max_retries}): {e}", level="ERROR")

            if attempt < max_retries:
                backoff = 5 * 60 * (2 ** (attempt - 1))  # 5min, 10min, 20min
                log(f"Retrying in {backoff}s...")
                time_module.sleep(backoff)
            else:
                log("All retries exhausted", level="ERROR")
                return None

    return None

def score_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    """Score headlines with FinBERT"""
    
    log("Loading FinBERT model...")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log(f"Using device: {device}")
    
    tokenizer = BertTokenizer.from_pretrained("ProsusAI/finbert")
    model = BertForSequenceClassification.from_pretrained("ProsusAI/finbert")
    model.to(device)
    model.eval()
    
    # Deduplicate headlines for efficiency
    unique_headlines = df['headline'].unique()
    log(f"Scoring {len(unique_headlines)} unique headlines (batch size: {BATCH_SIZE})")
    
    scores = {}
    
    with torch.no_grad():
        for i in range(0, len(unique_headlines), BATCH_SIZE):
            batch = unique_headlines[i:i + BATCH_SIZE]
            
            inputs = tokenizer(
                list(batch),
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt"
            ).to(device)
            
            outputs = model(**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
            
            # Extract positive score (index 2)
            positive_scores = probs[:, 2].cpu().numpy()
            
            for headline, score in zip(batch, positive_scores):
                scores[headline] = float(score)
            
            if (i + BATCH_SIZE) % 320 == 0:
                log(f"Scored {i + BATCH_SIZE}/{len(unique_headlines)} headlines")
    
    # Map scores back to dataframe
    df['positive_score'] = df['headline'].map(scores)
    
    log(f"Sentiment scoring complete")
    return df

def apply_rolling_24h_attribution(df: pd.DataFrame) -> pd.DataFrame:
    """Apply rolling 24H attribution logic (market hours news → next business day)"""
    
    log("Applying rolling 24H attribution logic...")
    et_tz = pytz.timezone("America/New_York")
    
    # Convert UTC to ET
    df['timestamp_et'] = df['timestamp'].dt.tz_convert(et_tz)
    df['news_date'] = df['timestamp_et'].dt.date
    df['news_time'] = df['timestamp_et'].dt.time
    
    # Attribution rule
    market_open = dt_time(9, 30)
    
    def get_trade_date(row):
        if row['news_time'] < market_open:
            # Pre-market news → trade same day
            return row['news_date']
        else:
            # Market hours/after-hours → next business day
            return (pd.to_datetime(row['news_date']) + pd.tseries.offsets.BDay(1)).date()
    
    df['trade_date'] = df.apply(get_trade_date, axis=1)
    
    log(f"Attribution complete: {df['trade_date'].nunique()} unique trade dates")
    return df

def filter_and_aggregate(df: pd.DataFrame, threshold: float = 0.90) -> pd.DataFrame:
    """Filter by sentiment threshold and aggregate by (trade_date, symbol)"""
    
    log(f"Filtering sentiment >= {threshold}")
    filtered = df[df['positive_score'] >= threshold].copy()
    log(f"After threshold: {len(filtered)} items ({len(filtered)/len(df)*100:.1f}%)")
    
    # Aggregate: take MAX score per (trade_date, symbol)
    agg_df = filtered.groupby(['trade_date', 'symbol']).agg({
        'positive_score': 'max',
        'headline': 'first',
        'timestamp': 'first'
    }).reset_index()
    
    log(f"After aggregation: {len(agg_df)} candidates for {agg_df['trade_date'].nunique()} days")
    return agg_df

def cleanup_old_files(retention_days: int = 30):
    """Delete old sentiment files"""
    cutoff_date = datetime.now().date() - timedelta(days=retention_days)
    
    for directory in [NEWS_DIR, SENTIMENT_DIR]:
        deleted_count = 0
        for file in directory.glob("*.parquet"):
            try:
                file_date = datetime.strptime(file.stem.replace("daily_", ""), "%Y-%m-%d").date()
                if file_date < cutoff_date:
                    file.unlink()
                    deleted_count += 1
            except (ValueError, OSError):
                pass
        
        if deleted_count > 0:
            log(f"Deleted {deleted_count} old files from {directory.name}")

def main():
    """Main pipeline"""
    
    # Setup
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    SENTIMENT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now().date()
    log(f"Starting news/sentiment pipeline for {today}")
    
    # Load universe
    symbols = get_micro_universe()
    
    # Fetch 24h news (rolling window)
    et_tz = pytz.timezone("America/New_York")
    end_time = datetime.now(et_tz)
    start_time = end_time - timedelta(hours=24)
    start_time = start_time.astimezone(pytz.UTC)
    end_time = end_time.astimezone(pytz.UTC)
    
    df = fetch_news_with_retry(symbols, start_time, end_time)
    
    if df is None or len(df) == 0:
        log("Failed to fetch news after all retries - ABORTING", level="ERROR")
        sys.exit(1)
    
    # Save raw news
    raw_path = NEWS_DIR / f"daily_{today}.parquet"
    df.to_parquet(raw_path, index=False)
    log(f"Saved raw news to {raw_path.name}")
    
    # Score sentiment
    df = score_sentiment(df)
    
    # Apply attribution
    df = apply_rolling_24h_attribution(df)
    
    # Filter and aggregate
    candidates = filter_and_aggregate(df, SENTIMENT_THRESHOLD)
    
    # Save sentiment candidates
    sentiment_path = SENTIMENT_DIR / f"daily_{today}.parquet"
    candidates.to_parquet(sentiment_path, index=False)
    log(f"Saved {len(candidates)} sentiment candidates to {sentiment_path.name}")
    
    # Cleanup
    cleanup_old_files(RETENTION_DAYS)
    
    log("News/sentiment pipeline completed successfully")

if __name__ == "__main__":
    main()
