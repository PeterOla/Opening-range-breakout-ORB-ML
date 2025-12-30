"""Fast backtester for the ORB 30M Fibonacci pullback strategy.

Implements the rules described in `strategies/ORB 30M Fib/docs/readme.md`:
- Compute an opening range over the first N minutes after 09:30 ET
- Wait for breakout of OR high/low
- Draw Fib retracement from session extreme -> breakout extreme
- Enter on pullback to 50% / 61.8% with oscillator confirmation (MACD/RSI)
- Stop below/above 78.6% (or recent swing), target via R-multiple or session extreme

This script intentionally mirrors `scripts/ORB/fast_backtest.py`:
- Reads the existing ORB universe parquet (for fast candidate selection)
- Re-ranks by RVOL and takes Top-N per day
- Applies share sizing with a liquidity cap (% of daily volume)
- Writes the same parquet artefacts + `summary.md` (via analyse_run)

Usage:
    cd prod/backend
    python scripts/ORB30MFib/fast_backtest.py --universe universe_micro.parquet --run-name fib_micro_long --side long
"""

import sys

sys.path.insert(0, ".")

import argparse
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Optional, Tuple

import json
import numpy as np
import pandas as pd
from tqdm import tqdm

from scripts.ORB.analyse_run import write_run_summary_md
from core.config import settings


CAPITAL = settings.TRADING_CAPITAL
LEVERAGE = settings.FIXED_LEVERAGE
INITIAL_CAPITAL = settings.TRADING_CAPITAL

SPREAD_PCT = 0.001  # 0.1% per side (0.2% round trip)

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
ORB_UNIVERSE_DIR = DATA_DIR / "backtest" / "orb" / "universe"

FIB_RUNS_DIR = DATA_DIR / "backtest" / "orb_30m_fib" / "runs"
FIB_RUNS_DIR.mkdir(parents=True, exist_ok=True)

OR_START = time(9, 30)


def resolve_run_dir(run_name: str, *, compound: bool) -> Path:
    lowered = (run_name or "").lower()
    if lowered.startswith(("test_", "exp_", "experiment_", "rc_test_")):
        group = "experiments"
    elif compound:
        group = "compound"
    else:
        group = "fixed"
    return FIB_RUNS_DIR / group / run_name


