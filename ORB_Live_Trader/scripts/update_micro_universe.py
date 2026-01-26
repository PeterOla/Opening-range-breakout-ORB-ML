"""
Monthly Micro-Cap Universe Updater.

Fetches latest shares outstanding from SEC/AlphaVantage and rebuilds micro-cap universe (<50M shares).
Run monthly to keep universe current as companies issue/buyback shares.

Usage:
    python scripts/update_micro_universe.py [--av-api-key YOUR_KEY]
"""
import sys
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
import time
from typing import Optional, Dict
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

# Add prod/backend to path for SEC shares module
BACKEND_PATH = Path(__file__).parent.parent.parent / "prod" / "backend"
sys.path.insert(0, str(BACKEND_PATH))

try:
    from services.sec_shares import get_latest_shares_outstanding
    SEC_AVAILABLE = True
except ImportError:
    print("WARNING: SEC shares module not found, will use AlphaVantage only")
    SEC_AVAILABLE = False

# Paths
REFERENCE_DIR = Path(__file__).parent.parent / "data" / "reference"
UNIVERSE_FILE = REFERENCE_DIR / "universe_micro_full.parquet"
BACKUP_DIR = REFERENCE_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

# Config
AV_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
MICRO_CAP_THRESHOLD = 50_000_000  # 50M shares
AV_RATE_LIMIT_DELAY = 12.5  # Free tier: 5 calls/min = 12s delay


