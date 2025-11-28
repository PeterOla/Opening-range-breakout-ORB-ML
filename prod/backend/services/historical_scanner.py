"""
Historical ORB Scanner Service.

Calculates Top 20 candidates for past dates using stored 5-min bars.
Shows hypothetical P&L based on entry/stop/EOD exit rules.

Data flow:
1. Check opening_ranges table for cached data
2. If not found, calculate from scratch:
   - Daily bars from DB (Polygon) for ATR, avg_volume
   - 5-min bars from Alpaca for OR and intraday simulation
"""
import json
import logging
from datetime import datetime, date, time, timedelta
from typing import Optional, AsyncGenerator
from zoneinfo import ZoneInfo
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from db.database import SessionLocal
from db.models import DailyBar, OpeningRange, Ticker, SimulatedTrade, OrderSide, ScannerCache
from services.universe import fetch_5min_bars, get_data_client
from services.data_sync import get_universe_with_metrics


logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
OR_END = time(9, 35)
MARKET_CLOSE = time(16, 0)
PREMARKET_START = time(4, 0)  # Pre-market opens 4:00 ET

# Data subscription flag - set to True when you have Alpaca Algo Trader Plus ($99/mo)
# This enables real-time SIP data for live scanning
HAS_REALTIME_SUBSCRIPTION = True

# Filter constants
MIN_PRICE = 5.0
MIN_ATR = 0.50
MIN_AVG_VOLUME = 1_000_000
MIN_RVOL = 1.0
TOP_N = 20


def _save_scanner_cache(
    db: Session,
    scan_date: datetime,
    status: str,
    candidates_count: int,
    trades_entered: int = 0,
    total_pnl_pct: float = None,
    winners: int = 0,
    losers: int = 0,
) -> None:
    """
    Save scanner cache entry to avoid refetching holidays/no-data days.
    """
    try:
        existing = db.query(ScannerCache).filter(
            func.date(ScannerCache.scan_date) == scan_date.date() if hasattr(scan_date, 'date') else scan_date
        ).first()
        
        if existing:
            existing.status = status
            existing.candidates_count = candidates_count
            existing.trades_entered = trades_entered
            existing.total_pnl_pct = total_pnl_pct
            existing.winners = winners
            existing.losers = losers
        else:
            cache_entry = ScannerCache(
                scan_date=scan_date,
                status=status,
                candidates_count=candidates_count,
                trades_entered=trades_entered,
                total_pnl_pct=total_pnl_pct,
                winners=winners,
                losers=losers,
            )
            db.add(cache_entry)
        
        db.commit()
        logger.info(f"[Cache] Saved {status} for {scan_date}")
    except Exception as e:
        logger.error(f"[Cache] Failed to save cache: {e}")
        db.rollback()


def _save_simulated_trades(
    candidates_with_pnl: list,
    target: date,
    metrics_lookup: dict,
    db: Session,
) -> int:
    """
    Save simulated trades to database for historical tracking.
    Uses upsert logic - updates if exists, inserts if not.
    
    Returns:
        Number of trades saved
    """
    saved_count = 0
    
    for c in candidates_with_pnl:
        symbol = c["symbol"]
        metrics = metrics_lookup.get(symbol, {})
        
        # Check if already exists
        existing = db.query(SimulatedTrade).filter(
            SimulatedTrade.trade_date == target,
            SimulatedTrade.ticker == symbol,
        ).first()
        
        if existing:
            # Update existing record
            existing.side = OrderSide.LONG if c["direction"] == 1 else OrderSide.SHORT
            existing.rvol_rank = c["rank"]
            existing.rvol = c["rvol"]
            existing.or_open = c["or_open"]
            existing.or_high = c["or_high"]
            existing.or_low = c["or_low"]
            existing.or_close = c["or_close"]
            existing.or_volume = c["or_volume"]
            existing.entry_price = c["entry_price"]
            existing.stop_price = c["stop_price"]
            existing.exit_price = c.get("exit_price")
            existing.exit_reason = c.get("exit_reason")
            existing.pnl_pct = c.get("pnl_pct")
            existing.day_change_pct = c.get("day_change_pct")
            existing.stop_distance_pct = c.get("stop_distance_pct")
            existing.leverage = c.get("leverage")
            existing.dollar_pnl = c.get("dollar_pnl")
            existing.atr_14 = metrics.get("atr_14")
            existing.avg_volume_14 = metrics.get("avg_volume_14")
            existing.prev_close = metrics.get("close")
        else:
            # Insert new record
            trade = SimulatedTrade(
                trade_date=target,
                ticker=symbol,
                side=OrderSide.LONG if c["direction"] == 1 else OrderSide.SHORT,
                rvol_rank=c["rank"],
                rvol=c["rvol"],
                or_open=c["or_open"],
                or_high=c["or_high"],
                or_low=c["or_low"],
                or_close=c["or_close"],
                or_volume=c["or_volume"],
                entry_price=c["entry_price"],
                stop_price=c["stop_price"],
                exit_price=c.get("exit_price"),
                exit_reason=c.get("exit_reason"),
                pnl_pct=c.get("pnl_pct"),
                day_change_pct=c.get("day_change_pct"),
                stop_distance_pct=c.get("stop_distance_pct"),
                leverage=c.get("leverage"),
                dollar_pnl=c.get("dollar_pnl"),
                atr_14=metrics.get("atr_14"),
                avg_volume_14=metrics.get("avg_volume_14"),
                prev_close=metrics.get("close"),
            )
            db.add(trade)
        
        saved_count += 1
    
    db.commit()
    logger.info(f"   💾 Saved {saved_count} simulated trades to database")
    return saved_count


