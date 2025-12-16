"""
Configuration management using pydantic-settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Alpaca Configuration
    ALPACA_API_KEY: str = ""
    ALPACA_API_SECRET: str = ""
    ALPACA_PAPER: bool = True
    
    # Polygon Configuration
    POLYGON_API_KEY: str = ""

    # Alpha Vantage Configuration
    ALPHAVANTAGE_API_KEY: str = ""

    # SEC (shares outstanding / company facts)
    # SEC requires a descriptive User-Agent with contact details.
    SEC_USER_AGENT: str = ""
    
    # Database
    # Default to local Postgres for transactionals (Docker compose above). If you prefer SQLite
    # for quick single-process runs, set DATABASE_URL to sqlite:///./trading.db
    DATABASE_URL: str = "postgresql+psycopg2://orb:orb@localhost:5432/orb"  # Local Postgres default

    # DuckDB and Parquet paths (local-only setup)
    DUCKDB_PATH: str = "./data/duckdb_local.db"
    PARQUET_BASE_PATH: str = "./data/processed"
    DELTA_BASE_PATH: str = "./data/deltas"
    
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse comma-separated CORS origins into list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    
    # Strategy Selection (controls top_n, direction, risk_per_trade)
    # Options: top5_long, top10_long, top20_both, top50_both
    ORB_STRATEGY: str = "top20_both"

    # Universe selection for live scanning/execution
    # Options: all, micro, small, large, micro_small, micro_small_unknown, micro_unknown, unknown
    ORB_UNIVERSE: str = "all"

    # Execution broker
    # Options: alpaca, tradezero
    EXECUTION_BROKER: str = "alpaca"

    # TradeZero (Selenium) credentials + execution safety
    TRADEZERO_USERNAME: str = ""
    TRADEZERO_PASSWORD: str = ""
    TRADEZERO_HEADLESS: bool = False
    TRADEZERO_DRY_RUN: bool = True
    TRADEZERO_LOCATE_MAX_PPS: float = 0.05  # max $/share for short locates
    TRADEZERO_DEFAULT_EQUITY: float = 100000.0  # used if we cannot read equity from UI
    
    # Risk Management
    DAILY_LOSS_LIMIT_PCT: float = 0.10    # 10% daily loss limit (kill switch)
    
    # System
    KILL_SWITCH_FILE: str = ".stop_trading"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


settings = Settings()


# Strategy presets - all target 10% daily risk
STRATEGY_CONFIGS = {
    "top5_long": {
        "top_n": 5,
        "direction": "long",
        "risk_per_trade": 0.02,  # 2% per trade = 10% daily
        "description": "Top 5 LONG only",
    },
    "top5_both": {
        "top_n": 5,
        "direction": "both",
        "risk_per_trade": 0.02,  # 2% per trade = 10% daily
        "description": "Top 5 Long & Short",
    },
    "top10_long": {
        "top_n": 10,
        "direction": "long",
        "risk_per_trade": 0.01,  # 1% per trade = 10% daily
        "description": "Top 10 LONG only",
    },
    "top20_both": {
        "top_n": 20,
        "direction": "both",
        "risk_per_trade": 0.005,  # 0.5% per trade = 10% daily
        "description": "Top 20 Long & Short",
    },
    "top50_both": {
        "top_n": 50,
        "direction": "both",
        "risk_per_trade": 0.002,  # 0.2% per trade = 10% daily
        "description": "Top 50 Long & Short",
    },
}


def get_strategy_config() -> dict:
    """Get the active strategy configuration from ORB_STRATEGY env var."""
    strategy_name = settings.ORB_STRATEGY.lower()
    if strategy_name not in STRATEGY_CONFIGS:
        raise ValueError(
            f"Unknown strategy: {strategy_name}. "
            f"Valid options: {list(STRATEGY_CONFIGS.keys())}"
        )
    config = STRATEGY_CONFIGS[strategy_name].copy()
    config["name"] = strategy_name
    return config
