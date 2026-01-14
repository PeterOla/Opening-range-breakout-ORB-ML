"""
ORB Scanner Service (Hybrid: Local Parquet DB + Alpaca Live).

1. Uses daily_bars DB (from local Parquet) for ATR and avg_volume
2. Uses Alpaca for live 5-min opening range bar
3. Computes RVOL, applies filters, ranks top 20
"""
from datetime import datetime, time, timedelta
from typing import Optional
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import duckdb
import pandas as pd
from core.config import settings
from services.universe import fetch_5min_bars, load_universe_from_parquet
from state.duckdb_store import DuckDBStateStore


ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
OR_END = time(9, 35)


def _repo_root() -> Path:
    # services/orb_scanner.py -> services -> backend -> prod -> repo_root
    return Path(__file__).resolve().parents[3]


def _allowed_symbols_from_universe_setting() -> Optional[set[str]]:
    key = (getattr(settings, "ORB_UNIVERSE", "all") or "all").strip().lower()
    if key in {"all", ""}:
        return None

    universe_file_map = {
        "micro": "universe_micro_full.parquet",
        "small": "universe_small.parquet",
        "large": "universe_large.parquet",
        "micro_small": "universe_micro_small.parquet",
        "micro_small_unknown": "universe_micro_small_unknown.parquet",
        "micro_unknown": "universe_micro_unknown.parquet",
        "unknown": "universe_unknown.parquet",
    }
    file_name = universe_file_map.get(key)
    if not file_name:
        raise ValueError(
            f"Unknown ORB_UNIVERSE={key}. Valid: {sorted(universe_file_map.keys()) + ['all']}"
        )

    p1 = _repo_root() / "data" / "backtest" / "orb" / "universe" / file_name
    p2 = Path("data/backtest/orb/universe") / file_name
    universe_path = p1 if p1.exists() else p2

    if not universe_path.exists():
        raise FileNotFoundError(
            f"Universe file not found for ORB_UNIVERSE={key}: tried {p1} and {p2}"
        )

    # Use robust shared loader
    try:
        symbols_list = load_universe_from_parquet(universe_path)
        return set(symbols_list)
    except Exception as e:
        raise ValueError(f"Failed to load universe from {universe_path}: {e}")


def _get_sentiment_allowlist(target_date: datetime.date) -> Optional[set[str]]:
    """
    Load sentiment allowlist for the given date.
    Returns:
        - Set of allowed symbols if file exists.
        - None if file does not exist (indicating no filter).
    """
    # Expected path: data/sentiment/allowlist_YYYY-MM-DD.json
    date_str = target_date.strftime("%Y-%m-%d")
    path = _repo_root() / "data" / "sentiment" / f"allowlist_{date_str}.json"
    
    if not path.exists():
        return None
        
    try:
        with open(path, "r") as f:
            data = json.load(f)
            # data structure: {"allowed": ["AAPL", ...], "rejected": [...]}
            allowed = data.get("allowed", [])
            return {str(s).upper().strip() for s in allowed}
    except Exception as e:
        print(f"Error loading sentiment allowlist {path}: {e}")
        return None


def get_opening_range_from_bars(df: pd.DataFrame, target_date: Optional[datetime] = None) -> Optional[dict]:
    """
    Extract opening range (first 5-min bar 9:30-9:35 ET) from 5min bars DataFrame.
    """
    if df is None or df.empty:
        return None
    
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    
    # Convert to ET
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert(ET)
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert(ET)
    
    df["date"] = df["timestamp"].dt.date
    
    # Get target date
    if target_date is None:
        target_date = datetime.now(ET).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()
    
    # Filter to target date's 9:30 bar
    mask = (df["date"] == target_date) & (df["timestamp"].dt.hour == 9) & (df["timestamp"].dt.minute == 30)
    or_bar = df[mask]
    
    if or_bar.empty:
        return None
    
    bar = or_bar.iloc[0]
    
    # Determine direction
    if bar["close"] > bar["open"]:
        direction = 1  # Bullish - long only
    elif bar["close"] < bar["open"]:
        direction = -1  # Bearish - short only
    else:
        direction = 0  # Doji - skip
    
    return {
        "or_open": float(bar["open"]),
        "or_high": float(bar["high"]),
        "or_low": float(bar["low"]),
        "or_close": float(bar["close"]),
        "or_volume": float(bar["volume"]),
        "direction": direction,
        "timestamp": bar["timestamp"],
    }