def get_scanner_mode() -> dict:
    """
    Determine scanner mode based on current time (ET) and subscription status.
    
    Uses market calendar for dynamic close time (handles early close days like Black Friday).
    
    Timeline:
    - 00:00 - 04:00 ET: Show previous day results
    - 04:00 - 09:35 ET: Pre-market prep (universe candidates, no ORB yet)
    - 09:35 - CLOSE ET: Live session (requires real-time subscription) or fallback
    - CLOSE+ ET: Today's historical results with P&L
    
    Returns:
        dict with mode, target_date, and description
    """
    from services.market_calendar import get_market_calendar
    
    # Helper function defined first
    def get_previous_trading_day(d: date) -> date:
        prev = d - timedelta(days=1)
        while prev.weekday() >= 5:  # Saturday=5, Sunday=6
            prev -= timedelta(days=1)
        return prev
    
    now = datetime.now(ET)
    current_time = now.time()
    today = now.date()
    prev_day = get_previous_trading_day(today)
    
    # Get dynamic market close time from calendar
    calendar = get_market_calendar()
    market_close_time = calendar.get_market_close_time(today)
    
    # If market is closed today (holiday), use previous day
    if market_close_time is None:
        return {
            "mode": "historical_previous",
            "target_date": str(prev_day),
            "display_date": prev_day.strftime("%A, %d %B %Y"),
            "description": "Market closed today (holiday). Showing previous trading day.",
            "is_live": False,
            "show_pnl": True,
        }
    
    # Check if early close day
    schedule = calendar.get_calendar_for_date(today)
    is_early_close = schedule.get("early_close", False) if schedule else False
    
    # Before pre-market (00:00 - 04:00 ET)
    if current_time < PREMARKET_START:
        return {
            "mode": "historical_previous",
            "target_date": str(prev_day),
            "display_date": prev_day.strftime("%A, %d %B %Y"),
            "description": "Overnight. Showing previous trading day results.",
            "is_live": False,
            "show_pnl": True,
        }
    
    # Pre-market prep (04:00 - 09:35 ET)
    if PREMARKET_START <= current_time < OR_END:
        close_str = market_close_time.strftime("%H:%M")
        early_note = f" (Early close at {close_str})" if is_early_close else ""
        return {
            "mode": "premarket",
            "target_date": str(today),
            "display_date": today.strftime("%A, %d %B %Y"),
            "description": f"Pre-market prep. ORB forms at 9:35 ET.{early_note}",
            "is_live": False,
            "show_pnl": False,
            "premarket": True,
            "or_time": "09:35 ET",
            "early_close": is_early_close,
            "market_close": close_str if is_early_close else None,
        }
    
    # During market hours (09:35 - CLOSE ET) - using dynamic close time
    if OR_END <= current_time < market_close_time:
        close_str = market_close_time.strftime("%H:%M")
        if HAS_REALTIME_SUBSCRIPTION:
            # Real-time subscription available - show live data
            early_note = f" Early close at {close_str} ET." if is_early_close else ""
            return {
                "mode": "live",
                "target_date": str(today),
                "display_date": today.strftime("%A, %d %B %Y"),
                "description": f"🟢 Live trading session.{early_note}",
                "is_live": True,
                "show_pnl": False,
                "early_close": is_early_close,
                "market_close": close_str if is_early_close else None,
            }
        else:
            # No real-time subscription - show previous day with warning
            return {
                "mode": "historical_previous",
                "target_date": str(prev_day),
                "display_date": prev_day.strftime("%A, %d %B %Y"),
                "description": "⚠️ Live scanning requires Alpaca Algo Trader Plus ($99/mo). Showing previous day.",
                "is_live": False,
                "show_pnl": True,
                "live_disabled_reason": "Real-time SIP data requires Alpaca Algo Trader Plus subscription",
                "upgrade_url": "https://app.alpaca.markets/brokerage/dashboard/overview",
            }
    
    # After market close (CLOSE+ ET)
    close_str = market_close_time.strftime("%H:%M")
    early_note = f" (Early close at {close_str})" if is_early_close else ""
    return {
        "mode": "historical_today",
        "target_date": str(today),
        "display_date": today.strftime("%A, %d %B %Y"),
        "description": f"Market closed.{early_note} Showing today's results with P&L.",
        "is_live": False,
        "show_pnl": True,
    }


