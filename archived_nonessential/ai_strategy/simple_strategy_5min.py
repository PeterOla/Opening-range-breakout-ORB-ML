import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_strategy.build_features_5min import build_features_for_symbol


FEATURE_COLS = ["ret_1", "ret_5", "ma_ratio", "rvol_20"]


def train_model(df: pd.DataFrame) -> RandomForestRegressor:
    """Train the same RandomForest as in train_model_5min.py and return it.

    We keep this self-contained for now (no model persistence yet).
    """
    X = df[FEATURE_COLS]
    y = df["ret_fwd_5"]

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

    return model, X_test.index


def build_strategy(df: pd.DataFrame, model: RandomForestRegressor, test_idx: pd.Index) -> pd.DataFrame:
    """Create a simple long-only strategy on the test period.

    Rule (very naive):
    - Compute predicted ret_fwd_5 on the test set.
    - Go long (signal=1) when prediction is in the top quantile; flat otherwise.
    """
    X = df.loc[test_idx, FEATURE_COLS]
    preds = model.predict(X)

    df_strat = df.loc[test_idx].copy()
    df_strat["pred"] = preds

    # Threshold: top 10% of predicted returns
    thresh = np.quantile(preds, 0.9)
    df_strat["signal"] = (df_strat["pred"] >= thresh).astype(int)

    # Strategy return: signal * actual forward 5-bar return
    df_strat["strategy_ret"] = df_strat["signal"] * df_strat["ret_fwd_5"]

    # Equity curve assuming 1 unit of capital
    df_strat["equity"] = (1.0 + df_strat["strategy_ret"]).cumprod()

    return df_strat


def main() -> None:
    symbol = "AAPL"
    df = build_features_for_symbol(symbol)

    model, test_idx = train_model(df)
    df_strat = build_strategy(df, model, test_idx)

    total_ret = df_strat["equity"].iloc[-1] - 1.0
    num_trades = int(df_strat["signal"].sum())

    print(f"Simple 5m strategy on {symbol}")
    print("Rows in test period:", len(df_strat))
    print("Number of bars with position (signal=1):", num_trades)
    print("Total return over test period: {:.2%}".format(total_ret))
    print("\nSample of strategy output:")
    print(df_strat[["timestamp", "ret_fwd_5", "pred", "signal", "strategy_ret", "equity"]].head(15))


if __name__ == "__main__":
    main()
