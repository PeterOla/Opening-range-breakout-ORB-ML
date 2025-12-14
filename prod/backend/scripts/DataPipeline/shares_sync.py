"""
Shares outstanding synchronization — auto-fetch missing shares before enrichment.
"""
import logging
import json
import pandas as pd
from pathlib import Path
from typing import Tuple, List, Optional
from datetime import datetime, timedelta

from .config import DATA_RAW

logger = logging.getLogger(__name__)

IGNORE_FILE = DATA_RAW / "missing_shares_ignore.json"


def load_ignore_list() -> dict:
    if IGNORE_FILE.exists():
        try:
            with open(IGNORE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load ignore list: {e}")
    return {}


def save_ignore_list(data: dict):
    try:
        with open(IGNORE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save ignore list: {e}")


def sync_missing_shares(symbols: Optional[List[str]] = None, skip_if_recent: bool = True) -> Tuple[int, int]:
    """
    Identify and fetch shares data for symbols missing from historical_shares.parquet.
    
    Args:
        symbols: Optional list of symbols to check. If None, checks all NASDAQ/NYSE tickers.
        skip_if_recent: Skip if last sync was <24h ago (prevent redundant API calls)
    
    Returns:
        (missing_count, fetched_count) — how many symbols needed and how many fetched
    """
    
    # Load existing shares
    shares_path = DATA_RAW / "historical_shares.parquet"
    if shares_path.exists():
        existing = pd.read_parquet(shares_path)
        existing_symbols = set(existing['symbol'].dropna().unique())
        last_modified = shares_path.stat().st_mtime
    else:
        existing = pd.DataFrame()
        existing_symbols = set()
        last_modified = 0
    
    # Determine target universe
    if symbols:
        all_symbols = set(symbols)
    else:
        # Load current universe (NASDAQ + NYSE)
        tickers_path = DATA_RAW / "nasdaq_nyse_tickers.csv"
        if not tickers_path.exists():
            logger.debug("nasdaq_nyse_tickers.csv not found, skipping shares sync")
            return 0, 0
        
        tickers = pd.read_csv(tickers_path)
        all_symbols = set(tickers['symbol'].unique())
    
    # Find missing from shares file
    missing_from_file = sorted([s for s in (all_symbols - existing_symbols) if pd.notna(s)])

    # Identify stale symbols (existing but not updated in >90 days)
    stale_symbols = []
    if not existing.empty:
        try:
            # Ensure we work with datetime objects
            if not pd.api.types.is_datetime64_any_dtype(existing['date']):
                existing['date'] = pd.to_datetime(existing['date'])
            
            # Filter for symbols currently in our universe
            existing_in_universe = existing[existing['symbol'].isin(all_symbols)]
            
            if not existing_in_universe.empty:
                # Find max date per symbol
                latest_dates = existing_in_universe.groupby('symbol')['date'].max()
                cutoff_date = datetime.now() - timedelta(days=90)
                stale_symbols = latest_dates[latest_dates < cutoff_date].index.tolist()
                if stale_symbols:
                    logger.info(f"Found {len(stale_symbols)} stale symbols (last data > 90 days old)")
        except Exception as e:
            logger.warning(f"Failed to check for stale symbols: {e}")
    
    # Check which missing symbols already have shares_outstanding in their daily parquets
    from .config import DAILY_DIR
    symbols_with_local_shares = set()
    
    for symbol in missing_from_file:
        daily_path = DAILY_DIR / f"{symbol}.parquet"
        if daily_path.exists():
            try:
                df = pd.read_parquet(daily_path)
                if 'shares_outstanding' in df.columns and df['shares_outstanding'].notna().any():
                    symbols_with_local_shares.add(symbol)
                    logger.debug(f"[{symbol}] Already has shares_outstanding in daily parquet, skipping fetch")
            except Exception as e:
                logger.debug(f"[{symbol}] Error reading daily parquet: {e}")
    
    # Load ignore list
    ignore_data = load_ignore_list()
    valid_ignore = set()
    for sym, date_str in ignore_data.items():
        try:
            date_added = datetime.fromisoformat(date_str)
            # Retry after 90 days
            if (datetime.now() - date_added).days < 90:
                valid_ignore.add(sym)
        except:
            pass

    # Only fetch for symbols that don't have shares data anywhere AND are not ignored
    missing_truly = [s for s in missing_from_file if s not in symbols_with_local_shares and s not in valid_ignore]
    
    # Combine missing and stale
    symbols_to_fetch = sorted(list(set(missing_truly + stale_symbols)))
    
    if not symbols_to_fetch:
        logger.info(f"OK Shares data complete: {len(existing_symbols)} symbols (+ {len(symbols_with_local_shares)} with local shares, {len(valid_ignore)} ignored)")
        return 0, 0
    
    logger.info(f"Fetching shares for {len(symbols_to_fetch)} symbols ({len(missing_truly)} missing, {len(stale_symbols)} stale)")
    logger.info("Source: SEC Company Facts (free). Uses polite sleeps + local caching.")
    
    # Import fetch function (lazy import to avoid circular dependency)
    try:
        from scripts.fetch_historical_shares import fetch_shares_for_symbols
    except ImportError:
        logger.error("fetch_historical_shares module not found")
        return len(symbols_to_fetch), 0
    
    # Fetch new shares
    logger.info(f"Fetching shares for {len(symbols_to_fetch)} symbols...")
    try:
        new_shares = fetch_shares_for_symbols(symbols_to_fetch)
    except Exception as e:
        logger.error(f"Shares fetch failed: {e}")
        return len(symbols_to_fetch), 0
    
    # Update ignore list for symbols that returned no data
    # Only add to ignore list if they were in the 'missing_truly' list (never had data)
    fetched_symbols = set(new_shares['symbol'].unique()) if not new_shares.empty else set()
    
    failed_missing = set(missing_truly) - fetched_symbols
    
    if failed_missing:
        today = datetime.now().isoformat()
        for s in failed_missing:
            ignore_data[s] = today
        save_ignore_list(ignore_data)
        logger.info(f"Added {len(failed_missing)} symbols to ignore list (no shares data found)")

    if new_shares.empty:
        logger.warning("No shares data returned from fetch")
        return len(symbols_to_fetch), 0
    
    fetched_count = new_shares['symbol'].nunique()
    logger.info(f"OK Fetched shares for {fetched_count} symbols ({len(new_shares)} records)")
    
    # Combine and save
    if new_shares.empty:
        logger.warning("No new shares data fetched")
        return len(symbols_to_fetch), 0
    
    # Ensure date consistency
    if 'date' in new_shares.columns:
        new_shares['date'] = pd.to_datetime(new_shares['date'])
    
    if existing.empty:
        combined = new_shares
    else:
        # existing['date'] was already converted to datetime above
        combined = pd.concat([existing, new_shares], ignore_index=True)
    
    combined = combined.drop_duplicates(subset=['symbol', 'date'], keep='last')
    combined = combined.sort_values(['symbol', 'date']).reset_index(drop=True)
    
    combined.to_parquet(shares_path, compression='snappy', index=False)
    logger.info(f"OK Updated historical_shares.parquet: {len(combined)} total records")
    
    return len(symbols_to_fetch), fetched_count
