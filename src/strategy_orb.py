import pandas as pd
from pathlib import Path
from typing import Tuple

from src.data.features import build_daily_features

FIVEMIN_DIR = Path("data/processed/5min")


def _load_5min(symbol: str) -> pd.DataFrame:
    path = FIVEMIN_DIR / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing 5min data for {symbol}: {path}")

    df = pd.read_parquet(path)
    # Expect columns: timestamp, open, high, low, close, volume
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    # Convert to US/Eastern and add date/time columns
    df["ts_et"] = df["timestamp"].dt.tz_convert("America/New_York")
    df["date"] = df["ts_et"].dt.date
    df["time"] = df["ts_et"].dt.time
    return df


def run_orb_single_symbol(
    symbol: str,
    start_date: str,
    end_date: str,
    atr_period: int = 14,
    rvol_period: int = 14,
    rvol_threshold: float = 1.0,
    atr_stop_pct: float = 0.10,
    initial_equity: float = 100_000.0,
    risk_per_trade_frac: float = 0.01,
    commission_per_share: float = 0.0035,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Run a simple ORB strategy for one symbol.

    Rules (per day):
      - Use daily features from build_daily_features (ATR, OR, RVOL).
      - Require or_rvol >= rvol_threshold.
      - Long if or_direction == +1: entry stop at or_high.
      - Short if or_direction == -1: entry stop at or_low.
      - No trade if or_direction == 0 or missing.
      - Stop distance = atr_stop_pct * ATR (uses atr_<atr_period>).
      - Exit at stop hit or at final bar of the day (EOD).

        Returns (trades, daily_pnl):
            - trades: one row per trade with entry/exit prices and share/Dollar PnL.
            - daily_pnl: aggregated dollar PnL and equity curve per date.
    """
    # Daily features
    features = build_daily_features(symbol, atr_period=atr_period, rvol_period=rvol_period)
    features["date"] = pd.to_datetime(features["date"]).dt.date

    start = pd.to_datetime(start_date).date()
    end = pd.to_datetime(end_date).date()
    mask = (features["date"] >= start) & (features["date"] <= end)
    features = features.loc[mask].copy()

    # Intraday 5min
    intraday = _load_5min(symbol)

    trades = []
    equity = initial_equity

    for date, row in features.iterrows():
        d = row["date"]

        atr_col = f"atr_{atr_period}"
        rvol_col = f"or_rvol_{rvol_period}"

        atr_val = row.get(atr_col)
        or_rvol = row.get(rvol_col)
        or_dir = row.get("or_direction")
        or_high = row.get("or_high")
        or_low = row.get("or_low")

        # Skip if we don't have required features
        if pd.isna(atr_val) or pd.isna(or_rvol) or pd.isna(or_dir) or pd.isna(or_high) or pd.isna(or_low):
            continue

        # RVOL filter
        if or_rvol < rvol_threshold:
            continue

        # Determine direction
        if or_dir > 0:
            direction = 1  # long only
        elif or_dir < 0:
            direction = -1  # short only
        else:
            continue  # doji day

        day_bars = intraday[intraday["date"] == d].sort_values("ts_et")
        if day_bars.empty:
            continue

        # We assume opening range bar already happened; we trade from after 9:30 bar
        # Filter to bars after 9:30 ET
        day_bars = day_bars[day_bars["ts_et"].dt.time > pd.to_datetime("09:30").time()]
        if day_bars.empty:
            continue

        stop_dist = atr_stop_pct * atr_val

        if direction == 1:
            entry_level = or_high
            stop_level = entry_level - stop_dist
        else:
            entry_level = or_low
            stop_level = entry_level + stop_dist

        in_trade = False
        entry_price = None
        exit_price = None
        entry_time = None
        exit_time = None

        for _, bar in day_bars.iterrows():
            high = bar["high"]
            low = bar["low"]
            close = bar["close"]
            ts = bar["ts_et"]

            if not in_trade:
                # Check entry
                if direction == 1 and high >= entry_level:
                    in_trade = True
                    entry_price = entry_level
                    entry_time = ts
                elif direction == -1 and low <= entry_level:
                    in_trade = True
                    entry_price = entry_level
                    entry_time = ts
            else:
                # Check stop
                if direction == 1:
                    if low <= stop_level:
                        exit_price = stop_level
                        exit_time = ts
                        break
                else:
                    if high >= stop_level:
                        exit_price = stop_level
                        exit_time = ts
                        break

        # If still in trade at EOD, exit at last close
        if in_trade:
            if exit_price is None:
                last_bar = day_bars.iloc[-1]
                exit_price = last_bar["close"]
                exit_time = last_bar["ts_et"]

            pnl_per_share = (exit_price - entry_price) * direction

            # Risk-based position sizing: risk_per_trade_frac * equity per trade
            # Risk per share approximated by ATR stop distance.
            risk_dollars = risk_per_trade_frac * equity
            per_share_risk = stop_dist
            if per_share_risk <= 0:
                continue

            shares = max(int(risk_dollars // per_share_risk), 0)
            if shares == 0:
                continue

            gross_pnl = pnl_per_share * shares
            # Simple per-share commission: entry + exit
            commissions = commission_per_share * shares * 2
            net_pnl = gross_pnl - commissions

            equity += net_pnl

            trades.append({
                "symbol": symbol,
                "date": d,
                "direction": direction,
                "entry_time": entry_time,
                "entry_price": entry_price,
                "exit_time": exit_time,
                "exit_price": exit_price,
                "pnl_per_share": pnl_per_share,
                "shares": shares,
                "gross_pnl": gross_pnl,
                "commissions": commissions,
                "net_pnl": net_pnl,
                "equity_after_trade": equity,
                atr_col: atr_val,
                rvol_col: or_rvol,
                "or_high": or_high,
                "or_low": or_low,
            })

    trades_df = pd.DataFrame(trades)

    if trades_df.empty:
        daily_pnl = pd.DataFrame(columns=["date", "net_pnl", "equity"])
    else:
        daily_pnl = (
            trades_df
            .groupby("date")["net_pnl"]
            .sum()
            .reset_index()
            .sort_values("date")
        )
        # Build an equity curve from initial_equity
        eq = initial_equity
        equities = []
        for _, r in daily_pnl.iterrows():
            eq += r["net_pnl"]
            equities.append(eq)
        daily_pnl["equity"] = equities

    return trades_df, daily_pnl


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run single-symbol ORB backtest.")
    parser.add_argument("symbol", type=str, help="Ticker symbol, e.g. AAPL")
    parser.add_argument("--start", type=str, default="2022-01-01")
    parser.add_argument("--end", type=str, default="2022-03-31")
    parser.add_argument("--rvol-threshold", type=float, default=1.0)
    parser.add_argument("--atr-stop-pct", type=float, default=0.10)
    parser.add_argument("--initial-equity", type=float, default=100_000.0)
    parser.add_argument("--risk-per-trade-frac", type=float, default=0.01)
    parser.add_argument("--commission-per-share", type=float, default=0.0035)

    args = parser.parse_args()

    trades, daily_pnl = run_orb_single_symbol(
        symbol=args.symbol,
        start_date=args.start,
        end_date=args.end,
        rvol_threshold=args.rvol_threshold,
        atr_stop_pct=args.atr_stop_pct,
        initial_equity=args.initial_equity,
        risk_per_trade_frac=args.risk_per_trade_frac,
        commission_per_share=args.commission_per_share,
    )

    print("Trades (first 10):")
    print(trades.head(10))

    print("\nDaily PnL:")
    print(daily_pnl.head(20))
