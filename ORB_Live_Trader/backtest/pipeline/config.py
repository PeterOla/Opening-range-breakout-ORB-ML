"""
Configuration for ORB Live Trader backtest data pipeline.
Self-contained - no dependencies on prod/backend.
"""
import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Load .env from ORB_Live_Trader/config/.env
BACKTEST_DIR = Path(__file__).resolve().parent.parent  # ORB_Live_Trader/backtest
ORB_LIVE_TRADER_DIR = BACKTEST_DIR.parent  # ORB_Live_Trader
REPO_ROOT = ORB_LIVE_TRADER_DIR.parent  # Opening Range Breakout (ORB)

# Load environment variables
# Try prod/backend/.env first (has Alpaca credentials), then ORB_Live_Trader/config/.env
prod_env = REPO_ROOT / "prod" / "backend" / ".env"
if prod_env.exists():
    load_dotenv(prod_env)

env_file = ORB_LIVE_TRADER_DIR / "config" / ".env"
if env_file.exists():
    load_dotenv(env_file, override=False)  # Don't override existing values

# ===== PATHS =====
# Data directories (shared with main project)
DATA_ROOT = REPO_ROOT / "data"
DATA_RAW = DATA_ROOT / "raw"
DATA_PROCESSED = DATA_ROOT / "processed"

DAILY_DIR = DATA_PROCESSED / "daily"
FIVE_MIN_DIR = DATA_PROCESSED / "5min"

# Backtest-specific directories (inside ORB_Live_Trader)
BACKTEST_DATA_DIR = BACKTEST_DIR / "data"
BACKTEST_UNIVERSE_DIR = BACKTEST_DATA_DIR / "universe"
BACKTEST_RUNS_DIR = BACKTEST_DATA_DIR / "runs"

# Ensure directories exist
for path in [DATA_RAW, DAILY_DIR, FIVE_MIN_DIR, BACKTEST_DATA_DIR, BACKTEST_UNIVERSE_DIR, BACKTEST_RUNS_DIR]:
    path.mkdir(parents=True, exist_ok=True)

# ===== API CREDENTIALS =====
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_API_SECRET", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://api.alpaca.markets")

# ===== FETCH SETTINGS =====
FETCH_CONFIG = {
    "symbols_per_batch": 100,
    "lookback_days": 14,
    "max_retries": 3,
    "retry_delay_seconds": 5,
    "timeout_seconds": 30,
    "start_date": "2021-01-01",
}

# ===== ENRICHMENT SETTINGS =====
ENRICHMENT_CONFIG = {
    "atr_period": 14,
    "volume_period": 14,
    "min_price": 5.0,
    "min_atr": 0.50,
    "min_volume": 1_000_000,
}

# ===== VALIDATION SETTINGS =====
VALIDATION_CONFIG = {
    "required_daily_columns": ["date", "open", "high", "low", "close", "volume"],
    "required_5min_columns": ["datetime", "open", "high", "low", "close", "volume"],
    "min_file_size_bytes": 1000,
    "max_file_size_bytes": 100_000_000,
}

# ===== SHARES DATA =====
SHARES_CONFIG = {
    "raw_file": DATA_RAW / "historical_shares.parquet",
    "forward_fill_days": 365,
}

# ===== FILTER THRESHOLDS =====
FILTER_THRESHOLDS = {
    "price_min": 5.0,
    "price_max": 9999.99,
    "atr_min": 0.50,
    "volume_min": 1_000_000,
}

# ===== UTILITY FUNCTIONS =====
def get_symbol_daily_path(symbol: str) -> Path:
    """Get path to daily parquet file for a symbol."""
    return DAILY_DIR / f"{symbol}.parquet"

def get_symbol_5min_path(symbol: str) -> Path:
    """Get path to 5-min parquet file for a symbol."""
    return FIVE_MIN_DIR / f"{symbol}.parquet"

def get_all_symbols() -> List[str]:
    """Load list of all symbols from daily directory."""
    daily_files = list(DAILY_DIR.glob("*.parquet"))
    return sorted([f.stem.upper() for f in daily_files])

if __name__ == "__main__":
    print("ORB Backtest Pipeline Configuration")
    print(f"Repo Root: {REPO_ROOT}")
    print(f"Daily Dir: {DAILY_DIR}")
    print(f"5-Min Dir: {FIVE_MIN_DIR}")
    print(f"Backtest Data Dir: {BACKTEST_DATA_DIR}")
    print(f"Symbols available: {len(get_all_symbols())}")
    print(f"Alpaca API Key: {'*' * 8 if ALPACA_API_KEY else 'NOT SET'}")