def log(msg: str):
    """Simple timestamped logger."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def fetch_shares_alphavantage(symbol: str, api_key: str) -> Optional[int]:
    """Fetch shares outstanding from AlphaVantage Company Overview."""
    import requests
    
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "OVERVIEW",
        "symbol": symbol,
        "apikey": api_key
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "SharesOutstanding" in data and data["SharesOutstanding"]:
            shares = int(data["SharesOutstanding"])
            return shares if shares > 0 else None
        
        return None
    except Exception as e:
        log(f"  AlphaVantage error for {symbol}: {e}")
        return None


def fetch_shares_sec(symbol: str) -> Optional[int]:
    """Fetch shares outstanding from SEC Company Facts."""
    if not SEC_AVAILABLE:
        return None
    
    try:
        shares = get_latest_shares_outstanding(symbol)
        return shares
    except Exception as e:
        log(f"  SEC error for {symbol}: {e}")
        return None


def get_current_universe() -> pd.DataFrame:
    """Load existing universe or return empty DataFrame."""
    if UNIVERSE_FILE.exists():
        return pd.read_parquet(UNIVERSE_FILE)
    else:
        log("No existing universe found - will fetch all from scratch")
        return pd.DataFrame(columns=['symbol', 'date', 'shares_outstanding'])


def get_nasdaq_nyse_tickers() -> list[str]:
    """Load full ticker list from Alpaca or fallback CSV."""
    # Try using Alpaca client if available
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        
        client = StockHistoricalDataClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY")
        )
        
        # Alpaca doesn't have a direct "all assets" endpoint in the data client
        # Fallback to CSV for now
        raise NotImplementedError("Use CSV fallback")
        
    except Exception:
        # Fallback to CSV (if exists)
        csv_path = Path(__file__).parent.parent.parent.parent / "data" / "raw" / "nasdaq_nyse_tickers.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            return df['Symbol'].dropna().unique().tolist()
        else:
            log(f"ERROR: No ticker source found at {csv_path}")
            sys.exit(1)


def update_universe(use_sec: bool = True, use_av: bool = True, force_refresh: bool = False):
    """
    Update micro-cap universe with latest shares outstanding.
    
    Args:
        use_sec: Try SEC Company Facts first (free, no rate limit)
        use_av: Fall back to AlphaVantage if SEC fails (requires API key, rate limited)
        force_refresh: Re-fetch all symbols instead of incremental update
    """
    log("=" * 80)
    log("MICRO-CAP UNIVERSE UPDATE")
    log("=" * 80)
    
    # Backup existing universe
    if UNIVERSE_FILE.exists() and not force_refresh:
        backup_path = BACKUP_DIR / f"universe_micro_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
        import shutil
        shutil.copy(UNIVERSE_FILE, backup_path)
        log(f"Backed up existing universe to {backup_path.name}")
    
    # Load current universe
    current_universe = get_current_universe()
    log(f"Current universe: {len(current_universe)} symbols")
    
    # Get full ticker list
    log("Loading full ticker list...")
    all_tickers = get_nasdaq_nyse_tickers()
    log(f"Total tickers to scan: {len(all_tickers)}")
    
    # Determine which to fetch
    if force_refresh:
        to_fetch = all_tickers
    else:
        # Fetch only new tickers + re-check existing (companies can change shares)
        existing_symbols = set(current_universe['symbol'].unique())
        new_symbols = [t for t in all_tickers if t not in existing_symbols]
        # Re-check existing every month (update date)
        to_fetch = all_tickers
        log(f"New symbols: {len(new_symbols)}, Re-checking existing: {len(existing_symbols)}")
    
    # Fetch shares for all tickers
    results = []
    fetch_date = datetime.now().date()
    
    for i, symbol in enumerate(to_fetch, 1):
        if i % 100 == 0:
            log(f"Progress: {i}/{len(to_fetch)} ({i*100/len(to_fetch):.1f}%)")
        
        shares = None
        
        # Try SEC first (free, no rate limit)
        if use_sec and SEC_AVAILABLE:
            shares = fetch_shares_sec(symbol)
            if shares:
                time.sleep(0.1)  # Be polite to SEC
        
        # Fall back to AlphaVantage
        if shares is None and use_av and AV_API_KEY:
            shares = fetch_shares_alphavantage(symbol, AV_API_KEY)
            if shares:
                time.sleep(AV_RATE_LIMIT_DELAY)  # Rate limit: 5 calls/min
        
        if shares:
            results.append({
                'symbol': symbol,
                'date': fetch_date,
                'shares_outstanding': shares
            })
    
    log(f"Successfully fetched shares for {len(results)}/{len(to_fetch)} symbols")
    
    # Filter to micro-caps only
    df_all = pd.DataFrame(results)
    df_micro = df_all[df_all['shares_outstanding'] < MICRO_CAP_THRESHOLD].copy()
    log(f"Micro-cap filter (<{MICRO_CAP_THRESHOLD/1_000_000:.0f}M shares): {len(df_micro)} symbols")
    
    # Save updated universe
    df_micro.to_parquet(UNIVERSE_FILE, index=False)
    log(f"Saved updated universe to {UNIVERSE_FILE}")
    
    # Print summary
    log("")
    log("=" * 80)
    log("UPDATE SUMMARY")
    log("=" * 80)
    log(f"Total tickers scanned: {len(to_fetch)}")
    log(f"Successful fetches: {len(results)}")
    log(f"Micro-cap symbols: {len(df_micro)}")
    log(f"Threshold: <{MICRO_CAP_THRESHOLD/1_000_000:.0f}M shares")
    log(f"Output: {UNIVERSE_FILE}")
    log("")
    
    # Show sample
    if len(df_micro) > 0:
        log("Sample (smallest caps):")
        sample = df_micro.nsmallest(10, 'shares_outstanding')
        for _, row in sample.iterrows():
            log(f"  {row['symbol']:6s}: {row['shares_outstanding']:>12,} shares ({row['shares_outstanding']/1_000_000:.1f}M)")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Update micro-cap universe with latest shares outstanding")
    parser.add_argument("--force-refresh", action="store_true", help="Re-fetch all symbols (ignores cache)")
    parser.add_argument("--no-sec", action="store_true", help="Skip SEC Company Facts (faster but less reliable)")
    parser.add_argument("--no-av", action="store_true", help="Skip AlphaVantage (no rate limits)")
    parser.add_argument("--av-api-key", type=str, help="AlphaVantage API key (overrides .env)")
    
    args = parser.parse_args()
    
    # Override API key if provided
    if args.av_api_key:
        global AV_API_KEY
        AV_API_KEY = args.av_api_key
    
    # Check dependencies
    if not args.no_sec and not SEC_AVAILABLE:
        log("WARNING: SEC module not available, will use AlphaVantage only")
    
    if not args.no_av and not AV_API_KEY:
        log("ERROR: AlphaVantage API key required (set ALPHAVANTAGE_API_KEY in .env or use --av-api-key)")
        sys.exit(1)
    
    # Run update
    update_universe(
        use_sec=not args.no_sec,
        use_av=not args.no_av,
        force_refresh=args.force_refresh
    )


if __name__ == "__main__":
    main()