def compute_rvol(or_volume: float, avg_volume: float) -> Optional[float]:
    """
    Compute Relative Volume (RVOL).
    
    RVOL = (OR_volume extrapolated to full day) / avg_daily_volume
    
    Approximation: OR (first 5 min) typically ~10% of daily volume for active stocks.
    We extrapolate: full_day_volume ≈ or_volume * 78 (78 five-min bars in trading day).
    """
    if avg_volume is None or avg_volume == 0:
        return None
    
    # Extrapolate OR volume to full day
    extrapolated_daily = or_volume * 78
    return extrapolated_daily / avg_volume


def _get_universe_with_metrics_from_local_parquet(
    min_price: float,
    min_atr: float,
    min_avg_volume: float,
    allowed_symbols: Optional[set[str]] = None,
) -> list[dict]:
    """Return latest daily metrics per symbol from local Parquet using DuckDB."""
    base = Path(getattr(settings, "PARQUET_BASE_PATH", "./data/processed"))
    glob_path = str((base / "daily" / "*.parquet").as_posix())

    con = duckdb.connect(str(getattr(settings, "DUCKDB_PATH", "./data/duckdb_local.db")))
    try:
        allowed_df = None
        if allowed_symbols is not None:
            allowed = [str(s).upper().strip() for s in allowed_symbols if s]
            if allowed:
                allowed_df = pd.DataFrame({"symbol": allowed})
                con.register("allowed_symbols", allowed_df)

        q = """
            WITH raw AS (
                SELECT symbol, date, close, atr_14, avg_volume_14
                FROM read_parquet(?, hive_partitioning=false)
            ),
            latest AS (
                SELECT
                    symbol,
                    max(date) AS date,
                    arg_max(close, date) AS close,
                    arg_max(atr_14, date) AS atr_14,
                    arg_max(avg_volume_14, date) AS avg_volume_14
                FROM raw
                GROUP BY symbol
            )
            SELECT l.symbol, l.date, l.close, l.atr_14, l.avg_volume_14
            FROM latest l
        """

        if allowed_df is not None and not allowed_df.empty:
            q += " JOIN allowed_symbols a ON a.symbol = l.symbol "

        q += """
            WHERE l.close >= ?
              AND l.atr_14 >= ?
              AND l.avg_volume_14 >= ?
        """

        df = con.execute(q, [glob_path, float(min_price), float(min_atr), float(min_avg_volume)]).fetchdf()
        if df is None or df.empty:
            return []

        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        return [
            {
                "symbol": row["symbol"],
                "date": row["date"],
                "close": float(row["close"]),
                "atr_14": float(row["atr_14"]),
                "avg_volume_14": float(row["avg_volume_14"]),
            }
            for _, row in df.iterrows()
        ]
    finally:
        con.close()


