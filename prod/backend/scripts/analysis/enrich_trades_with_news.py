import pandas as pd
import argparse
import os
from datetime import timedelta

def load_data(trades_path, news_path):
    print(f"Loading trades from {trades_path}...")
    trades = pd.read_parquet(trades_path)
    
    print(f"Loading news from {news_path}...")
    news = pd.read_parquet(news_path)
    
    return trades, news

def process_trades(trades):
    # Standardize trade date column
    # Look for common date columns
    date_cols = ['date', 'entry_date', 'trade_date', 'datetime']
    date_col = next((c for c in date_cols if c in trades.columns), None)
    
    if not date_col:
        raise ValueError(f"Could not define date column in trades. Available: {trades.columns}")
    
    print(f"Using '{date_col}' as trade date column.")
    
    # Ensure datetime64[ns] only checks the date part
    trades['join_date'] = pd.to_datetime(trades[date_col]).dt.normalize()
    
    return trades, date_col

def process_news(news):
    # News is already mapped to 'trading_date' string or datetime by the previous script
    # We should ensure it matches the join_format
    
    # 'trading_date' in processed news comes from mcal which is usually YYYY-MM-DD string or datetime
    news['join_date'] = pd.to_datetime(news['trading_date']).dt.normalize()
    
    return news

def aggregate_news(news):
    # Multiple news items per symbol-date?
    # We want to aggregate them so we don't duplicate trade rows
    
    print("Aggregating news by Symbol + Date...")
    
    # helper for unique string concatenation
    def unique_join(x):
        return ' | '.join(sorted(list(set(x.dropna().astype(str)))))
        
    news_agg = news.groupby(['symbol', 'join_date']).agg({
        'headline': unique_join,
        'summary': 'first', # extensive text, just take one or ignore
        'timestamp_et': 'min', # First news of the session
        'source': unique_join,
        'url': 'first'
    }).reset_index()
    
    news_agg['has_news'] = True
    news_agg.rename(columns={'headline': 'news_headlines', 'timestamp_et': 'news_earliest_time'}, inplace=True)
    
    return news_agg

def main():
    parser = argparse.ArgumentParser(description="Enrich trade logs with historical news data.")
    parser.add_argument("--trades", required=True, help="Path to the input trades parquet/csv file")
    parser.add_argument("--output", default="data/analysis/trades_with_news.parquet", help="Path to save enriched trades")
    parser.add_argument("--news", default="data/news/processed/news_mapped_2012_2025.parquet", help="Path to processed news")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.trades):
        print(f"Error: Trades file not found at {args.trades}")
        return

    # Load
    trades_raw, news_raw = load_data(args.trades, args.news)
    
    # Process
    trades_clean, trade_date_col = process_trades(trades_raw)
    news_clean = process_news(news_raw)
    
    # Aggregate News to 1 row per symbol-date
    news_agg = aggregate_news(news_clean)
    
    # Join
    print(f"Joining {len(trades_clean)} trades with {len(news_agg)} news days...")
    enriched = pd.merge(
        trades_clean,
        news_agg,
        how='left',
        on=['symbol', 'join_date']
    )
    
    # Fill NAs for has_news
    enriched['has_news'] = enriched['has_news'].fillna(False)
    
    # Stats
    news_count = enriched['has_news'].sum()
    print(f"Enrichment Complete.")
    print(f"Total Trades: {len(enriched)}")
    print(f"Trades with News: {news_count} ({news_count/len(enriched)*100:.1f}%)")
    
    # Save
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    enriched.drop(columns=['join_date'], inplace=True)
    enriched.to_parquet(args.output)
    print(f"Saved to {args.output}")

if __name__ == "__main__":
    main()