async def get_historical_top20(
    target_date: str,
    top_n: int = 20,
) -> dict:
    """
    Get historical Top 20 with full P&L calculation.
    
    For each candidate:
    1. Check if entry triggered (price reached OR_high for long, OR_low for short)
    2. If entered, track to stop or EOD close
    3. Calculate P&L
    
    Args:
        target_date: Date string "YYYY-MM-DD"
        top_n: Number of top candidates to return
        
    Returns:
        Dict with candidates and P&L summary
    """
    logger.info(f"📊 get_historical_top20 called for date={target_date}, top_n={top_n}")
    db = SessionLocal()
    
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
        logger.info(f"   Parsed target date: {target}")
        
        # First check if we have simulated trades already saved for this date
        from sqlalchemy import func
        saved_trades = db.query(SimulatedTrade).filter(
            func.date(SimulatedTrade.trade_date) == target
        ).order_by(SimulatedTrade.rvol_rank.asc()).limit(top_n).all()
        
        if saved_trades:
            logger.info(f"   ✅ Found {len(saved_trades)} cached simulated trades")
            return _build_response_from_saved_trades(saved_trades, target_date)
        
        # Check if we have opening ranges saved for this date
        saved_candidates = db.query(OpeningRange).filter(
            and_(
                OpeningRange.date == target,
                OpeningRange.passed_filters == True,
            )
        ).order_by(OpeningRange.rank.asc()).limit(top_n).all()
        
        logger.info(f"   Found {len(saved_candidates)} saved candidates in opening_ranges table")
        
        if saved_candidates:
            # Use saved data - need to fetch 5min bars for P&L calculation
            return await _process_saved_candidates(saved_candidates, target, target_date, db)
        
        # No saved data - calculate from scratch using Polygon daily + Alpaca 5-min
        logger.info(f"   ⚠️ No cached data. Calculating Top 20 from scratch...")
        return await _calculate_historical_top20(target, target_date, top_n, db)
        
    except Exception as e:
        import traceback
        logger.error(f"   ❌ Error in get_historical_top20: {e}")
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(e),
            "candidates": [],
        }
    finally:
        db.close()


