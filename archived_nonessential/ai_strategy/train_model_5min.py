import os
import sys
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score

# Ensure project root is on sys.path so we can import our modules when run as a script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_strategy.build_features_5min import build_features_for_symbol


def main() -> None:
    symbol = "AAPL"
    df = build_features_for_symbol(symbol)

    feature_cols = ["ret_1", "ret_5", "ma_ratio", "rvol_20"]
    X = df[feature_cols]
    y = df["ret_fwd_5"]

    # Time-ordered split: oldest 80% train, newest 20% test
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=6,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)

    print(f"Trained RandomForest on {symbol} 5m data")
    print("Train size:", len(X_train), "Test size:", len(X_test))
    print("Features:", feature_cols)
    print("R^2 on test:", r2)

    # Show a small sample of predictions
    df_test = df.iloc[split_idx:].copy()
    df_test["pred"] = y_pred
    print("\nSample predictions:")
    print(df_test[["timestamp", "ret_fwd_5", "pred"]].head(10))


if __name__ == "__main__":
    main()
