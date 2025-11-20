import pandas as pd
from pathlib import Path
from typing import Tuple, Optional
import sys

# Add project root to path to allow importing ml_orb_5m
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.data.features import build_daily_features

FIVEMIN_DIR = Path("data/processed/5min")
DAILY_DIR = Path("data/processed/daily")
ML_MODELS_DIR = PROJECT_ROOT / "ml_orb_5m" / "models" / "saved_models"
ML_CONFIG_PATH = PROJECT_ROOT / "ml_orb_5m" / "config" / "selected_features.json"

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

def _load_daily(symbol: str) -> pd.DataFrame:
    path = DAILY_DIR / f"{symbol}.parquet"
    if not path.exists():
        # It's possible daily data is missing if we only have 5min, but for ML we need it.
        # We can try to resample 5min if daily is missing, but for now let's assume it exists or return empty.
        return pd.DataFrame()

    df = pd.read_parquet(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def run_orb_single_symbol(
    symbol: str,
    start_date: str,
    end_date: str,
    atr_period: int = 14,
    rvol_period: int = 14,
    rvol_threshold: float = 1.0,
    atr_stop_pct: float = 0.10,
    initial_equity: float = 1000.0,
    risk_per_trade_frac: float = 0.01,
    commission_per_share: float = 0.0035,
    min_commission_per_trade: float = 0.0,
    slippage_per_share: float = 0.0,
    min_price: float = 5.0,
    min_atr: float = 0.5,
    use_ml: bool = False,
    ml_threshold: float = 0.60,
    valid_dates: Optional[list] = None,
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
      
      ML Integration:
      - If use_ml is True, loads the Dual Model and filters trades based on ml_threshold.
      
      Optimization:
      - valid_dates: If provided, only processes these specific dates.

        Returns (trades, daily_pnl):
            - trades: one row per trade with entry/exit prices and share/Dollar PnL.
            - daily_pnl: aggregated dollar PnL and equity curve per date.
    """
    # ML Setup
    ml_predictor = None
    spy_df = pd.DataFrame()
    qqq_df = pd.DataFrame()
    vix_df = pd.DataFrame()
    bars_daily = pd.DataFrame()
    
    if use_ml:
        try:
            from ml_orb_5m.src.inference.predictor import MLPredictor
            print(f"Initializing ML Predictor (Threshold: {ml_threshold})...")
            ml_predictor = MLPredictor(ML_MODELS_DIR, ML_CONFIG_PATH)
            
            # Load Market Context Data
            if ml_predictor.uses_market_context:
                print("Loading Market Context Data (SPY, QQQ, VIX)...")
                spy_df = _load_daily("SPY")
                qqq_df = _load_daily("QQQ")
                vix_df = _load_daily("VIX")
            
            # Load Symbol Daily Data (for history features)
            bars_daily = _load_daily(symbol)
            
        except ImportError:
            print("Error: Could not import MLPredictor. Make sure ml_orb_5m is in path.")
            use_ml = False
        except Exception as e:
            print(f"Error initializing ML: {e}")
            use_ml = False

    # Daily features
    features = build_daily_features(symbol, atr_period=atr_period, rvol_period=rvol_period)
    features["date"] = pd.to_datetime(features["date"]).dt.date

    start = pd.to_datetime(start_date).date()
    end = pd.to_datetime(end_date).date()
    mask = (features["date"] >= start) & (features["date"] <= end)
    features = features.loc[mask].copy()
    
    print(f"Processing {len(features)} days for {symbol}...")

    # Intraday 5min
    intraday = _load_5min(symbol)

    trades = []
    equity = initial_equity

    for date, row in features.iterrows():
        d = row["date"]
        
        # Optimization: Skip dates not in valid_dates
        if valid_dates is not None and d not in valid_dates:
            continue

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

        # Filter: Minimum Price and ATR to avoid friction costs destroying small scalps
        # Use or_high as a proxy for price
        if or_high < min_price:
            continue
        if atr_val < min_atr:
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

        # --- ML Filter ---
        ml_prob = 0.0
        if use_ml and ml_predictor:
            try:
                # Calculate features live
                # We need to pass the 5min bars for this symbol
                # Ideally we pass the whole dataframe and let the predictor filter, 
                # or we pass just what's needed. 
                # The predictor.calculate_features_live expects the full 5min df to do lookbacks if needed,
                # but currently it filters by date inside.
                
                # Optimization: Pass only relevant history to avoid huge DF copies if possible,
                # but for now passing 'intraday' (full 5min) is safest for correctness.
                
                live_features = ml_predictor.calculate_features_live(
                    symbol=symbol,
                    date=d,
                    bars_5m=intraday,
                    bars_daily=bars_daily,
                    spy_df=spy_df,
                    qqq_df=qqq_df,
                    vix_df=vix_df
                )
                
                # Add direction/side
                live_features['direction'] = direction
                
                ml_prob = ml_predictor.predict(live_features)
                # print(f"Date: {d}, Direction: {direction}, ML Prob: {ml_prob:.4f}")
                
                if ml_prob < ml_threshold:
                    # Skip trade
                    continue

            except Exception as e:
                print(f"ML Prediction Error on {d}: {e}")
                # If calculation fails (e.g. missing data), skip trade or allow?
                # Strict: skip
                continue
        # -----------------

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

            # Apply slippage to entry and exit prices
            # Long: Buy higher (entry + slip), Sell lower (exit - slip)
            # Short: Sell lower (entry - slip), Buy higher (exit + slip)
            if direction == 1:
                real_entry_price = entry_price + slippage_per_share
                real_exit_price = exit_price - slippage_per_share
            else:
                real_entry_price = entry_price - slippage_per_share
                real_exit_price = exit_price + slippage_per_share

            pnl_per_share = (real_exit_price - real_entry_price) * direction

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
            commissions = max(min_commission_per_trade, commission_per_share * shares) * 2
            net_pnl = gross_pnl - commissions

            equity += net_pnl

            trades.append({
                "symbol": symbol,
                "date": d,
                "direction": direction,
                "entry_time": entry_time,
                "entry_price": real_entry_price,
                "exit_time": exit_time,
                "exit_price": real_exit_price,
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
                "ml_prob": ml_prob if use_ml else None,
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
    parser.add_argument("--use-ml", action="store_true", help="Enable ML filtering")
    parser.add_argument("--ml-threshold", type=float, default=0.60, help="ML probability threshold")

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
        use_ml=args.use_ml,
        ml_threshold=args.ml_threshold,
    )

    print("Trades (first 10):")
    print(trades.head(10))

    print("\nDaily PnL:")
    print(daily_pnl.head(20))