def deserialize_bars(bars_data) -> pd.DataFrame:
    """Deserialize bars from list or JSON string."""
    if isinstance(bars_data, str):
        data = json.loads(bars_data)
        df = pd.DataFrame(data)
        df["datetime"] = pd.to_datetime(df["datetime"])
    else:
        df = pd.DataFrame(bars_data, columns=["datetime", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["datetime"])

    df["time"] = df["datetime"].dt.time
    return df


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    # Wilder's smoothing via EMA with alpha=1/period
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


@dataclass(frozen=True)
class TradeSimResult:
    entered: bool
    exit_reason: str
    direction: int = 0
    entry_price: Optional[float] = None
    entry_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    pnl_pct: Optional[float] = None
    dollar_pnl: Optional[float] = None
    base_dollar_pnl: Optional[float] = None
    position_size: Optional[float] = None
    stop_level: Optional[float] = None
    target_level: Optional[float] = None
    breakout_time: Optional[str] = None
    breakout_extreme: Optional[float] = None
    session_anchor_a: Optional[float] = None
    session_anchor_b: Optional[float] = None
    fib_50: Optional[float] = None
    fib_618: Optional[float] = None
    fib_786: Optional[float] = None
    is_capped: bool = False
    cap_ratio: float = 1.0
    target_shares: Optional[float] = None
    actual_shares: Optional[float] = None
    max_allowed_shares: Optional[float] = None


def _opening_range(bars_rth: pd.DataFrame, minutes: int) -> Optional[dict]:
    if bars_rth.empty:
        return None

    bars_rth = bars_rth.sort_values("datetime")
    start_dt = bars_rth.iloc[0]["datetime"]

    # Robustness: ensure OR starts at 09:30 if present
    or_start_rows = bars_rth[bars_rth["time"] == OR_START]
    if not or_start_rows.empty:
        start_dt = or_start_rows.iloc[0]["datetime"]

    end_dt = start_dt + pd.Timedelta(minutes=minutes)
    or_bars = bars_rth[(bars_rth["datetime"] >= start_dt) & (bars_rth["datetime"] < end_dt)].copy()
    if or_bars.empty:
        return None

    first = or_bars.iloc[0]
    last = or_bars.iloc[-1]

    direction = 0
    if float(last["close"]) > float(first["open"]):
        direction = 1
    elif float(last["close"]) < float(first["open"]):
        direction = -1

    return {
        "or_start": start_dt,
        "or_end": end_dt,
        "or_open": float(first["open"]),
        "or_close": float(last["close"]),
        "or_high": float(or_bars["high"].max()),
        "or_low": float(or_bars["low"].min()),
        "direction": direction,
        "or_bars": or_bars,
    }


def _fib_levels(direction: int, anchor_a: float, anchor_b: float) -> dict:
    """Return fib levels for a move from anchor_a -> anchor_b.

    For long setups: anchor_a=low, anchor_b=high.
    For short setups: anchor_a=high, anchor_b=low.
    """
    if direction == 1:
        low, high = float(anchor_a), float(anchor_b)
        rng = max(high - low, 1e-12)
        return {
            "low": low,
            "high": high,
            "50": high - 0.5 * rng,
            "618": high - 0.618 * rng,
            "786": high - 0.786 * rng,
        }

    high, low = float(anchor_a), float(anchor_b)
    rng = max(high - low, 1e-12)
    return {
        "high": high,
        "low": low,
        "50": low + 0.5 * rng,
        "618": low + 0.618 * rng,
        "786": low + 0.786 * rng,
    }


def _macd_confirm(direction: int, hist: pd.Series, macd_line: pd.Series, signal_line: pd.Series, idx: int) -> bool:
    # Strategy rule: "MACD divergence OR price starting to curl back up from midline".
    # We enforce this strictly via:
    # - Divergence: price makes a new extreme (lower low / higher high) while MACD histogram makes a weaker extreme.
    # - Curl: MACD histogram and MACD line trend in the expected direction for 3 consecutive bars.
    if idx < 3:
        return False

    if direction == 1:
        curl = (hist.iat[idx] > hist.iat[idx - 1] > hist.iat[idx - 2]) and (
            macd_line.iat[idx] > macd_line.iat[idx - 1] > macd_line.iat[idx - 2]
        )
    else:
        curl = (hist.iat[idx] < hist.iat[idx - 1] < hist.iat[idx - 2]) and (
            macd_line.iat[idx] < macd_line.iat[idx - 1] < macd_line.iat[idx - 2]
        )

    # Divergence check uses pivots; computed externally and passed in via closure.
    # Here we only implement curl; divergence is checked in the entry loop.
    return curl


def _find_pivots(series: pd.Series, *, kind: str, lookback: int = 50) -> list[int]:
    """Find simple local pivot indices in the last `lookback` bars.

    kind:
      - 'low'  -> local minima
      - 'high' -> local maxima
    """
    if series.empty:
        return []
    start = max(1, len(series) - lookback)
    end = len(series) - 1
    pivots: list[int] = []

    for i in range(start, end):
        prev_v = float(series.iat[i - 1])
        v = float(series.iat[i])
        next_v = float(series.iat[i + 1])

        if kind == "low" and v <= prev_v and v <= next_v:
            pivots.append(i)
        elif kind == "high" and v >= prev_v and v >= next_v:
            pivots.append(i)

    return pivots


def _macd_divergence(
    *,
    direction: int,
    price_extreme: pd.Series,
    hist: pd.Series,
    idx: int,
    lookback: int = 50,
) -> bool:
    """Detect bullish/bearish divergence using the two most recent pivots."""
    if idx < 3:
        return False

    window_price = price_extreme.iloc[: idx + 1]
    window_hist = hist.iloc[: idx + 1]

    if direction == 1:
        pivots = _find_pivots(window_price, kind="low", lookback=lookback)
        if len(pivots) < 2:
            return False
        a, b = pivots[-2], pivots[-1]
        price_a, price_b = float(window_price.iat[a]), float(window_price.iat[b])
        hist_a, hist_b = float(window_hist.iat[a]), float(window_hist.iat[b])
        return (price_b <= price_a) and (hist_b > hist_a)

    pivots = _find_pivots(window_price, kind="high", lookback=lookback)
    if len(pivots) < 2:
        return False
    a, b = pivots[-2], pivots[-1]
    price_a, price_b = float(window_price.iat[a]), float(window_price.iat[b])
    hist_a, hist_b = float(window_hist.iat[a]), float(window_hist.iat[b])
    return (price_b >= price_a) and (hist_b < hist_a)


def _rsi_confirm(direction: int, rsi: pd.Series, idx: int, threshold: float) -> bool:
    # Strict interpretation: use RSI midline (50) as "midline" proxy.
    # Long: RSI rising from below threshold.
    # Short: RSI falling from above threshold.
    if idx < 1:
        return False

    if direction == 1:
        return (rsi.iat[idx - 1] < threshold) and (rsi.iat[idx] >= rsi.iat[idx - 1])

    return (rsi.iat[idx - 1] > threshold) and (rsi.iat[idx] <= rsi.iat[idx - 1])


def simulate_trade_orb_fib(
    bars: pd.DataFrame,
    *,
    opening_range_minutes: int,
    max_entry_minutes: int,
    side_filter: str,
    fib_entry: str,
    oscillator: str,
    rsi_threshold: float,
    stop_mode: str,
    swing_buffer_pct: float,
    stop_buffer_pct: float,
    target_mode: str,
    rr: float,
    position_size: float,
    leverage: float,
    apply_leverage: bool,
    spread_pct: float,
    max_pct_volume: float,
) -> TradeSimResult:
    """Simulate ORB+Fib pullback trade on one day's bars for a single symbol."""

    # Regular-hours bars only (we still use full-day volume for liquidity cap).
    rth = bars[bars["time"] >= OR_START].copy()
    if rth.empty:
        return TradeSimResult(entered=False, exit_reason="NO_BARS")

    rth = rth.sort_values("datetime").reset_index(drop=True)
    or_info = _opening_range(rth, minutes=opening_range_minutes)
    if not or_info:
        return TradeSimResult(entered=False, exit_reason="NO_OR")

    direction = int(or_info["direction"])
    if direction == 0:
        return TradeSimResult(entered=False, exit_reason="NO_BIAS", direction=0)

    if side_filter == "long" and direction != 1:
        return TradeSimResult(entered=False, exit_reason="SIDE_FILTER", direction=direction)
    if side_filter == "short" and direction != -1:
        return TradeSimResult(entered=False, exit_reason="SIDE_FILTER", direction=direction)

    or_high = float(or_info["or_high"])
    or_low = float(or_info["or_low"])
    or_end_dt = or_info["or_end"]

    session_start_dt = or_info["or_start"]
    entry_end_dt = session_start_dt + pd.Timedelta(minutes=max_entry_minutes)

    post_or = rth[(rth["datetime"] >= or_end_dt) & (rth["datetime"] <= entry_end_dt)].copy().reset_index(drop=True)
    if post_or.empty:
        return TradeSimResult(entered=False, exit_reason="NO_POST_OR", direction=direction)

    close = rth["close"].astype(float)
    macd_line, signal_line, hist = compute_macd(close)
    rsi = compute_rsi(close)

    # 1) Breakout detection
    breakout_idx: Optional[int] = None
    breakout_dt: Optional[pd.Timestamp] = None

    # Index mapping: post_or index -> rth index
    post_or_to_rth_idx = post_or.index.to_numpy()

    for _, row_i in enumerate(post_or_to_rth_idx):
        bar = rth.iloc[row_i]
        if direction == 1 and float(bar["high"]) >= or_high:
            breakout_idx = int(row_i)
            breakout_dt = bar["datetime"]
            break
        if direction == -1 and float(bar["low"]) <= or_low:
            breakout_idx = int(row_i)
            breakout_dt = bar["datetime"]
            break

    if breakout_idx is None or breakout_dt is None:
        return TradeSimResult(entered=False, exit_reason="NO_BREAKOUT", direction=direction)

    # 2) Fib anchors (from session extreme up to breakout extreme)
    upto_breakout = rth.iloc[: breakout_idx + 1]

    breakout_extreme: float
    anchor_a: float
    anchor_b: float

    if direction == 1:
        session_low = float(upto_breakout["low"].min())
        breakout_high = float(upto_breakout["high"].max())
        anchor_a, anchor_b = session_low, breakout_high
        breakout_extreme = breakout_high
        fib = _fib_levels(direction, anchor_a, anchor_b)
    else:
        session_high = float(upto_breakout["high"].max())
        breakout_low = float(upto_breakout["low"].min())
        anchor_a, anchor_b = session_high, breakout_low
        breakout_extreme = breakout_low
        fib = _fib_levels(direction, anchor_a, anchor_b)

    fib50 = float(fib["50"])
    fib618 = float(fib["618"])
    fib786 = float(fib["786"])

    # 3) Entry search: pullback to 50/61.8 with oscillator confirmation
    entry_level: Optional[float] = None
    entry_idx: Optional[int] = None

    # Determine which levels are acceptable
    levels = []
    if fib_entry in {"50", "either"}:
        levels.append(("50", fib50))
    if fib_entry in {"618", "either"}:
        levels.append(("618", fib618))

    # For "either", prefer deeper pullback (better price) by checking 61.8 first for long
    if fib_entry == "either":
        if direction == 1:
            levels = [("618", fib618), ("50", fib50)]
        else:
            levels = [("618", fib618), ("50", fib50)]

    for idx in range(breakout_idx + 1, len(rth)):
        bar = rth.iloc[idx]
        if bar["datetime"] > entry_end_dt:
            break
        low = float(bar["low"])
        high = float(bar["high"])

        hit_level: Optional[float] = None
        for _, lvl in levels:
            if low <= lvl <= high:
                hit_level = lvl
                break

        if hit_level is None:
            continue

        if oscillator == "macd":
            # Strict: divergence OR curling up/down.
            if direction == 1:
                price_ext = rth["low"].astype(float)
            else:
                price_ext = rth["high"].astype(float)

            has_div = _macd_divergence(direction=direction, price_extreme=price_ext, hist=hist, idx=idx)
            has_curl = _macd_confirm(direction, hist, macd_line, signal_line, idx)
            if not (has_div or has_curl):
                continue
        elif oscillator == "rsi":
            if not _rsi_confirm(direction, rsi, idx, threshold=rsi_threshold):
                continue
        elif oscillator == "none":
            pass
        else:
            return TradeSimResult(entered=False, exit_reason="BAD_OSC", direction=direction)

        entry_level = float(hit_level)
        entry_idx = idx
        break

    if entry_level is None or entry_idx is None:
        return TradeSimResult(entered=False, exit_reason="NO_ENTRY", direction=direction)

    # 4) Stop level
    if stop_mode == "fib_786":
        stop_level = fib786 * (1 - stop_buffer_pct) if direction == 1 else fib786 * (1 + stop_buffer_pct)
    elif stop_mode == "swing":
        pullback_slice = rth.iloc[breakout_idx : entry_idx + 1]
        if direction == 1:
            swing = float(pullback_slice["low"].min())
            stop_level = swing * (1 - max(swing_buffer_pct, stop_buffer_pct))
        else:
            swing = float(pullback_slice["high"].max())
            stop_level = swing * (1 + max(swing_buffer_pct, stop_buffer_pct))
    else:
        return TradeSimResult(entered=False, exit_reason="BAD_STOP_MODE", direction=direction)

    # Sanity: avoid inverted stop
    if direction == 1 and stop_level >= entry_level:
        return TradeSimResult(entered=False, exit_reason="BAD_STOP", direction=direction)
    if direction == -1 and stop_level <= entry_level:
        return TradeSimResult(entered=False, exit_reason="BAD_STOP", direction=direction)

    # 5) Target level
    if target_mode == "rr":
        risk = abs(entry_level - stop_level)
        if risk <= 0:
            return TradeSimResult(entered=False, exit_reason="BAD_RISK", direction=direction)
        if direction == 1:
            target_level = entry_level + rr * risk
        else:
            target_level = entry_level - rr * risk
    elif target_mode in {"session_extreme", "breakout_extreme"}:
        # Strategy rule: "Profit target: new session high/low".
        # Conservative and literal: target the breakout extreme (session high/low at breakout leg).
        target_level = breakout_extreme
    else:
        return TradeSimResult(entered=False, exit_reason="BAD_TARGET", direction=direction)

    # 6) Liquidity cap (shares)
    total_daily_volume = float(bars["volume"].sum())
    max_allowed_shares = total_daily_volume * max_pct_volume

    # Entry/exit prices w/ spread
    if direction == 1:
        entry_price = entry_level * (1 + spread_pct)
    else:
        entry_price = entry_level * (1 - spread_pct)

    target_position_value = position_size * leverage if apply_leverage else position_size
    target_shares = target_position_value / entry_price

    actual_shares = min(target_shares, max_allowed_shares)
    is_capped = actual_shares < target_shares

    actual_position_value = actual_shares * entry_price
    actual_margin_used = actual_position_value / leverage if apply_leverage else actual_position_value

    # 7) Walk forward for stop/target/EOD
    exit_price: Optional[float] = None
    exit_time: Optional[time] = None
    exit_reason: Optional[str] = None

    for idx in range(entry_idx, len(rth)):
        bar = rth.iloc[idx]
        low = float(bar["low"])
        high = float(bar["high"])

        hit_stop = False
        hit_target = False

        if direction == 1:
            hit_stop = low <= stop_level
            hit_target = high >= target_level
        else:
            hit_stop = high >= stop_level
            hit_target = low <= target_level

        # Conservative intrabar handling: if both, assume stop first
        if hit_stop:
            exit_reason = "STOP_LOSS"
            exit_time = bar["time"]
            if direction == 1:
                exit_price = stop_level * (1 - spread_pct)
            else:
                exit_price = stop_level * (1 + spread_pct)
            break

        if hit_target:
            exit_reason = "TAKE_PROFIT"
            exit_time = bar["time"]
            if direction == 1:
                exit_price = target_level * (1 - spread_pct)
            else:
                exit_price = target_level * (1 + spread_pct)
            break

    if exit_price is None:
        last = rth.iloc[-1]
        exit_time = last["time"]
        exit_reason = "EOD"
        raw_close = float(last["close"])
        if direction == 1:
            exit_price = raw_close * (1 - spread_pct)
        else:
            exit_price = raw_close * (1 + spread_pct)

    direction_sign = 1 if direction == 1 else -1
    price_move = (exit_price - entry_price) * direction_sign
    pnl_pct = (price_move / entry_price) * 100.0

    dollar_pnl = actual_shares * price_move
    base_dollar_pnl = actual_margin_used * (pnl_pct / 100.0)

    return TradeSimResult(
        entered=True,
        exit_reason=str(exit_reason),
        direction=direction,
        entry_price=round(float(entry_price), 4),
        entry_time=str(rth.iloc[entry_idx]["time"].strftime("%H:%M")),
        exit_price=round(float(exit_price), 4),
        exit_time=str(exit_time.strftime("%H:%M")) if exit_time else None,
        pnl_pct=round(float(pnl_pct), 2),
        dollar_pnl=round(float(dollar_pnl), 2),
        base_dollar_pnl=round(float(base_dollar_pnl), 2),
        position_size=round(float(actual_margin_used), 2),
        stop_level=round(float(stop_level), 4),
        target_level=round(float(target_level), 4),
        breakout_time=str(breakout_dt.time().strftime("%H:%M")) if breakout_dt is not None else None,
        breakout_extreme=round(float(breakout_extreme), 4),
        session_anchor_a=round(float(anchor_a), 4),
        session_anchor_b=round(float(anchor_b), 4),
        fib_50=round(float(fib50), 4),
        fib_618=round(float(fib618), 4),
        fib_786=round(float(fib786), 4),
        is_capped=bool(is_capped),
        cap_ratio=round(float(actual_shares / target_shares), 2) if target_shares > 0 else 1.0,
        target_shares=float(target_shares),
        actual_shares=float(actual_shares),
        max_allowed_shares=float(max_allowed_shares),
    )


def run_strategy(
    universe_path: Path,
    min_atr: float,
    min_volume: int,
    top_n: int,
    side_filter: str,
    run_name: str,
    compound: bool,
    daily_risk: float,
    verbose: bool,
    max_pct_volume: float,
    opening_range_minutes: int,
    fib_entry: str,
    oscillator: str,
    rsi_threshold: float,
    stop_mode: str,
    swing_buffer_pct: float,
    stop_buffer_pct: float,
    target_mode: str,
    rr: float,
    max_entry_minutes: int,
):
    print(f"Loading universe: {universe_path}")
    df_universe = pd.read_parquet(universe_path)
    print(f"  Total candidates: {len(df_universe):,}")

    df_filtered = df_universe[(df_universe["atr_14"] >= min_atr) & (df_universe["avg_volume_14"] >= min_volume)].copy()
    print(f"  After runtime filters (ATR ≥ {min_atr}, Vol ≥ {min_volume:,}): {len(df_filtered):,}")

    df_filtered = df_filtered.sort_values(["trade_date", "rvol"], ascending=[True, False])
    df_filtered = df_filtered.groupby("trade_date").head(top_n).reset_index(drop=True)
    print(f"  After Top-{top_n} per day: {len(df_filtered):,}")

    if df_filtered.empty:
        print("No candidates after filters.")
        return

    results = []
    equity_curve = []
    yearly_results = []

    current_equity = INITIAL_CAPITAL
    current_year = None
    year_start_equity = INITIAL_CAPITAL

    mode_str = "COMPOUND" if compound else "FIXED"
    print(
        "Simulating trades "
        f"(OR={opening_range_minutes}m, entry_window={max_entry_minutes}m, fib={fib_entry}, osc={oscillator}, stop={stop_mode}, target={target_mode}, rr={rr:.1f}, "
        f"mode={mode_str}, vol_cap={max_pct_volume*100:.1f}%)..."
    )

    date_groups = df_filtered.groupby("trade_date")

    for trade_date, day_df in tqdm(date_groups, desc="Processing days"):
        trade_year = pd.to_datetime(trade_date).year
        if compound and current_year is not None and trade_year != current_year:
            year_pnl = current_equity - year_start_equity
            yearly_results.append(
                {
                    "year": current_year,
                    "start_equity": year_start_equity,
                    "end_equity": current_equity,
                    "year_pnl": year_pnl,
                    "year_return_pct": (year_pnl / year_start_equity) * 100 if year_start_equity > 0 else 0,
                }
            )
            year_start_equity = current_equity

        current_year = trade_year
        day_equity_start = current_equity
        day_pnl = 0.0

        num_trades_today = len(day_df)
        allocation_per_trade = current_equity / num_trades_today if num_trades_today > 0 else 0.0

        for _, row in day_df.iterrows():
            bars = deserialize_bars(row["bars_json"])

            if compound:
                position_size = allocation_per_trade
                apply_lev = True
            else:
                position_size = CAPITAL
                apply_lev = True

            sim = simulate_trade_orb_fib(
                bars,
                opening_range_minutes=opening_range_minutes,
                max_entry_minutes=max_entry_minutes,
                side_filter=side_filter,
                fib_entry=fib_entry,
                oscillator=oscillator,
                rsi_threshold=rsi_threshold,
                stop_mode=stop_mode,
                swing_buffer_pct=swing_buffer_pct,
                stop_buffer_pct=stop_buffer_pct,
                target_mode=target_mode,
                rr=rr,
                position_size=position_size,
                leverage=LEVERAGE,
                apply_leverage=apply_lev,
                spread_pct=SPREAD_PCT,
                max_pct_volume=max_pct_volume,
            )

            trade_pnl = sim.dollar_pnl or 0.0
            if compound and sim.entered:
                day_pnl += trade_pnl

            results.append(
                {
                    "trade_date": row["trade_date"],
                    "ticker": row["ticker"],
                    "side": "LONG" if sim.direction == 1 else "SHORT" if sim.direction == -1 else None,
                    "direction": sim.direction,
                    "rvol_rank": row.get("rvol_rank"),
                    "rvol": round(float(row["rvol"]), 2) if pd.notna(row.get("rvol")) else None,
                    "universe_direction": int(row.get("direction")) if pd.notna(row.get("direction")) else None,
                    "or_open": row.get("or_open"),
                    "or_high": row.get("or_high"),
                    "or_low": row.get("or_low"),
                    "or_close": row.get("or_close"),
                    "or_volume": row.get("or_volume"),
                    "breakout_time": sim.breakout_time,
                    "breakout_extreme": sim.breakout_extreme,
                    "session_anchor_a": sim.session_anchor_a,
                    "session_anchor_b": sim.session_anchor_b,
                    "fib_50": sim.fib_50,
                    "fib_618": sim.fib_618,
                    "fib_786": sim.fib_786,
                    "entry_price": sim.entry_price,
                    "stop_price": sim.stop_level,
                    "target_price": sim.target_level,
                    "exit_price": sim.exit_price,
                    "exit_reason": sim.exit_reason,
                    "entry_time": sim.entry_time,
                    "exit_time": sim.exit_time,
                    "pnl_pct": sim.pnl_pct,
                    "leverage": LEVERAGE,
                    "dollar_pnl": sim.dollar_pnl,
                    "base_dollar_pnl": sim.base_dollar_pnl,
                    "position_size": sim.position_size,
                    "atr_14": row.get("atr_14"),
                    "avg_volume_14": row.get("avg_volume_14"),
                    "prev_close": row.get("prev_close"),
                    "shares_outstanding": row.get("shares_outstanding"),
                    "is_capped": sim.is_capped,
                    "cap_ratio": sim.cap_ratio,
                    "target_shares": sim.target_shares,
                    "actual_shares": sim.actual_shares,
                    "max_allowed_shares": sim.max_allowed_shares,
                }
            )

            if verbose and sim.entered:
                print(f"{trade_date} {row['ticker']} {sim.exit_reason} pnl={sim.pnl_pct}% capped={sim.is_capped}")

        if compound:
            current_equity = day_equity_start + day_pnl
            if current_equity <= 0:
                print(f"\n⚠️ Account blown on {trade_date}! Equity: ${current_equity:.2f}")
                current_equity = 0.01

        equity_curve.append({"date": trade_date, "equity": round(current_equity, 2), "day_pnl": round(day_pnl, 2)})

    if compound and current_year is not None:
        year_pnl = current_equity - year_start_equity
        yearly_results.append(
            {
                "year": current_year,
                "start_equity": year_start_equity,
                "end_equity": current_equity,
                "year_pnl": year_pnl,
                "year_return_pct": (year_pnl / year_start_equity) * 100 if year_start_equity > 0 else 0,
            }
        )

    df_trades = pd.DataFrame(results)
    run_dir = resolve_run_dir(run_name, compound=compound)
    run_dir.mkdir(parents=True, exist_ok=True)

    run_config = {
        "run_name": run_name,
        "strategy": "orb_30m_fib",
        "universe_file": universe_path.name,
        "min_atr": float(min_atr),
        "min_volume": int(min_volume),
        "top_n": int(top_n),
        "side": side_filter,
        "compound": bool(compound),
        "daily_risk": float(daily_risk),
        "max_pct_volume": float(max_pct_volume),
        "leverage": float(LEVERAGE),
        "spread_pct": float(SPREAD_PCT),
        "opening_range_minutes": int(opening_range_minutes),
        "max_entry_minutes": int(max_entry_minutes),
        "fib_entry": fib_entry,
        "oscillator": oscillator,
        "rsi_threshold": float(rsi_threshold),
        "stop_mode": stop_mode,
        "swing_buffer_pct": float(swing_buffer_pct),
        "stop_buffer_pct": float(stop_buffer_pct),
        "target_mode": target_mode,
        "rr": float(rr),
    }
    (run_dir / "run_config.json").write_text(json.dumps(run_config, indent=2), encoding="utf-8")

    trades_path = run_dir / "simulated_trades.parquet"
    df_trades.to_parquet(trades_path, index=False)

    if compound:
        df_equity = pd.DataFrame(equity_curve)
        equity_path = run_dir / "equity_curve.parquet"
        df_equity.to_parquet(equity_path, index=False)

        df_yearly = pd.DataFrame(yearly_results)
        yearly_path = run_dir / "yearly_results.parquet"
        df_yearly.to_parquet(yearly_path, index=False)

    entered = df_trades[df_trades["exit_reason"] != "NO_ENTRY"].copy()
    daily_perf = []
    for date, group in entered.groupby("trade_date"):
        winners = group[group["pnl_pct"] > 0]
        losers = group[group["pnl_pct"] < 0]
        daily_perf.append(
            {
                "date": date,
                "trades": len(group),
                "entered": len(group),
                "winners": len(winners),
                "losers": len(losers),
                "total_base_pnl": float(group["base_dollar_pnl"].fillna(0).sum()),
                "total_leveraged_pnl": float(group["dollar_pnl"].fillna(0).sum()),
            }
        )

    df_daily = pd.DataFrame(daily_perf)
    daily_path = run_dir / "daily_performance.parquet"
    df_daily.to_parquet(daily_path, index=False)

    write_run_summary_md(run_dir)

    print("\nOutputs:")
    print(f"  {trades_path}")
    print(f"  {daily_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=str, required=True, help="Universe parquet filename (from data/backtest/orb/universe)")
    ap.add_argument("--top-n", type=int, default=20)
    ap.add_argument("--side", choices=["long", "short", "both"], default="both")
    ap.add_argument("--compound", action="store_true", help="Enable compounding")
    ap.add_argument("--daily-risk", type=float, default=0.10, help="Daily risk target (kept for parity with ORB fast_backtest)")
    ap.add_argument("--run-name", type=str, required=True)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--max-pct-volume", type=float, default=0.01, help="Max %% of daily volume allowed for position size (0.01 = 1%%)")

    ap.add_argument("--or-minutes", type=int, default=30, help="Opening range duration in minutes (default: 30)")
    ap.add_argument("--max-entry-minutes", type=int, default=120, help="Only allow breakouts/entries in the first N minutes after 09:30 (default: 120)")
    ap.add_argument("--fib-entry", choices=["50", "618", "either"], default="either", help="Fib level(s) allowed for entry")
    ap.add_argument("--osc", choices=["macd", "rsi", "none"], default="macd", help="Oscillator confirmation")
    ap.add_argument("--rsi-threshold", type=float, default=50.0, help="RSI threshold used when --osc=rsi")

    ap.add_argument("--stop-mode", choices=["fib_786", "swing"], default="fib_786")
    ap.add_argument("--swing-buffer-pct", type=float, default=0.001, help="Buffer for swing stop (0.001 = 0.1%%)")
    ap.add_argument("--stop-buffer-pct", type=float, default=0.0005, help="Extra buffer for fib/swing stops to represent 'just below/above' (default: 0.0005 = 0.05%%)")

    ap.add_argument("--target-mode", choices=["session_extreme", "rr"], default="session_extreme")
    ap.add_argument("--rr", type=float, default=2.0, help="R-multiple target when --target-mode=rr")

    args = ap.parse_args()

    # Mirror ORB/fast_backtest hardcoded filters
    MIN_ATR = 0.50
    MIN_VOLUME = 100_000

    if args.side == "both":
        side_filter = "both"
    else:
        side_filter = args.side

    universe_path = ORB_UNIVERSE_DIR / args.universe
    if not universe_path.exists():
        legacy_path = DATA_DIR / "backtest" / args.universe
        if legacy_path.exists():
            universe_path = legacy_path
        else:
            print(f"Universe not found: {universe_path}")
            return

    run_strategy(
        universe_path=universe_path,
        min_atr=MIN_ATR,
        min_volume=MIN_VOLUME,
        top_n=args.top_n,
        side_filter=side_filter,
        run_name=args.run_name,
        compound=bool(args.compound),
        daily_risk=float(args.daily_risk),
        verbose=bool(args.verbose),
        max_pct_volume=float(args.max_pct_volume),
        opening_range_minutes=int(args.or_minutes),
        fib_entry=str(args.fib_entry),
        oscillator=str(args.osc),
        rsi_threshold=float(args.rsi_threshold),
        stop_mode=str(args.stop_mode),
        swing_buffer_pct=float(args.swing_buffer_pct),
        stop_buffer_pct=float(args.stop_buffer_pct),
        target_mode=str(args.target_mode),
        rr=float(args.rr),
        max_entry_minutes=int(args.max_entry_minutes),
    )


if __name__ == "__main__":
    main()