async def scan_orb_candidates(
    min_price: float = 5.0,
    min_atr: float = 0.50,
    min_avg_volume: float = 1_000_000,
    min_rvol: float = 1.0,
    top_n: int = 20,
    save_to_db: bool = True,
    use_sentiment_filter: bool = True,
) -> dict:
    """
    Full ORB scan using hybrid data approach.
    
    Pipeline:
    1. Get universe from daily_bars DB (pre-filtered by price, ATR, avg_volume)
    2. Fetch today's 5-min OR bar from Alpaca for each candidate
    3. Compute RVOL, apply filter
    4. Rank by RVOL, take top N
    5. Optionally save to opening_ranges table
    
    Returns:
        Dict with scan results and candidates
    """
    now_et = datetime.now(ET)
    today = now_et.date()
    
    try:
        allowed_symbols = _allowed_symbols_from_universe_setting()

        # --- Sentiment Filter Integration ---
        if use_sentiment_filter:
            sentiment_allowed = _get_sentiment_allowlist(today)
            if sentiment_allowed is not None:
                print(f"[Sentiment] Allowlist found with {len(sentiment_allowed)} symbols.")
                if allowed_symbols is None:
                    allowed_symbols = sentiment_allowed
                else:
                    original_count = len(allowed_symbols)
                    allowed_symbols = allowed_symbols.intersection(sentiment_allowed)
                    print(f"[Sentiment] Filtered universe: {original_count} -> {len(allowed_symbols)} symbols")
            else:
                print(f"[Sentiment] Filter enabled but no allowlist found for {today}. Skipping.")
        # ------------------------------------

        # Step 1: Get universe with pre-computed metrics from local Parquet via DuckDB.
        print("Fetching universe (Parquet + DuckDB)...")
        universe = _get_universe_with_metrics_from_local_parquet(
            min_price=min_price,
            min_atr=min_atr,
            min_avg_volume=min_avg_volume,
            allowed_symbols=allowed_symbols,
        )
        
        if not universe:
            return {
                "status": "error",
                "error": "No symbols pass base filters (Parquet/DuckDB). Check daily Parquet metrics and thresholds.",
                "candidates": [],
            }
        
        symbols = [u["symbol"] for u in universe]
        print(f"Universe size after base filters: {len(symbols)} symbols")
        
        # Create lookup for metrics
        metrics_lookup = {u["symbol"]: u for u in universe if u["symbol"] in set(symbols)}
        
        # Step 2: Fetch today's 5-min bars from Alpaca
        print(f"Fetching 5-min bars for {len(symbols)} symbols (prefer local parquet when available)...")
        # Use today's date as target_date to prefer local Parquet/duckdb storage for pre-market views
        target_dt = datetime.combine(today, time(0, 0))
        fivemin_bars = await fetch_5min_bars(symbols, lookback_days=1, target_date=target_dt)
        print(f"Got 5-min bars for {len(fivemin_bars)} symbols")
        
        # Step 3 & 4: Extract OR, compute RVOL, filter
        candidates: list[dict] = []
        or_bar_found = 0

        for symbol in symbols:
            bars_df = fivemin_bars.get(symbol)
            if bars_df is None:
                continue

            or_data = get_opening_range_from_bars(bars_df, target_date=today)
            if or_data is None:
                continue

            # Skip doji candles
            if or_data["direction"] == 0:
                continue

            or_bar_found += 1

            metrics = metrics_lookup.get(symbol)
            if not metrics:
                continue

            # Compute RVOL
            rvol = compute_rvol(or_data["or_volume"], metrics["avg_volume_14"])
            if rvol is None or rvol < min_rvol:
                continue

            # Calculate entry and stop
            atr = metrics["atr_14"]
            if or_data["direction"] == 1:  # Long
                entry_price = or_data["or_high"]
                stop_price = entry_price - (0.10 * atr)
            else:  # Short
                entry_price = or_data["or_low"]
                stop_price = entry_price + (0.10 * atr)

            candidates.append(
                {
                    "symbol": symbol,
                    "price": metrics["close"],
                    "atr": round(atr, 2),
                    "avg_volume": int(metrics["avg_volume_14"]),
                    "rvol": round(rvol, 2),
                    "or_high": round(or_data["or_high"], 2),
                    "or_low": round(or_data["or_low"], 2),
                    "or_open": round(or_data["or_open"], 2),
                    "or_close": round(or_data["or_close"], 2),
                    "or_volume": int(or_data["or_volume"]),
                    "direction": or_data["direction"],
                    "direction_label": "LONG" if or_data["direction"] == 1 else "SHORT",
                    "entry_price": round(entry_price, 2),
                    "stop_price": round(stop_price, 2),
                    "stop_distance": round(0.10 * atr, 2),
                }
            )

        if or_bar_found == 0:
            return {
                "status": "error",
                "error": "No 9:30 ET opening-range bar found for today. If you are running before/after market hours, run after 09:35 ET or adjust your data source.",
                "candidates": [],
            }

        print(f"Candidates after RVOL filter: {len(candidates)}")

        # Step 5: Rank by RVOL and take top N
        candidates.sort(key=lambda x: x["rvol"], reverse=True)

        # Assign ranks
        for i, c in enumerate(candidates):
            c["rank"] = i + 1

        top_candidates = candidates[:top_n]

        # Step 6: Save to DuckDB state store if requested
        if save_to_db and candidates:
            store = DuckDBStateStore()
            store.replace_opening_ranges(
                target_date=today,
                candidates=[
                    {
                        **c,
                        "passed_filters": bool(c.get("rank") and c["rank"] <= top_n),
                        "rank": int(c["rank"]) if c.get("rank") and c["rank"] <= top_n else None,
                        "signal_generated": False,
                        "order_placed": False,
                    }
                    for c in candidates
                ],
            )
            print(f"Saved {len(candidates)} candidates to DuckDB state store")
        
        return {
            "status": "success",
            "timestamp": datetime.now(ET).isoformat(),
            "date": str(today),
            "filters": {
                "min_price": min_price,
                "min_atr": min_atr,
                "min_avg_volume": min_avg_volume,
                "min_rvol": min_rvol,
                "top_n": top_n,
            },
            "universe_size": len(symbols),
            "candidates_total": len(candidates),
            "candidates_top_n": len(top_candidates),
            "candidates": top_candidates,
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "candidates": [],
        }


