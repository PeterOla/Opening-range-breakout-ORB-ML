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
    
    # Database
    DATABASE_URL: str = "sqlite:///./trading.db"
    
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse comma-separated CORS origins into list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    
    # Trading Parameters
    MAX_OPEN_POSITIONS: int = 20          # Top 20 candidates
    DAILY_LOSS_LIMIT_PCT: float = 0.05    # 5% daily loss limit
    POSITION_SIZE_PCT: float = 0.02       # Legacy - not used with new sizing
    
    # Position Sizing (Fixed Leverage)
    TRADING_CAPITAL: float = 1000.0       # Capital allocated to strategy
    FIXED_LEVERAGE: float = 2.0           # Fixed 2x leverage
    RISK_PER_TRADE_PCT: float = 0.01      # 1% risk per trade = $10 on $1000
    
    # System
    KILL_SWITCH_FILE: str = ".stop_trading"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


settings = Settings()
