"""
Centralized configuration for ORB data pipeline.
"""
import os
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv

# Load .env file from backend directory
env_file = Path(__file__).resolve().parents[2] / ".env"
if env_file.exists():
    load_dotenv(env_file)

# ===== PATHS =====
REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = REPO_ROOT / "data"
DATA_RAW = DATA_ROOT / "raw"
DATA_PROCESSED = DATA_ROOT / "processed"
DATA_DELTAS = DATA_ROOT / "deltas"
BACKTEST_DIR = DATA_ROOT / "backtest"

DAILY_DIR = DATA_PROCESSED / "daily"
FIVE_MIN_DIR = DATA_PROCESSED / "5min"
UNIVERSES_DIR = DATA_PROCESSED / "universes"

# Ensure directories exist
for path in [DATA_RAW, DAILY_DIR, FIVE_MIN_DIR, DATA_DELTAS, UNIVERSES_DIR, BACKTEST_DIR]:
    path.mkdir(parents=True, exist_ok=True)

# ===== API CREDENTIALS =====
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_API_SECRET", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://api.alpaca.markets")

# ===== DATABASE =====
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///orb.db")

# ===== FETCH SETTINGS =====
FETCH_CONFIG = {
    "symbols_per_batch": 100,  # Parallel batch size (premium Alpaca, no rate limits)
    "lookback_days": 14,  # How many days back to fetch/update
    "max_retries": 3,
    "retry_delay_seconds": 5,
    "timeout_seconds": 30,
    "start_date": "2021-01-01",  # Full historical backfill
}

# ===== ENRICHMENT SETTINGS =====
ENRICHMENT_CONFIG = {
    "atr_period": 14,  # ATR(14) for mean true range
    "volume_period": 14,  # 14-day average volume
    "min_price": 5.0,  # Minimum price filter
    "min_atr": 0.50,  # Minimum ATR filter
    "min_volume": 1_000_000,  # Minimum daily volume
}

# ===== VALIDATION SETTINGS =====
VALIDATION_CONFIG = {
    "required_daily_columns": ["date", "open", "high", "low", "close", "volume"],
    "required_5min_columns": ["datetime", "open", "high", "low", "close", "volume"],
    "min_file_size_bytes": 1000,  # Minimum parquet file size
    "max_file_size_bytes": 100_000_000,  # Maximum parquet file size (100MB)
    "check_date_continuity": True,  # Warn if dates not consecutive
    "allow_missing_dates": ["weekends", "holidays"],  # Skip these in continuity checks
}

# ===== SHARES DATA =====
SHARES_CONFIG = {
    "raw_file": DATA_RAW / "historical_shares.parquet",
    "forward_fill_days": 365,  # Forward-fill shares data up to 1 year
}

# ===== LOGGING =====
LOGGING_CONFIG = {
    "log_dir": REPO_ROOT / "logs",
    "log_level": "INFO",
    "log_format": "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    "log_file": "orb_sync_{timestamp}.log",
}
LOGGING_CONFIG["log_dir"].mkdir(parents=True, exist_ok=True)

# ===== FILTER THRESHOLDS (for daily_metrics_historical) =====
FILTER_THRESHOLDS = {
    "price_min": 5.0,
    "price_max": 9999.99,
    "atr_min": 0.50,
    "volume_min": 1_000_000,
}

# ===== STRATEGY PRESETS =====
STRATEGY_PRESETS = {
    "orb_top5_long": {"top_n": 5, "atr_threshold": 0.50},
    "orb_top10_long": {"top_n": 10, "atr_threshold": 0.50},
    "orb_top20_both": {"top_n": 20, "atr_threshold": 0.50},
    "orb_top50_both": {"top_n": 50, "atr_threshold": 0.50},
    "rc_bull_flags": {"gap_min": 0.02, "rvol_min": 5.0, "float_max_millions": 10},
}

# ===== FEATURE FLAGS =====
FEATURES = {
    "parallel_fetch": True,  # Use parallel fetching for Alpaca
    "incremental_build": True,  # Only fetch new data since last run
    "validate_on_write": True,  # Validate before writing parquets
    "update_database": True,  # Sync to PostgreSQL/SQLite
    "auto_build_universes": False,  # Auto-trigger ORB/RC universe builds after sync
}

# ===== UTILITY FUNCTIONS =====
def get_symbol_daily_path(symbol: str) -> Path:
    """Get path to daily parquet file for a symbol."""
    return DAILY_DIR / f"{symbol}.parquet"

def get_symbol_5min_path(symbol: str) -> Path:
    """Get path to 5-min parquet file for a symbol."""
    return FIVE_MIN_DIR / f"{symbol}.parquet"

def get_all_symbols() -> List[str]:
    """Load list of all symbols to sync."""
    daily_files = list(DAILY_DIR.glob("*.parquet"))
    return sorted([f.stem.upper() for f in daily_files])

if __name__ == "__main__":
    print("ORB Data Pipeline Configuration")
    print(f"Repo Root: {REPO_ROOT}")
    print(f"Data Root: {DATA_ROOT}")
    print(f"Daily Dir: {DAILY_DIR}")
    print(f"5-Min Dir: {FIVE_MIN_DIR}")
    print(f"Symbols to sync: {len(get_all_symbols())}")
    print(f"Features: {FEATURES}")