async def get_historical_top20_stream(
    target_date: str,
    top_n: int = 20,
    force_refresh: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Stream progress while calculating historical Top 20.
    
    Yields SSE-formatted events:
    - progress: {step, message, percent, detail}
    - result: final data
    - error: if something fails
    
    Args:
        force_refresh: If True, bypass cache and refetch data
    """
    def sse_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    
    db = SessionLocal()
    
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
        target_dt = datetime.combine(target, time(0, 0))
        
        logger.info(f"[SSE] Streaming request for {target_date}")
        
        # Step 1: Check cache (skip if force_refresh)
        if force_refresh:
            yield sse_event("progress", {
                "step": 1,
                "message": "Force refresh - bypassing cache...",
                "percent": 5,
                "detail": "Will fetch fresh data from Alpaca",
            })
            # Delete existing cache entries for this date
            db.query(ScannerCache).filter(func.date(ScannerCache.scan_date) == target).delete()
            db.query(SimulatedTrade).filter(func.date(SimulatedTrade.trade_date) == target).delete()
            db.commit()
            logger.info(f"[SSE] Force refresh: cleared cache for {target_date}")
        else:
            yield sse_event("progress", {
                "step": 1,
                "message": "Checking database cache...",
                "percent": 5,
                "detail": f"Looking for saved trades on {target_date}",
            })
        
        # First check ScannerCache for "no data" days (holidays, etc.)
        cache_entry = db.query(ScannerCache).filter(
            func.date(ScannerCache.scan_date) == target
        ).first() if not force_refresh else None
        
        if cache_entry and cache_entry.status in ('no_data', 'holiday', 'no_candidates'):
            logger.info(f"[SSE] Cache hit: {cache_entry.status} for {target_date}")
            yield sse_event("progress", {
                "step": 1,
                "message": f"Cached: {cache_entry.status.replace('_', ' ').title()}",
                "percent": 100,
                "detail": f"✓ No trading data available for this date",
            })
            yield sse_event("result", {
                "status": cache_entry.status,
                "date": target_date,
                "message": f"No trading data for {target_date} (cached)",
                "candidates": [],
                "summary": None,
            })
            return
        
        # Check for saved SimulatedTrades (skip if force_refresh - already deleted above)
        saved_trades = [] if force_refresh else db.query(SimulatedTrade).filter(
            func.date(SimulatedTrade.trade_date) == target
        ).order_by(SimulatedTrade.rvol_rank.asc()).limit(top_n).all()
        
        logger.info(f"[SSE] Cache check: found {len(saved_trades)} trades for {target_date}")
        
        if saved_trades:
            yield sse_event("progress", {
                "step": 1,
                "message": "Found cached data!",
                "percent": 100,
                "detail": f"✓ {len(saved_trades)} trades loaded from cache",
            })
            result = _build_response_from_saved_trades(saved_trades, target_date)
            yield sse_event("result", result)
            return
        
        # Step 2: Get universe
        yield sse_event("progress", {
            "step": 2,
            "message": "Getting qualified universe...",
            "percent": 10,
            "detail": "Filtering symbols by price, volume, ATR",
        })
        
        universe = get_universe_with_metrics(
            min_price=MIN_PRICE,
            min_atr=MIN_ATR,
            min_avg_volume=MIN_AVG_VOLUME,
            db=db,
        )
        
        if not universe:
            yield sse_event("result", {
                "status": "no_universe",
                "date": target_date,
                "message": "No symbols pass base filters. Run data sync first.",
                "candidates": [],
                "summary": None,
            })
            return
        
        symbols = [u["symbol"] for u in universe]
        metrics_lookup = {u["symbol"]: u for u in universe}
        
        yield sse_event("progress", {
            "step": 2,
            "message": f"Found {len(symbols)} qualified symbols",
            "percent": 15,
            "detail": f"✓ Price ≥ $5, Vol ≥ 1M, ATR ≥ $0.50",
        })
        
        # Step 3: Fetch 5-min bars from Alpaca
        yield sse_event("progress", {
            "step": 3,
            "message": "Fetching 5-min bars from Alpaca...",
            "percent": 20,
            "detail": f"Requesting data for {len(symbols)} symbols (this takes ~30s)",
        })
        
        target_datetime = datetime.combine(target, time(0, 0), tzinfo=ET)
        fivemin_bars = await fetch_5min_bars(symbols, lookback_days=3, target_date=target_datetime)
        
        yield sse_event("progress", {
            "step": 3,
            "message": f"Received {len(fivemin_bars)} symbol bars",
            "percent": 60,
            "detail": f"✓ {len(fivemin_bars)}/{len(symbols)} symbols have data",
        })
        
        # Step 4: Compute RVOL & rank
        yield sse_event("progress", {
            "step": 4,
            "message": "Computing RVOL & ranking...",
            "percent": 65,
            "detail": "Extracting opening ranges, filtering by RVOL",
        })
        
        candidates = []
        for symbol in symbols:
            if symbol not in fivemin_bars:
                continue
            
            or_data = _extract_opening_range(fivemin_bars[symbol], target)
            if or_data is None:
                continue
            
            if or_data["direction"] == 0:
                continue
            
            if or_data["or_open"] < MIN_PRICE:
                continue
            
            metrics = metrics_lookup.get(symbol)
            if not metrics:
                continue
            
            avg_volume = metrics.get("avg_volume_14", 0)
            atr = metrics.get("atr_14", 0)
            
            if avg_volume > 0:
                rvol = (or_data["or_volume"] * 78) / avg_volume
            else:
                continue
            
            if rvol < MIN_RVOL:
                continue
            
            if or_data["direction"] == 1:
                entry_price = or_data["or_high"]
                stop_price = entry_price - (0.10 * atr)
            else:
                entry_price = or_data["or_low"]
                stop_price = entry_price + (0.10 * atr)
            
            candidates.append({
                "symbol": symbol,
                "price": metrics.get("close", 0),
                "atr": round(atr, 2),
                "avg_volume": int(avg_volume),
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
                "_bars_df": fivemin_bars[symbol],
            })
        
        if not candidates:
            # Save to cache so we don't refetch for holidays/no-data days
            _save_scanner_cache(db, target_dt, "no_candidates", 0)
            
            yield sse_event("result", {
                "status": "no_candidates",
                "date": target_date,
                "message": f"No candidates found after applying RVOL filter.",
                "candidates": [],
                "summary": None,
            })
            return
        
        candidates.sort(key=lambda x: x["rvol"], reverse=True)
        for i, c in enumerate(candidates):
            c["rank"] = i + 1
        top_candidates = candidates[:top_n]
        
        yield sse_event("progress", {
            "step": 4,
            "message": f"Found {len(candidates)} candidates, using Top {len(top_candidates)}",
            "percent": 75,
            "detail": f"✓ Ranked by RVOL",
        })
        
        # Step 5: Simulate trades
        yield sse_event("progress", {
            "step": 5,
            "message": "Simulating trades & P&L...",
            "percent": 80,
            "detail": f"Processing {len(top_candidates)} trades",
        })
        
        candidates_with_pnl = []
        total_pnl = 0
        total_dollar_pnl = 0
        total_base_dollar_pnl = 0  # P&L at 1x leverage
        total_leverage = 0
        winners = 0
        losers = 0
        trades_taken = 0
        
        for i, c in enumerate(top_candidates):
            bars_df = c.pop("_bars_df", None)
            
            result = simulate_trade(
                symbol=c["symbol"],
                direction=c["direction"],
                entry_level=c["entry_price"],
                stop_level=c["stop_price"],
                atr=c["atr"],
                target_date=target,
                bars_df=bars_df,
            )
            
            pnl_pct = result.get("pnl_pct", 0) if result else 0
            dollar_pnl = result.get("dollar_pnl", 0) if result else 0
            base_dollar_pnl = result.get("base_dollar_pnl", 0) if result else 0
            leverage = result.get("leverage", 0) if result else 0
            entered = result.get("entered", False) if result else False
            
            total_pnl += pnl_pct
            total_dollar_pnl += dollar_pnl
            total_base_dollar_pnl += base_dollar_pnl
            
            if entered:
                total_leverage += leverage
                trades_taken += 1
            
            if pnl_pct > 0:
                winners += 1
            elif pnl_pct < 0:
                losers += 1
            
            candidates_with_pnl.append({**c, **(result or {})})
            
            # Progress update every 5 trades
            if (i + 1) % 5 == 0 or i == len(top_candidates) - 1:
                yield sse_event("progress", {
                    "step": 5,
                    "message": f"Simulating trades... {i + 1}/{len(top_candidates)}",
                    "percent": 80 + int((i + 1) / len(top_candidates) * 15),
                    "detail": f"W:{winners} L:{losers}",
                })
        
        trades_taken = len([c for c in candidates_with_pnl if c.get("entered")])
        
        # Step 6: Save to database
        yield sse_event("progress", {
            "step": 6,
            "message": "Saving to database...",
            "percent": 98,
            "detail": f"Caching {len(candidates_with_pnl)} trades",
        })
        
        _save_simulated_trades(candidates_with_pnl, target, metrics_lookup, db)
        
        # Also save to scanner cache for quick lookup
        _save_scanner_cache(
            db, target_dt, "success",
            candidates_count=len(candidates_with_pnl),
            trades_entered=trades_taken,
            total_pnl_pct=round(total_pnl, 2),
            winners=winners,
            losers=losers,
        )
        
        yield sse_event("progress", {
            "step": 6,
            "message": "Complete!",
            "percent": 100,
            "detail": f"✓ {trades_taken} trades entered, {winners}W/{losers}L",
        })
        
        # Final result
        final_result = {
            "status": "success",
            "date": target_date,
            "mode": "historical_calculated",
            "candidates": candidates_with_pnl,
            "summary": {
                "total_candidates": len(candidates_with_pnl),
                "trades_entered": trades_taken,
                "winners": winners,
                "losers": losers,
                "win_rate": round(winners / trades_taken * 100, 1) if trades_taken > 0 else 0,
                "total_pnl_pct": round(total_pnl, 2),
                "avg_pnl_pct": round(total_pnl / trades_taken, 2) if trades_taken > 0 else 0,
                "total_dollar_pnl": round(total_dollar_pnl, 2),
                "base_dollar_pnl": round(total_base_dollar_pnl, 2),  # P&L at 1x leverage
                "avg_leverage": round(total_leverage / trades_taken, 2) if trades_taken > 0 else 0,
            },
        }
        
        yield sse_event("result", final_result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield sse_event("error", {"message": str(e)})
    finally:
        db.close()


def _build_response_from_saved_trades(trades: list, target_date: str) -> dict:
    """Build API response from cached SimulatedTrade records."""
    candidates = []
    total_pnl = 0
    total_dollar_pnl = 0
    total_base_dollar_pnl = 0
    winners = 0
    losers = 0
    trades_entered = 0
    total_leverage = 0
    
    for t in trades:
        entered = t.exit_reason and t.exit_reason != "NO_ENTRY"
        pnl = t.pnl_pct or 0
        dollar_pnl = t.dollar_pnl or 0
        leverage = t.leverage or 1.0
        
        # Calculate base P&L (at 1x leverage) from leveraged P&L
        base_dollar_pnl = dollar_pnl / leverage if leverage > 0 else 0
        
        if entered:
            trades_entered += 1
            total_leverage += leverage
            if pnl > 0:
                winners += 1
            elif pnl < 0:
                losers += 1
        
        total_pnl += pnl
        total_dollar_pnl += dollar_pnl
        total_base_dollar_pnl += base_dollar_pnl
        
        candidates.append({
            "symbol": t.ticker,
            "rank": t.rvol_rank,
            "direction": 1 if t.side.value == "LONG" else -1,
            "direction_label": t.side.value,
            "rvol": t.rvol,
            "atr": t.atr_14,
            "or_high": t.or_high,
            "or_low": t.or_low,
            "or_open": t.or_open,
            "or_close": t.or_close,
            "or_volume": int(t.or_volume),
            "entry_price": t.entry_price,
            "stop_price": t.stop_price,
            "entered": entered,
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason,
            "pnl_pct": pnl,
            "is_winner": pnl > 0 if entered else None,
            "day_change_pct": t.day_change_pct,
            "stop_distance_pct": t.stop_distance_pct,
            "leverage": leverage,
            "dollar_pnl": dollar_pnl,
            "base_dollar_pnl": round(base_dollar_pnl, 2),
        })
    
    return {
        "status": "success",
        "date": target_date,
        "mode": "historical_cached",
        "candidates": candidates,
        "summary": {
            "total_candidates": len(candidates),
            "trades_entered": trades_entered,
            "winners": winners,
            "losers": losers,
            "win_rate": round(winners / trades_entered * 100, 1) if trades_entered > 0 else 0,
            "total_pnl_pct": round(total_pnl, 2),
            "avg_pnl_pct": round(total_pnl / trades_entered, 2) if trades_entered > 0 else 0,
            "total_dollar_pnl": round(total_dollar_pnl, 2),
            "base_dollar_pnl": round(total_base_dollar_pnl, 2),
            "avg_leverage": round(total_leverage / trades_entered, 2) if trades_entered > 0 else 0,
        },
    }


async def _process_saved_candidates(
    saved_candidates: list,
    target: date,
    target_date: str,
    db: Session,
) -> dict:
    """Process candidates from cached opening_ranges table."""
    symbols = [c.symbol for c in saved_candidates]
    logger.info(f"   Symbols: {symbols[:5]}... (showing first 5)")
    
    # Fetch intraday data from Alpaca
    logger.info(f"   Fetching 5-min bars from Alpaca for {len(symbols)} symbols...")
    fivemin_bars = await fetch_5min_bars(symbols, lookback_days=5)
    logger.info(f"   Got 5-min bars for {len(fivemin_bars)} symbols")
    
    candidates_with_pnl = []
    total_pnl = 0
    winners = 0
    losers = 0
    
    for c in saved_candidates:
        result = simulate_trade(
            symbol=c.symbol,
            direction=c.direction,
            entry_level=c.entry_price,
            stop_level=c.stop_price,
            atr=c.atr,
            target_date=target,
            bars_df=fivemin_bars.get(c.symbol),
        )
        
        pnl_pct = result.get("pnl_pct", 0) if result else 0
        total_pnl += pnl_pct
        if pnl_pct > 0:
            winners += 1
        elif pnl_pct < 0:
            losers += 1
        
        candidates_with_pnl.append({
            "symbol": c.symbol,
            "rank": c.rank,
            "direction": c.direction,
            "direction_label": "LONG" if c.direction == 1 else "SHORT",
            "rvol": c.rvol,
            "atr": c.atr,
            "or_high": c.or_high,
            "or_low": c.or_low,
            "entry_price": c.entry_price,
            "stop_price": c.stop_price,
            **(result or {}),
        })
    
    trades_taken = len([c for c in candidates_with_pnl if c.get("entered")])
    logger.info(f"   ✅ Processed {len(candidates_with_pnl)} candidates, {trades_taken} entered, {winners} winners, {losers} losers")
    
    return {
        "status": "success",
        "date": target_date,
        "mode": "historical_cached",
        "candidates": candidates_with_pnl,
        "summary": {
            "total_candidates": len(candidates_with_pnl),
            "trades_entered": trades_taken,
            "winners": winners,
            "losers": losers,
            "win_rate": round(winners / trades_taken * 100, 1) if trades_taken > 0 else 0,
            "total_pnl_pct": round(total_pnl, 2),
            "avg_pnl_pct": round(total_pnl / trades_taken, 2) if trades_taken > 0 else 0,
        },
    }


async def _calculate_historical_top20(
    target: date,
    target_date: str,
    top_n: int,
    db: Session,
) -> dict:
    """
    Calculate Top 20 from scratch for a historical date.
    
    Uses:
    - Daily bars from DB (Polygon) for ATR, avg_volume, close
    - 5-min bars from Alpaca for OR calculation and trade simulation
    """
    # Step 1: Get qualified universe from daily_bars (closest date to target)
    logger.info(f"   Step 1: Getting qualified universe from daily_bars...")
    
    # Find the trading day on or just before target for metrics
    # (ATR/avg_volume should be from day BEFORE the trade date)
    metrics_date = target - timedelta(days=1)
    
    # Get symbols that pass base filters
    universe = get_universe_with_metrics(
        min_price=MIN_PRICE,
        min_atr=MIN_ATR,
        min_avg_volume=MIN_AVG_VOLUME,
        db=db,
    )
    
    if not universe:
        logger.warning(f"   No symbols pass base filters")
        return {
            "status": "no_universe",
            "date": target_date,
            "message": "No symbols in database pass base filters. Run data sync first.",
            "candidates": [],
            "summary": None,
        }
    
    symbols = [u["symbol"] for u in universe]
    metrics_lookup = {u["symbol"]: u for u in universe}
    logger.info(f"   Found {len(symbols)} symbols passing base filters")
    
    # Step 2: Fetch 5-min bars from Alpaca for target date
    logger.info(f"   Step 2: Fetching 5-min bars from Alpaca for {len(symbols)} symbols...")
    
    # Convert target date to datetime for Alpaca API
    target_datetime = datetime.combine(target, time(0, 0), tzinfo=ET)
    
    # Fetch with target date so we get the right historical data
    fivemin_bars = await fetch_5min_bars(symbols, lookback_days=3, target_date=target_datetime)
    logger.info(f"   Got 5-min data for {len(fivemin_bars)} symbols")
    
    # Step 3: Extract OR bar, compute RVOL, filter
    logger.info(f"   Step 3: Computing OR and RVOL...")
    candidates = []
    
    for symbol in symbols:
        if symbol not in fivemin_bars:
            continue
        
        or_data = _extract_opening_range(fivemin_bars[symbol], target)
        if or_data is None:
            continue
        
        # Skip doji candles
        if or_data["direction"] == 0:
            continue
        
        # Filter: Opening price must be >= $5 (per strategy rules)
        if or_data["or_open"] < MIN_PRICE:
            continue
        
        metrics = metrics_lookup.get(symbol)
        if not metrics:
            continue
        
        avg_volume = metrics.get("avg_volume_14", 0)
        atr = metrics.get("atr_14", 0)
        
        # Compute RVOL: (OR_volume extrapolated to full day) / avg_daily_volume
        # OR is 5 min, full day is 78 five-min bars
        if avg_volume > 0:
            rvol = (or_data["or_volume"] * 78) / avg_volume
        else:
            continue
        
        # Apply RVOL filter
        if rvol < MIN_RVOL:
            continue
        
        # Calculate entry and stop
        if or_data["direction"] == 1:  # Long
            entry_price = or_data["or_high"]
            stop_price = entry_price - (0.10 * atr)
        else:  # Short
            entry_price = or_data["or_low"]
            stop_price = entry_price + (0.10 * atr)
        
        candidates.append({
            "symbol": symbol,
            "price": metrics.get("close", 0),
            "atr": round(atr, 2),
            "avg_volume": int(avg_volume),
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
            "_bars_df": fivemin_bars[symbol],  # Keep for simulation
        })
    
    logger.info(f"   Found {len(candidates)} candidates after RVOL filter (>= {MIN_RVOL})")
    
    if not candidates:
        return {
            "status": "no_candidates",
            "date": target_date,
            "message": f"No candidates found for {target_date} after applying filters.",
            "candidates": [],
            "summary": None,
        }
    
    # Step 4: Rank by RVOL and take top N
    candidates.sort(key=lambda x: x["rvol"], reverse=True)
    
    for i, c in enumerate(candidates):
        c["rank"] = i + 1
    
    top_candidates = candidates[:top_n]
    logger.info(f"   Top {len(top_candidates)} candidates selected")
    
    # Step 5: Simulate trades and calculate P&L
    logger.info(f"   Step 4: Simulating trades...")
    candidates_with_pnl = []
    total_pnl = 0
    total_dollar_pnl = 0
    total_leverage = 0
    winners = 0
    losers = 0
    
    for c in top_candidates:
        bars_df = c.pop("_bars_df", None)
        
        result = simulate_trade(
            symbol=c["symbol"],
            direction=c["direction"],
            entry_level=c["entry_price"],
            stop_level=c["stop_price"],
            atr=c["atr"],
            target_date=target,
            bars_df=bars_df,
        )
        
        pnl_pct = result.get("pnl_pct", 0) if result else 0
        dollar_pnl = result.get("dollar_pnl", 0) if result else 0
        leverage = result.get("leverage", 0) if result else 0
        entered = result.get("entered", False) if result else False
        
        total_pnl += pnl_pct
        total_dollar_pnl += dollar_pnl
        
        if entered:
            total_leverage += leverage
        
        if pnl_pct > 0:
            winners += 1
        elif pnl_pct < 0:
            losers += 1
        
        candidates_with_pnl.append({
            **c,
            **(result or {}),
        })
    
    trades_taken = len([c for c in candidates_with_pnl if c.get("entered")])
    logger.info(f"   ✅ Calculated {len(candidates_with_pnl)} candidates, {trades_taken} entered, {winners} W / {losers} L")
    
    # Step 5: Save simulated trades to database
    _save_simulated_trades(candidates_with_pnl, target, metrics_lookup, db)
    
    return {
        "status": "success",
        "date": target_date,
        "mode": "historical_calculated",
        "candidates": candidates_with_pnl,
        "summary": {
            "total_candidates": len(candidates_with_pnl),
            "trades_entered": trades_taken,
            "winners": winners,
            "losers": losers,
            "win_rate": round(winners / trades_taken * 100, 1) if trades_taken > 0 else 0,
            "total_pnl_pct": round(total_pnl, 2),
            "avg_pnl_pct": round(total_pnl / trades_taken, 2) if trades_taken > 0 else 0,
            "total_dollar_pnl": round(total_dollar_pnl, 2),
            "avg_leverage": round(total_leverage / trades_taken, 2) if trades_taken > 0 else 0,
        },
    }


def _extract_opening_range(df: pd.DataFrame, target_date: date) -> Optional[dict]:
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
    
    # Filter to target date's 9:30 bar
    mask = (
        (df["date"] == target_date) & 
        (df["timestamp"].dt.hour == 9) & 
        (df["timestamp"].dt.minute == 30)
    )
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
    }


def simulate_trade(
    symbol: str,
    direction: int,
    entry_level: float,
    stop_level: float,
    atr: float,
    target_date: date,
    bars_df: Optional[pd.DataFrame],
) -> Optional[dict]:
    """
    Simulate a single trade using intraday bars.
    
    Rules:
    - Entry: Stop order at entry_level (OR_high for long, OR_low for short)
    - Exit: Stop-loss hit OR EOD (whichever comes first)
    
    Returns:
        Dict with entry/exit details and P&L, or None if no bars
    """
    if bars_df is None or bars_df.empty:
        return {
            "entered": False,
            "exit_reason": "NO_DATA",
            "pnl_pct": 0,
        }
    
    df = bars_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    
    # Convert to ET
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert(ET)
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert(ET)
    
    df["date"] = df["timestamp"].dt.date
    
    # Filter to target date, after 9:35 ET
    day_bars = df[
        (df["date"] == target_date) & 
        (df["timestamp"].dt.time > OR_END)
    ].sort_values("timestamp")
    
    if day_bars.empty:
        return {
            "entered": False,
            "exit_reason": "NO_BARS",
            "pnl_pct": 0,
            "day_change_pct": None,
        }
    
    # Calculate day's price change (open to close)
    first_bar = day_bars.iloc[0]
    last_bar = day_bars.iloc[-1]
    day_open = float(first_bar["open"])
    day_close = float(last_bar["close"])
    day_change_pct = round((day_close - day_open) / day_open * 100, 2) if day_open > 0 else 0
    
    in_trade = False
    entry_price = None
    entry_time = None
    exit_price = None
    exit_time = None
    exit_reason = None
    
    for _, bar in day_bars.iterrows():
        if not in_trade:
            # Check for entry
            if direction == 1:  # Long
                if bar["high"] >= entry_level:
                    in_trade = True
                    entry_price = entry_level
                    entry_time = bar["timestamp"]
            else:  # Short
                if bar["low"] <= entry_level:
                    in_trade = True
                    entry_price = entry_level
                    entry_time = bar["timestamp"]
        else:
            # Check for stop hit
            if direction == 1:  # Long - stop is below
                if bar["low"] <= stop_level:
                    exit_price = stop_level
                    exit_time = bar["timestamp"]
                    exit_reason = "STOP_LOSS"
                    break
            else:  # Short - stop is above
                if bar["high"] >= stop_level:
                    exit_price = stop_level
                    exit_time = bar["timestamp"]
                    exit_reason = "STOP_LOSS"
                    break
    
    # If still in trade, exit at EOD
    if in_trade and exit_price is None:
        last_bar = day_bars.iloc[-1]
        exit_price = float(last_bar["close"])  # Convert from numpy
        exit_time = last_bar["timestamp"]
        exit_reason = "EOD"
    
    # Position sizing constants - Fixed 2x leverage
    CAPITAL = 1000.0  # $1000 capital
    LEVERAGE = 2.0    # Fixed 2x leverage
    
    # Calculate stop distance as % of entry price
    stop_distance_pct = abs(entry_level - stop_level) / entry_level * 100 if entry_level > 0 else 0
    
    # Fixed 2x leverage position sizing
    position_value = CAPITAL * LEVERAGE  # $2000 position
    shares = position_value / entry_level if entry_level > 0 else 0
    leverage = LEVERAGE
    
    # Calculate P&L
    if in_trade and entry_price and exit_price:
        if direction == 1:  # Long
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:  # Short
            pnl_pct = (entry_price - exit_price) / entry_price * 100
        
        # Dollar P&L = shares × price move (with actual leverage)
        price_move = (exit_price - entry_price) * direction
        dollar_pnl = shares * price_move
        
        # Base P&L at 1x leverage (for comparison)
        base_shares = CAPITAL / entry_level  # 1x leverage = $1000 worth
        base_dollar_pnl = base_shares * price_move
        
        return {
            "entered": True,
            "entry_price_actual": round(float(entry_price), 2),
            "entry_time": entry_time.strftime("%H:%M") if entry_time else None,
            "exit_price": round(float(exit_price), 2),
            "exit_time": exit_time.strftime("%H:%M") if exit_time else None,
            "exit_reason": exit_reason,
            "pnl_pct": round(float(pnl_pct), 2),
            "is_winner": pnl_pct > 0,
            "day_change_pct": day_change_pct,
            "stop_distance_pct": round(float(stop_distance_pct), 3),
            "leverage": round(float(leverage), 2),
            "dollar_pnl": round(float(dollar_pnl), 2),
            "base_dollar_pnl": round(float(base_dollar_pnl), 2),  # P&L at 1x leverage
        }
    
    return {
        "entered": False,
        "exit_reason": "NO_ENTRY",
        "pnl_pct": 0,
        "day_change_pct": day_change_pct,
        "stop_distance_pct": round(float(stop_distance_pct), 3),
        "leverage": round(float(leverage), 2),
        "dollar_pnl": 0,
        "base_dollar_pnl": 0,
    }


async def get_premarket_candidates() -> dict:
    """
    Get universe candidates for pre-market (04:00 - 09:35 ET).
    
    Shows the daily-metrics-filtered universe before ORB forms.
    These are the stocks that COULD make Top 20 once RVOL is calculated.
    
    Returns:
        dict with universe candidates and pre-market status
    """
    db: Session = SessionLocal()
    try:
        today = datetime.now(ET).date()
        current_time = datetime.now(ET).time()
        
        # Calculate time until ORB (9:35 ET)
        or_datetime = datetime.combine(today, OR_END).replace(tzinfo=ET)
        now = datetime.now(ET)
        time_until_or = or_datetime - now
        
        if time_until_or.total_seconds() < 0:
            # ORB already formed
            return {
                "status": "orb_formed",
                "message": "ORB has already formed. Use the main scanner.",
                "or_time": "09:35 ET",
            }
        
        minutes_until = int(time_until_or.total_seconds() / 60)
        hours_until = minutes_until // 60
        mins_remaining = minutes_until % 60
        
        # Get universe from data_sync (filtered by ATR, volume, price)
        universe = await get_universe_with_metrics(db, today)
        
        if not universe:
            return {
                "status": "no_data",
                "message": "No universe data available. Daily bars may not be synced.",
                "time_until_or": f"{hours_until}h {mins_remaining}m",
            }
        
        # Build candidate list (sorted by avg_volume as proxy until we have RVOL)
        candidates = []
        for ticker, metrics in universe.items():
            # Apply same filters as historical scanner
            if metrics.get("avg_volume_20", 0) < MIN_AVG_VOLUME:
                continue
            if metrics.get("atr_14", 0) < MIN_ATR:
                continue
            # Note: Can't filter by opening price yet - no OR data
            
            candidates.append({
                "symbol": ticker,
                "atr": round(metrics.get("atr_14", 0), 2),
                "avg_volume": int(metrics.get("avg_volume_20", 0)),
                "last_close": round(metrics.get("last_close", 0), 2),
                # RVOL will be calculated once pre-market volume comes in
                "rvol": None,  
                "status": "awaiting_rvol",
            })
        
        # Sort by avg_volume (best proxy for importance until RVOL)
        candidates.sort(key=lambda x: x["avg_volume"], reverse=True)
        
        # Add rank
        for i, c in enumerate(candidates):
            c["rank"] = i + 1
        
        return {
            "status": "premarket",
            "date": str(today),
            "display_date": today.strftime("%A, %d %B %Y"),
            "time_until_or": f"{hours_until}h {mins_remaining}m" if hours_until > 0 else f"{minutes_until}m",
            "or_time": "09:35 ET",
            "message": f"Pre-market prep. {len(candidates)} candidates in universe. ORB forms at 09:35 ET.",
            "universe_count": len(candidates),
            "candidates": candidates[:50],  # Show top 50 by avg volume
            "note": "Ranked by avg volume (RVOL not available until market open)",
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
        }
    finally:
        db.close()
