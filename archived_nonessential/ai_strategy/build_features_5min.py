from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FIVE_MIN_DIR = ROOT / "data" / "processed" / "5min"


def build_features_for_symbol(symbol: str) -> pd.DataFrame:
    """Load 5m data for a symbol and build basic features + 5-bar ahead label.

    Features (all on 5-minute bars):
    - ret_1: 1-bar return
    - ret_5: 5-bar return
    - ma_10, ma_50: moving averages
    - ma_ratio: ma_10 / ma_50
    - vol_ma_20: 20-bar average volume
    - rvol_20: volume / vol_ma_20

    Label:
    - ret_fwd_5: forward 5-bar return (close[t+5] / close[t] - 1)
    """
    path = FIVE_MIN_DIR / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"5m parquet not found for {symbol}: {path}")

    df = pd.read_parquet(path).copy()
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Basic returns
    df["ret_1"] = df["close"].pct_change(1)
    df["ret_5"] = df["close"].pct_change(5)

    # Moving averages on close
    df["ma_10"] = df["close"].rolling(10).mean()
    df["ma_50"] = df["close"].rolling(50).mean()
    df["ma_ratio"] = df["ma_10"] / df["ma_50"]

    # Volume-based features
    df["vol_ma_20"] = df["volume"].rolling(20).mean()
    df["rvol_20"] = df["volume"] / df["vol_ma_20"]

    # Forward 5-bar return label
    df["ret_fwd_5"] = df["close"].shift(-5) / df["close"] - 1.0

    # Drop rows with any NaNs in features or label
    feature_cols = [
        "ret_1",
        "ret_5",
        "ma_10",
        "ma_50",
        "ma_ratio",
        "vol_ma_20",
        "rvol_20",
    ]
    df = df.dropna(subset=feature_cols + ["ret_fwd_5"]).reset_index(drop=True)

    return df


def main() -> None:
    symbol = "AAPL"
    feats = build_features_for_symbol(symbol)

    print(f"Built features for {symbol}:")
    print("Rows:", len(feats))
    print("Columns:", list(feats.columns))
    print("\nSample head:")
    print(feats.head(10))


if __name__ == "__main__":
    main()
