import pandas as pd
from pathlib import Path

DATA_DIR_5M = Path("data/processed/5min")


def compute_opening_range_for_symbol(symbol: str) -> pd.DataFrame:
    """Extract the first 5-minute bar (9:30-9:35 ET) for each trading day.

    Expects data/processed/5min/<SYMBOL>.parquet with columns:
    timestamp (tz-aware, America/New_York), open, high, low, close, volume, symbol
    """
    path = DATA_DIR_5M / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"5-min data not found for {symbol}: {path}")

    df = pd.read_parquet(path)
    # Ensure timestamp is datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Filter to 9:30 bar only
    df["date"] = df["timestamp"].dt.date
    df["time"] = df["timestamp"].dt.time

    opening = df[df["timestamp"].dt.hour.eq(9) & df["timestamp"].dt.minute.eq(30)].copy()

    opening.rename(
        columns={
            "open": "or_open",
            "high": "or_high",
            "low": "or_low",
            "close": "or_close",
            "volume": "or_volume",
        },
        inplace=True,
    )

    # Direction: +1 if close > open, -1 if close < open, 0 if equal
    opening["or_direction"] = 0
    opening.loc[opening["or_close"] > opening["or_open"], "or_direction"] = 1
    opening.loc[opening["or_close"] < opening["or_open"], "or_direction"] = -1

    # Keep only relevant columns
    opening = opening[[
        "date",
        "timestamp",
        "symbol",
        "or_open",
        "or_high",
        "or_low",
        "or_close",
        "or_volume",
        "or_direction",
    ]].reset_index(drop=True)

    return opening


if __name__ == "__main__":
    # Tiny manual test on ticker A
    or_df = compute_opening_range_for_symbol("A")
    print(or_df.head(10))
