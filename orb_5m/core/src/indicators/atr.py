import pandas as pd
from pathlib import Path

DATA_DIR = Path("data/processed/daily")


def compute_atr_for_symbol(symbol: str, period: int = 14) -> pd.DataFrame:
    """Compute ATR(period) for a single symbol using its daily parquet file.

    Expects a file data/processed/daily/<SYMBOL>.parquet with columns:
    date, open, high, low, close, volume, symbol
    """
    path = DATA_DIR / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Daily data not found for {symbol}: {path}")

    df = pd.read_parquet(path)
    df = df.sort_values("date").reset_index(drop=True)

    # True range
    prev_close = df["close"].shift(1)
    high_low = df["high"] - df["low"]
    high_prev_close = (df["high"] - prev_close).abs()
    low_prev_close = (df["low"] - prev_close).abs()

    tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    df["tr"] = tr

    # ATR as rolling mean of TR
    df[f"atr_{period}"] = df["tr"].rolling(window=period, min_periods=period).mean()

    return df


def save_atr_for_symbol(symbol: str, period: int = 14) -> Path:
    """Compute ATR and overwrite the symbol's daily parquet with ATR columns added."""
    df = compute_atr_for_symbol(symbol, period=period)
    path = DATA_DIR / f"{symbol}.parquet"
    df.to_parquet(path, index=False)
    return path


if __name__ == "__main__":
    # Tiny manual test on ticker A
    out_path = save_atr_for_symbol("A", period=14)
    df = pd.read_parquet(out_path)
    print(df[["date", "high", "low", "close", "tr", "atr_14"]].head(20))