async def get_todays_candidates(top_n: int = 20, direction: str = "both") -> list[dict]:
    """
    Get today's top N candidates from database (if already scanned).
    
    Args:
        top_n: Maximum number of candidates to return
        direction: Filter by direction - 'long', 'short', or 'both'
    """
    store = DuckDBStateStore()
    candidates = store.get_todays_candidates(top_n=int(top_n), direction=str(direction or "both"))
    for c in candidates:
        d = c.get("direction")
        c["direction_label"] = "LONG" if d == 1 else "SHORT" if d == -1 else None
    return candidates


async def get_todays_candidates_with_live_pnl(top_n: int = 20) -> list[dict]:
    """
    Get today's candidates with live prices and unrealized P&L.
    
    For each candidate:
    1. Fetch current price from Alpaca
    2. Determine if entry would have been triggered (price crossed entry level)
    3. Calculate unrealized P&L (or realized if stop was hit)
    
    Position sizing: $1000 capital, 1% risk, 2x max leverage
    """
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from core.config import settings

    today = datetime.now(ET).date()
    
    # Position sizing constants - Fixed 2x leverage
    CAPITAL = 1000.0
    
    try:
        store = DuckDBStateStore()
        candidates = store.get_todays_candidates(top_n=int(top_n), direction="both")
        if not candidates:
            return []

        symbols = [str(c.get("symbol", "")).upper().strip() for c in candidates if c.get("symbol")]
        
        # Fetch current prices from Alpaca
        data_client = StockHistoricalDataClient(
            api_key=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
        )
        
        # Get latest quotes
        try:
            quotes_request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
            quotes = data_client.get_stock_latest_quote(quotes_request)
        except Exception as e:
            print(f"Failed to get quotes: {e}")
            quotes = {}
        
        # Get today's bars to check for entry/stop triggers
        now = datetime.now(ET)
        start = datetime.combine(today, time(9, 35)).replace(tzinfo=ET)
        
        try:
            bars_request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Minute,
                start=start,
                end=now,
            )
            all_bars = data_client.get_stock_bars(bars_request)
        except Exception as e:
            print(f"Failed to get bars: {e}")
            all_bars = {}
        
        results = []
        
        for c in candidates:
            symbol = str(c.get("symbol", "")).upper().strip()
            entry_price = float(c.get("entry_price") or 0)
            stop_price = float(c.get("stop_price") or 0)
            direction = int(c.get("direction") or 0)
            
            # Get current price
            current_price = None
            if symbol in quotes:
                q = quotes[symbol]
                current_price = float(q.ask_price + q.bid_price) / 2 if q.ask_price and q.bid_price else None
            
            # Check entry/stop triggers from intraday bars
            entered = False
            stopped_out = False
            entry_time = None
            exit_time = None
            exit_price = None
            exit_reason = None
            
            if symbol in all_bars:
                bars_df = all_bars[symbol].df if hasattr(all_bars[symbol], 'df') else pd.DataFrame(all_bars[symbol])
                if not bars_df.empty:
                    for idx, bar in bars_df.iterrows():
                        if not entered:
                            # Check for entry trigger
                            if direction == 1:  # Long
                                if bar['high'] >= entry_price:
                                    entered = True
                                    entry_time = idx.strftime("%H:%M") if hasattr(idx, 'strftime') else str(idx)
                            else:  # Short
                                if bar['low'] <= entry_price:
                                    entered = True
                                    entry_time = idx.strftime("%H:%M") if hasattr(idx, 'strftime') else str(idx)
                        else:
                            # Check for stop trigger
                            if direction == 1:  # Long - stop is below
                                if bar['low'] <= stop_price:
                                    stopped_out = True
                                    exit_price = stop_price
                                    exit_time = idx.strftime("%H:%M") if hasattr(idx, 'strftime') else str(idx)
                                    exit_reason = "STOP_LOSS"
                                    break
                            else:  # Short - stop is above
                                if bar['high'] >= stop_price:
                                    stopped_out = True
                                    exit_price = stop_price
                                    exit_time = idx.strftime("%H:%M") if hasattr(idx, 'strftime') else str(idx)
                                    exit_reason = "STOP_LOSS"
                                    break
            
            # Fixed 2x leverage position sizing
            LEVERAGE = 2.0
            position_value = CAPITAL * LEVERAGE  # $2000 position
            shares = position_value / entry_price if entry_price > 0 else 0
            leverage = LEVERAGE
            
            # Calculate P&L
            pnl_pct = 0
            dollar_pnl = 0
            base_dollar_pnl = 0
            
            if entered:
                if stopped_out:
                    # Realized loss at stop
                    if direction == 1:
                        pnl_pct = (exit_price - entry_price) / entry_price * 100
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price * 100
                    price_move = (exit_price - entry_price) * direction
                    dollar_pnl = shares * price_move
                    base_shares = CAPITAL / entry_price
                    base_dollar_pnl = base_shares * price_move
                elif current_price:
                    # Unrealized P&L
                    if direction == 1:
                        pnl_pct = (current_price - entry_price) / entry_price * 100
                    else:
                        pnl_pct = (entry_price - current_price) / entry_price * 100
                    price_move = (current_price - entry_price) * direction
                    dollar_pnl = shares * price_move
                    base_shares = CAPITAL / entry_price
                    base_dollar_pnl = base_shares * price_move
                    exit_reason = "LIVE"
            
            results.append({
                "symbol": symbol,
                "rank": c.get("rank"),
                "direction": direction,
                "direction_label": "LONG" if direction == 1 else "SHORT",
                "rvol": c.get("rvol"),
                "atr": c.get("atr"),
                "entry_price": entry_price,
                "stop_price": stop_price,
                "or_high": c.get("or_high"),
                "or_low": c.get("or_low"),
                "current_price": round(current_price, 2) if current_price else None,
                "entered": entered,
                "entry_time": entry_time,
                "exit_price": round(exit_price, 2) if exit_price else (round(current_price, 2) if current_price and entered else None),
                "exit_time": exit_time,
                "exit_reason": exit_reason,
                "pnl_pct": round(pnl_pct, 2),
                "dollar_pnl": round(dollar_pnl, 2),
                "base_dollar_pnl": round(base_dollar_pnl, 2),
                "leverage": round(leverage, 2),
                "is_winner": pnl_pct > 0 if entered else None,
                # Live mode specific fields
                "unrealized_pnl": round(dollar_pnl, 2) if not stopped_out and entered else None,
                "unrealized_pnl_pct": round(pnl_pct, 2) if not stopped_out and entered else None,
            })
        
        return results
    
    finally:
        pass
