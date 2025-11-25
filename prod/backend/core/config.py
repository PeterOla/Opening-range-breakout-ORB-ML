"""
Configuration management using pydantic-settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Alpaca Configuration
    ALPACA_API_KEY: str = ""
    ALPACA_API_SECRET: str = ""
    ALPACA_PAPER: bool = True
    
    # Database
    DATABASE_URL: str = "sqlite:///./trading.db"
    
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:3001"]
    
    # Trading Parameters
    MAX_OPEN_POSITIONS: int = 5
    DAILY_LOSS_LIMIT_PCT: float = 0.05
    POSITION_SIZE_PCT: float = 0.02
    
    # System
    KILL_SWITCH_FILE: str = ".stop_trading"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


settings = Settings()
