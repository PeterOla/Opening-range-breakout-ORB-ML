"""
Unified Live ORB Execution
Supports both Live Trading and Historical Verification.

Usage:
  Live:   python ORB_Live_Trader/main.py
  Verify: python ORB_Live_Trader/main.py --verify --date 2021-02-22
"""
import sys
import os
import argparse
import pandas as pd
import duckdb
import pytz
import json
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from typing import List, Optional
import time as time_module
import logging
import logging.handlers

# ORB_ROOT is ORB_Live_Trader (1 level up from main.py)
ORB_ROOT = Path(__file__).resolve().parent
# PROJECT_ROOT is ../Opening Range Breakout (ORB) (Repo Root)
PROJECT_ROOT = ORB_ROOT.parent

# Load Env as early as possible
from dotenv import load_dotenv
load_dotenv(ORB_ROOT / "config" / ".env")

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(ORB_ROOT))

# Abstractions
from ORB_Live_Trader.core.execution import Clock, Broker
from ORB_Live_Trader.core.simulation import SimClock, SimBroker
from ORB_Live_Trader.core.live_impl import LiveClock, TradeZeroBroker

# Backtest Utils
from ORB_Live_Trader.backtest.engine import deserialize_bars

# TradeZero Import (only needed for live)
try:
    BACKEND_PATH = PROJECT_ROOT / "prod" / "backend"
    sys.path.insert(0, str(BACKEND_PATH))
    from execution.tradezero.client import TradeZero
except ImportError:
    pass # Expected in some envs if not live

# Logging
# Global Logger Setup
logs_dir = ORB_ROOT / "logs"
logs_dir.mkdir(exist_ok=True)

def setup_daily_logging(verify_date: str = None):
    """Configures a daily log file for trading review."""
    today_str = verify_date if verify_date else datetime.now().strftime("%Y-%m-%d")
    trading_dir = logs_dir / "trading"
    trading_dir.mkdir(exist_ok=True)
    log_file = trading_dir / f"trading_{today_str}.log"
    
    # Create logger
    logger = logging.getLogger("ORB_Trader")
    logger.setLevel(logging.INFO)
    
    # Clean handlers to avoid duplication if called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()
        
    # File Handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(fh)
    
    # Console Handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(ch)
    
    return logger

# Initialize logger (will be re-configured once we know if it's verify mode)
trading_logger = setup_daily_logging()

def log(msg: str, level: str = "INFO", clock: Clock = None):
    """
    Unified logging that supports both console and daily persistent files.
    """
    ts = None
    if clock:
        ts = clock.now().strftime("%Y-%m-%d %H:%M:%S")
    else:
        # Fallback to current system time if no market clock provided
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Print to console for immediate visibility (especially for sim time)
    print(f"[{ts}] [{level}] {msg}", flush=True)
    
    # 2. Write to persistent trading_logger
    lvl = getattr(logging, level.upper(), logging.INFO)
    log_msg = f"[{ts}] {msg}"
    trading_logger.log(lvl, log_msg)


# Pipeline
import ORB_Live_Trader.pipeline.live_pipeline as pipeline

# -----------------------------------------------------------------------------
# Safety & Fail-Safes
# -----------------------------------------------------------------------------

state_dir = ORB_ROOT / "state"
state_dir.mkdir(exist_ok=True)

KILL_SWITCH_FILE = state_dir / "orb_kill_switch.lock"

def check_kill_switch() -> bool:
    """Check if the manual kill switch is active."""
    return KILL_SWITCH_FILE.exists()

def activate_kill_switch(reason: str):
    """Engage the kill switch and log the reason."""
    log(f"!!! KILL SWITCH ACTIVATED !!! Reason: {reason}", level="CRITICAL")
    KILL_SWITCH_FILE.touch()

def safe_place_market_order(broker: Broker, symbol: str, side: str, shares: int, clock: Clock) -> Optional[str]:
    """
    Places a Market order with automatic fallback to Limit if rejected (R78).
    """
    # 1. Check Kill Switch (Only block BUYS)
    if side.upper() == 'BUY' and check_kill_switch():
        log(f"Aborting order for {symbol} - Kill Switch Active.", level="WARNING", clock=clock)
        return None

    # 2. Attempt Market Order
    order_id = broker.place_order(symbol, side, 'MARKET', shares)
    
    # SimBroker or other brokers might return ID immediately. 
    # In live TradeZero, we'd check notifications for R78.
    # For this implementation's abstraction, we'll assume the broker 
    # handles the R78 rejection internally or we check the status.
    
    if not order_id:
        log(f"Market order failed/rejected for {symbol}. Attempting LIMIT Fallback (R78)...", level="WARNING", clock=clock)
        # Fallback: Get Quote and place Limit
        quote = broker.get_quote(symbol)
        price = quote['ask'] if side == 'BUY' else quote['bid']
        if price > 0:
            order_id = broker.place_order(symbol, side, 'LIMIT', shares, price)
            if order_id:
                log(f"LIMIT Fallback success for {symbol} @ {price}", clock=clock)
            else:
                log(f"CRITICAL: Limit fallback also failed for {symbol}.", level="ERROR", clock=clock)
        else:
            log(f"CRITICAL: Could not get quote for limit fallback on {symbol}.", level="ERROR", clock=clock)
            
    return order_id

def safe_place_buy_stop(broker: Broker, symbol: str, shares: int, stop_price: float, clock: Clock) -> Optional[str]:
    """
    Places a BUY STOP order at the Opening Range High.
    Unlike Market orders, Stop orders are resting orders on the broker's books.
    """
    if check_kill_switch():
        log(f"Aborting Stop order for {symbol} - Kill Switch Active.", level="WARNING", clock=clock)
        return None

    # TradeZero/Broker specific: 
    # Use 'STOP' type logic.
    order_id = broker.place_order(symbol, 'BUY', 'STOP', shares, stop_price)
    
    if order_id:
        log(f"BUY STOP placed for {symbol} @ {stop_price} (Passively waiting for breakout)", clock=clock)
    else:
        log(f"ERROR: Failed to place BUY STOP for {symbol}.", level="ERROR", clock=clock)
        
    return order_id

def safe_place_sell_stop(broker: Broker, symbol: str, shares: float, stop_price: float, clock: Clock) -> Optional[str]:
    """
    Places a resting SELL STOP order on the broker's books.
    This protects the position even if the script crashes or loses connection.
    """
    # Only block BUYS? Actually, for sell stops, we want to allow them if they are for protection.
    # But if the user manually set a kill switch, they might want to stop ALL orders.
    # However, for strategy safety, we allow protective SELL STOPS.
    if check_kill_switch():
        log(f"ALERT: Placing protective STOP for {symbol} despite Kill Switch.", level="WARNING", clock=clock)

    # PREVENTION: Check if we already have a protective SELL STOP for this symbol
    existing = broker.get_active_orders()
    if existing:
        for o in existing:
            # Map side safely
            side_key = next((k for k in o.keys() if 'side' in k.lower()), 'side')
            side_val = str(o.get(side_key, '')).upper()
            if o.get('symbol') == symbol and ('SELL' in side_val or 'SHORT' in side_val):
                log(f"SKIP: Protective order already exists for {symbol} (Ref: {o.get('ref_number')})", clock=clock)
                return o.get('ref_number')

    # TradeZero/Broker specific logic for protective stops
    order_id = broker.place_order(symbol, 'SELL', 'STOP', shares, stop_price)
    
    if order_id:
        log(f"RESTING STOP-LOSS placed for {symbol} @ {stop_price}", clock=clock)
    else:
        log(f"CRITICAL ERROR: Failed to place resting stop-loss for {symbol}.", level="CRITICAL", clock=clock)
        # Note: Caller is responsible for tiered repair or manual intervention.
        
    return order_id

# -----------------------------------------------------------------------------
# Core Logic (Unified)
# -----------------------------------------------------------------------------

def run_trading_session(clock: Clock, broker: Broker, pool_df: pd.DataFrame, con: duckdb.DuckDBPyConnection = None, equity: float = 0, start_bp: float = 0):
    """
    Main Event Loop:
    1. 09:30 - 09:35: Wait for OR Candle
    2. 09:35:05: Perform Refinement (Green Candles + Top 5 RVOL)
    3. 09:35 - 16:00: Monitor Breakouts & Stops
    """
    et_tz = pytz.timezone("America/New_York")
    current_date = clock.now().date()
    market_open = et_tz.localize(datetime.combine(current_date, dt_time(9, 30)))
    or_cutoff = et_tz.localize(datetime.combine(current_date, dt_time(9, 35)))
    market_close = et_tz.localize(datetime.combine(current_date, dt_time(15, 55)))
    
    state_file = ORB_ROOT / "state" / f"session_{current_date}.json"
    
    active_orders = [] 
    open_positions = [] 
    triggered_symbols = set()
    
    # PNL Tracking
    realized_pnl = 0.0
    fills_tracker = {} # symbol -> {'entry_price': avg_price, 'shares': shares}
    
    refined_universe = None # DataFrame representing the final Top 5
    last_audit_time = 0
    last_heartbeat_time = 0
    last_notif_time = 0
    notif_history = set() # Track seen notifications to avoid spam

    # --- DURABLE STATE RECOVERY (Restart-Safety) ---
    if state_file.exists():
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
                active_orders = state.get('active_orders', [])
                open_positions = state.get('open_positions', [])
                fills_tracker = state.get('fills_tracker', {})
                realized_pnl = state.get('realized_pnl', 0.0)
                triggered_symbols = set(state.get('triggered_symbols', []))
                # Note: refined_universe is not easily JSON serializable, 
                # but if we have active_orders, we've already done refinement.
                if active_orders or open_positions:
                    refined_universe = pd.DataFrame() # Sentinel to skip refinement
                log(f"RECOVERY: Loaded session state from {state_file.name}", clock=clock)
        except Exception as e:
            log(f"RECOVERY ERROR: Failed to load state: {e}", level="ERROR", clock=clock)

    if not isinstance(broker, SimBroker):
        # Always cross-check with broker reality
        log("DURING START: Cross-checking state with broker reality...", clock=clock)
        current_portfolio = broker.get_positions()
        active_broker_orders = broker.get_active_orders()
        
        # 1. Ensure all broker positions are in our tracker
        for p in current_portfolio:
            sym = p['symbol']
            qty = float(p.get('qty', 0))
            if qty <= 0: continue
            
            if sym not in [pos['symbol'] for pos in open_positions]:
                log(f"RECOVERY: Found untracked position for {sym}. Adding to monitoring...", clock=clock)
                # Fallback: if we don't know the stop price, we'll try to get it from daily parquet later
                open_positions.append({
                    'symbol': sym,
                    'shares': qty,
                    'stop_price': 0.0,
                    'stop_order_id': "",
                    'repair_idx': 0 # Index into tiered multipliers [0.05, 0.08, 0.10]
                })
                fills_tracker[sym] = {'entry_price': float(p.get('avg_price', 0)), 'shares': qty}

        # 2. Update stop order IDs from active broker orders
        active_refs = {}
        for o in active_broker_orders:
            side_key = next((k for k in o.keys() if 'side' in k.lower()), None)
            side_val = str(o.get(side_key, '')).upper() if side_key else ''
            if 'SELL' in side_val:
                active_refs[o.get('symbol')] = o.get('ref_number')
        
        for pos in open_positions:
            if pos['symbol'] in active_refs:
                pos['stop_order_id'] = active_refs[pos['symbol']]
                if pos['stop_price'] <= 0:
                    # Recover stop price from broker order if possible
                    order = next(o for o in active_broker_orders if o['ref_number'] == pos['stop_order_id'])
                    pos['stop_price'] = float(order.get('price', 0) or order.get('stop_price', 0))
            
            # Enrich with ATR and OR High for Tiered Repair
            if (pos.get('atr_14', 0) <= 0 or pos.get('or_high', 0) <= 0) and not pool_df.empty:
                if pos['symbol'] in pool_df['symbol'].values:
                    row = pool_df[pool_df['symbol'] == pos['symbol']].iloc[0]
                    # Note: pool_df has atr_14 and or_high-related data
                    pos['atr_14'] = float(row.get('atr_14', 0))
                    # or_high and stop_price logic below...

        # 3. Final Fallback: If or_high/stop_price still missing, re-fetch opening bars
        missing_metadata = [p for p in open_positions if p.get('or_high', 0) <= 0 or p['stop_price'] <= 0]
        if missing_metadata:
            log(f"RECOVERY: Fetching opening bars for {len(missing_metadata)} symbols to reconstruct stops...", clock=clock)
            from ORB_Live_Trader.pipeline.live_pipeline import fetch_opening_bars
            from ORB_Live_Trader.backtest.universe import extract_or
            
            m_symbols = [p['symbol'] for p in missing_metadata]
            m_bars = fetch_opening_bars(m_symbols, current_date)
            
            for p in missing_metadata:
                b_df = m_bars[m_bars['symbol'] == p['symbol']]
                if not b_df.empty:
                    or_data = extract_or(b_df)
                    if or_data:
                        p['or_high'] = or_data['or_high']
                        if p['stop_price'] <= 0 and p.get('atr_14', 0) > 0:
                            p['stop_price'] = or_data['or_high'] - (0.05 * p['atr_14'])
                            log(f"RECOVERY: Reconstructed stop for {p['symbol']} @ {p['stop_price']:.4f}", clock=clock)

    # Main Loop
    while clock.now() < market_close:
        now = clock.now()
        
        # 0. Kill Switch Check
        if check_kill_switch():
            log("Manual Kill Switch Detected. Aborting session and flattening...", level="CRITICAL", clock=clock)
            break
        
        if now < market_open:
            clock.sleep(10)
            continue

        # 1. WAIT FOR OPENING RANGE (09:30 - 09:35)
        if now < or_cutoff:
            # Heartbeat if live to prevent timeout
            if not isinstance(broker, SimBroker):
                 pass # Subs handled by client
            clock.sleep(5)
            continue
            
        # 2. REFINEMENT PHASE (Once at or after 09:35:01)
        if refined_universe is None:
            log("5-Min Opening Range Complete. Identifying Long Candidates...", clock=clock)
            from ORB_Live_Trader.backtest.universe import extract_or
            from ORB_Live_Trader.pipeline.live_pipeline import fetch_opening_bars
            
            symbols = pool_df['symbol'].tolist()
            bars_map = {}
            
            if isinstance(broker, SimBroker):
                # Verification mode uses local bars
                bars_map = {s: broker.bars.get(s) for s in symbols if s in broker.bars}
            else:
                # Live mode fetches from Alpaca
                live_bars_df = fetch_opening_bars(symbols, current_date)
                # Convert DF to map of minimal bar DFs for extract_or compatibility
                for _, b_row in live_bars_df.iterrows():
                    bars_map[b_row['symbol']] = pd.DataFrame([b_row]).assign(time=dt_time(9, 30))

            final_list = []
            for _, row in pool_df.iterrows():
                symbol = row['symbol']
                bars = bars_map.get(symbol)
                if bars is None: continue
                
                # MEMORY: Skip if we already acted on this symbol today
                if symbol in triggered_symbols:
                    continue
                
                or_data = extract_or(bars)
                if not or_data: continue

                # ONLY LONG: OR Close > OR Open
                direction = 1 if or_data['or_close'] > or_data['or_open'] else -1
                if direction != 1: continue 

                # RVOL calculation
                rvol = (or_data['or_volume'] * 78.0) / row['avg_volume_14'] if row['avg_volume_14'] > 0 else 0
                
                final_list.append({
                    'symbol': symbol,
                    'or_high': or_data['or_high'],
                    'atr_14': row['atr_14'],
                    'rvol': rvol,
                    'stop_price': or_data['or_high'] - (0.05 * row['atr_14'])
                })
            
            if not final_list:
                log("No symbols showed a Green Candle (Long setup). Finishing session.", clock=clock)
                return

            df_refined = pd.DataFrame(final_list)
            df_refined = df_refined.sort_values('rvol', ascending=False).head(5)
            refined_universe = df_refined
            
            log(f"Selection Complete. Monitoring Top {len(refined_universe)} RVOL Green Candles.", clock=clock)
            log(f"Watchlist: {refined_universe['symbol'].tolist()}", clock=clock)

            # RESTART-SAFETY: Check existing orders before placing new ones
            existing_orders = broker.get_active_orders()
            existing_symbols = {o['symbol'] for o in existing_orders}
            if existing_symbols:
                log(f"Found {len(existing_symbols)} existing open orders on broker. Integrating...", clock=clock)

            # Backtest Strategy 1: Equal Allocation
            num_targets = len(refined_universe)
            bp_limit_per_trade = start_bp / num_targets if num_targets > 0 else 0
            
            log(f"Sizing Model: EQUAL-ALLOCATION (Backtest Truth) | Target: ${bp_limit_per_trade:,.2f} per trade", clock=clock)
            
            for _, row in refined_universe.iterrows():
                # Equal Allocation Model (Matches Backtest Strategy 1)
                shares = bp_limit_per_trade / row['or_high']

                # Round to Nearest Integer (Matches Backtest Logic)
                shares = int(round(shares))
                if shares < 1: shares = 1
                
                log(f"Sizing {row['symbol']}: EQUAL-ALLOC. ${bp_limit_per_trade:,.2f} / {row['or_high']:.2f} -> {shares} shares", clock=clock)
                
                order_id = None
                if row['symbol'] in existing_symbols:
                    # Recovery Logic
                    match = next(o for o in existing_orders if o['symbol'] == row['symbol'])
                    order_id = match.get('ref_number', f"REC_{row['symbol']}")
                    log(f"RECOVERY: Using existing order for {row['symbol']} (Ref: {order_id})", clock=clock)
                else:
                    # IMMEDIATE BREAKOUT CHECK: Fetch current Ask to avoid R118 (Stop < Market)
                    quote = broker.get_quote(row['symbol'])
                    curr_ask = float(quote.get('ask', 0))
                    
                    if curr_ask >= row['or_high'] and curr_ask > 0:
                        log(f"IMMEDIATE BREAKOUT DETECTED: {row['symbol']} Ask ({curr_ask}) >= Trigger ({row['or_high']}). Using MARKET BUY.", level="WARNING", clock=clock)
                        # We use safe_place_market_order which handles R78 rejections too
                        order_id = safe_place_market_order(broker, row['symbol'], 'BUY', shares, clock)
                    else:
                        order_id = safe_place_buy_stop(broker, row['symbol'], shares, row['or_high'], clock)
                
                if order_id:
                    active_orders.append({
                        'id': order_id, 
                        'symbol': row['symbol'], 
                        'side': 'BUY', 
                        'stop_trigger': row['or_high'],
                        'stop_price': row['stop_price'], # Protective stop-loss
                        'shares': shares,
                        'atr_14': row['atr_14'],
                        'or_high': row['or_high']
                    })
                    triggered_symbols.add(row['symbol'])

        # 3. FILL WATCHER & STOP MONITORING (09:35 - 16:00)
        # We no longer monitor for breakouts manually. 
        # We only monitor to see when our BUY STOPS get filled.
        current_positions = broker.get_positions()
        
        for order in list(active_orders):
            pos = next((p for p in current_positions if p['symbol'] == order['symbol']), None)
            if pos and pos.get('qty', 0) >= order['shares']:
                # The browser 'Avg' col is mapped to 'avg_price' in our normalization
                # If avg_price is missing or zero, we fallback to trigger price
                fill_price = float(pos.get('avg_price', 0)) or order['stop_trigger']
                log(f"FILLED: {order['symbol']} @ {fill_price}", clock=clock)
                
                fills_tracker[order['symbol']] = {'entry_price': fill_price, 'shares': order['shares']}
                
                # !!! NEW: PLACE BROKER-SIDE PROTECTIVE STOP IMMEDIATELY !!!
                stop_id = safe_place_sell_stop(broker, order['symbol'], order['shares'], order['stop_price'], clock)
                
                open_positions.append({
                    'symbol': order['symbol'],
                    'shares': order['shares'],
                    'stop_price': order['stop_price'],
                    'stop_order_id': stop_id,
                    'atr_14': order.get('atr_14', 0.0),
                    'or_high': order.get('or_high', 0.0),
                    'repair_idx': 0
                })
                active_orders.remove(order)

        # 4. MONITORING & AUDITING (09:35 - 15:55)
        # --- STOP LOSS INTEGRITY REPAIR ---
        if not isinstance(broker, SimBroker):
            active_list = broker.get_active_orders()
            if active_list is not None:
                active_refs = {o.get('ref_number') for o in active_list}
                for pos in open_positions:
                    if not pos['stop_order_id'] or pos['stop_order_id'] not in active_refs:
                        # If we had an ID but it's not in the books, previous attempt failed/rejected
                        if pos['stop_order_id']:
                            log(f"ALERT: Previously placed stop {pos['stop_order_id']} for {pos['symbol']} vanished. Escalating repair...", level="WARNING", clock=clock)
                            pos['repair_idx'] = pos.get('repair_idx', 0) + 1
                        
                        log(f"ALERT: Stop loss for {pos['symbol']} missing. Attempting tiered repair (Level {pos.get('repair_idx', 0)})...", level="WARNING", clock=clock)
                        
                        repair_success = False
                        # Tiered Repair Multipliers: 0.05, 0.08, 0.10, 0.15, 0.20
                        multipliers = [0.05, 0.08, 0.10, 0.15, 0.20]
                        
                        start_idx = pos.get('repair_idx', 0)
                        quote = broker.get_quote(pos['symbol'])
                        # Use BID for Sell Stop validation (more conservative/accurate than Last)
                        reference_price = float(quote.get('bid', 0)) or float(quote.get('last', 0)) or pos['stop_price']
                        
                        for i in range(start_idx, len(multipliers)):
                            mult = multipliers[i]
                            if pos.get('or_high', 0) > 0 and pos.get('atr_14', 0) > 0:
                                new_stop = pos['or_high'] - (mult * pos['atr_14'])
                                
                                # PRICE SANITY CHECK: Only place stop if it's below current BID
                                # R118 Error triggers if Stop >= Bid
                                if reference_price <= new_stop + 0.01:
                                    log(f"REPAIR SKIP: Multiplier {mult}x ({new_stop:.4f}) is at/above current Bid ({reference_price}). Trying wider...", clock=clock)
                                    pos['repair_idx'] = i + 1
                                    continue
    
                                log(f"TIERED REPAIR: Trying wider stop for {pos['symbol']} @ {new_stop:.4f} ({mult}x ATR)", clock=clock)
                                new_id = safe_place_sell_stop(broker, pos['symbol'], pos['shares'], new_stop, clock)
                                if new_id:
                                    pos['stop_order_id'] = new_id
                                    pos['stop_price'] = new_stop
                                    pos['repair_idx'] = i # Maintain this index as current
                                    repair_success = True
                                    break
                                else:
                                    # Immediate failure (UI error)? Increment index to try wider next time
                                    log(f"REPAIR FAIL: Placement failed for {new_stop:.4f}. Trying wider...", level="WARNING", clock=clock)
                                    pos['repair_idx'] = i + 1
                            else:
                                break 
    
                        if not repair_success:
                            log(f"CRITICAL: All stop repairs failed for {pos['symbol']} or price already below 0.15 ATR. MARKET EXITING.", level="CRITICAL", clock=clock)
                            safe_place_market_order(broker, pos['symbol'], 'SELL', pos['shares'], clock)
                            # We don't remove from open_positions here; the EOD auditor will catch the 0 qty

        for pos in list(open_positions):
            broker_pos = next((p for p in current_positions if p['symbol'] == pos['symbol']), None)
            # Standardized Broker interface uses 'qty'
            if not broker_pos or float(broker_pos.get('qty', 0)) <= 0:
                # Realized PNL Calculation (Assuming Stop Hit)
                entry = fills_tracker.get(pos['symbol'])
                if entry:
                    exit_price = pos['stop_price']
                    pnl = (exit_price - entry['entry_price']) * entry['shares']
                    realized_pnl += pnl
                    log(f"STOP HIT: {pos['symbol']} @ ~{exit_price}. Trade PNL: ${pnl:,.2f}", clock=clock)
                    del fills_tracker[pos['symbol']] # Handled
                
                open_positions.remove(pos)

        # 5. Heartbeat (Every 5 minutes)
        if (now - market_open).total_seconds() - last_heartbeat_time >= 300:
            last_heartbeat_time = (now - market_open).total_seconds()
            # Fetch official figures from TradeZero
            acct = broker.get_account_summary()
            log(f"HEARTBEAT: {len(active_orders)} Pending | {len(open_positions)} Open | TZ Day Realized: ${acct.get('day_realized', 0):,.2f} | TZ Day Total: ${acct.get('day_total', 0):,.2f} | TZ Fees: ${acct.get('est_comm_fees', 0):,.2f}", clock=clock)

        # 6. Rejection Polling (Every 60s)
        if (now - market_open).total_seconds() - last_notif_time >= 60:
            last_notif_time = (now - market_open).total_seconds()
            notifs = broker.get_notifications()
            for n in notifs:
                msg = n.get('message', '').upper()
                # Use title+message to create a unique key
                key = f"{n.get('title')}_{msg}"
                if key not in notif_history:
                    notif_history.add(key)
                    if "REJECT" in msg or "ERROR" in msg or "R118" in msg:
                        log(f"BROKER NOTIFICATION: {n.get('title')} - {n.get('message')}", level="WARNING", clock=clock)
            
            # Cross-reference check: If an active order is no longer in broker's books
            # but we didn't see a fill or manual cancel, it was likely rejected.
            if not isinstance(broker, SimBroker) and active_orders:
                real_list = broker.get_active_orders()
                if real_list is not None:
                    real_active = {o['symbol'] for o in real_list}
                    for o in list(active_orders):
                        if o['symbol'] not in real_active:
                            # Double check positions to ensure it didn't just fill in this split second
                            pos_symbols = {p['symbol'] for p in broker.get_positions()}
                            if o['symbol'] not in pos_symbols:
                                log(f"ALERT: Order for {o['symbol']} vanished from broker books without being filled. Likely REJECTED.", level="ERROR", clock=clock)
                                # Remove from our tracking so we don't alert every minute
                                active_orders.remove(o)

        # 7. Stop Auditor (Every 60s)
        if (now - market_open).total_seconds() - last_audit_time >= 60:
            last_audit_time = (now - market_open).total_seconds()
            pass 

        clock.sleep(5) 
        
        # Persistence
        try:
            state = {
                'active_orders': active_orders,
                'open_positions': open_positions,
                'fills_tracker': fills_tracker,
                'realized_pnl': realized_pnl,
                'triggered_symbols': list(triggered_symbols)
            }
            with open(state_file, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            pass # Silent failure for persistence to avoid loop crashes

    # EOD Cleanup: Relentless flattening until 16:00 ET
    log("EOD Reached (15:55 ET) - Entering RELENTLESS FLATTEN mode until 16:00 ET...", clock=clock)
    
    market_bell = et_tz.localize(datetime.combine(current_date, dt_time(16, 0)))
    
    attempt = 1
    while clock.now() < market_bell:
        final_positions = broker.get_positions()
        if not final_positions:
            log("All positions successfully flattened.", clock=clock)
            break
            
        log(f"Flatten Attempt {attempt}: Liquidating {len(final_positions)} positions...", clock=clock)
        for pos in final_positions:
            symbol = pos['symbol']
            shares = int(pos.get('qty', 0))
            if shares <= 0: continue
            
            # Record EOD PNL before we close it
            if symbol in fills_tracker:
                entry = fills_tracker[symbol]
                # Try to get last price for EOD PNL estimation
                last_price = float(pos.get('last_price', 0)) or entry['entry_price']
                pnl = (last_price - entry['entry_price']) * shares
                realized_pnl += pnl
                log(f"EOD EXIT: {symbol} @ ~{last_price}. Trade PNL: ${pnl:,.2f}", clock=clock)
                del fills_tracker[symbol] 
            
            order_id = safe_place_market_order(broker, symbol, 'SELL', shares, clock)
            if order_id:
                log(f"FLATTEN ORDER SUBMITTED: {symbol} SELL {shares}", clock=clock)
            
            # Poll and log the most recent notification after each flatten attempt
            # to capture any rejection reasons immediately
            clock.sleep(2)  # Brief wait for rejection response
            notifs = broker.get_notifications()
            if notifs:
                latest = notifs[-1] if isinstance(notifs, list) else notifs.iloc[-1].to_dict() if hasattr(notifs, 'iloc') else {}
                if latest:
                    msg = latest.get('message', '')
                    log(f"LATEST BROKER NOTIFICATION: {latest.get('title', '')} - {msg}", level="WARNING", clock=clock)
        
        attempt += 1
        clock.sleep(10)
    
    # Final Result
    log(f"--- SESSION OVER --- Total Realized PNL: ${realized_pnl:,.2f}", clock=clock)
    
    # Final Final Check at 16:00
    remaining = broker.get_positions()
    if remaining:
        log(f"CRITICAL: Failed to flatten {len(remaining)} positions by market close (16:00)!", level="CRITICAL", clock=clock)
    else:
        log("EOD Flattening Complete: Account is flat.", clock=clock)

# -----------------------------------------------------------------------------
# Selection & Ranking
# -----------------------------------------------------------------------------

def generate_initial_pool(candidates_df: pd.DataFrame, target_date: datetime.date, bars_dict: dict = None) -> pd.DataFrame:
    """
    Filters candidates based on technicals (ATR, Volume) and sentiment.
    Loads historical data for calculations or uses fresh metrics if provided.
    Returns Top 15 pool for monitoring.
    """
    from ORB_Live_Trader.backtest.universe import load_daily, load_5min_full
    
    final_list = []
    
    for _, row in candidates_df.iterrows():
        ticker = row['symbol']
        
        # 1. PRIORITY: Use fresh metrics from candidates_df if available (Live mode)
        # Check if columns exist and are not zero
        atr = row.get('atr_14', 0)
        avg_vol = row.get('avg_volume_14', 0)
        
        # 2. FALLBACK: Load from local parquets (Verification mode or if pipeline fetch failed)
        if atr <= 0 or avg_vol <= 0:
            daily = load_daily(ticker)
            if daily is not None:
                d_row = daily[pd.to_datetime(daily['date']).dt.date == target_date]
                if not d_row.empty:
                    atr = float(d_row.iloc[0]['atr_14'])
                    avg_vol = float(d_row.iloc[0]['avg_volume_14'])
        
        # Still 0? Skip.
        if atr <= 0 or avg_vol <= 0:
            continue
            
        # Technical Filters
        if atr < 0.50: continue
        if avg_vol < 100000: continue
        
        # Load 5-min bars for simulation/monitoring (Verification Only)
        if bars_dict is not None:
            bars = load_5min_full(ticker)
            if bars is not None:
                 bars_dict[ticker] = bars[bars['date_et'] == target_date].copy()
        
        final_list.append({
            'symbol': ticker,
            'atr_14': atr,
            'avg_volume_14': avg_vol,
            'positive_score': row.get('positive_score', 0)
        })
        
    df_pool = pd.DataFrame(final_list)
    if df_pool.empty:
        return df_pool
        
    # Rank by Sentiment to get Top 15 watchlist
    df_pool = df_pool.sort_values('positive_score', ascending=False)
    df_pool = df_pool.drop_duplicates(subset=['symbol']).head(15)
    return df_pool

# -----------------------------------------------------------------------------
# Verification Mode Setup
# -----------------------------------------------------------------------------

def run_verification(target_date: str):
    log(f"Verifying {target_date}...")
    t_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    
    # 1. Pipeline: Fresh Fetch & Score
    log("Running Live Pipeline (Fresh Fetch)...")
    raw_candidates = pipeline.run_pipeline(t_date)
    
    if raw_candidates.empty:
        log("No candidates found via live pipeline.")
        return

    # 2. Pool Generation (Top 15 Watchlist)
    my_bars = {} 
    df_pool = generate_initial_pool(raw_candidates, t_date, bars_dict=my_bars)
    
    if df_pool.empty:
        log("No candidates passed initial selection filters.")
        return
    
    selected_symbols = df_pool['symbol'].tolist()
    log(f"Initial Pool Subscribed: {len(df_pool)} symbols")
    log(f"Watchlist: {selected_symbols}")
    
    # Setup Sim
    et_tz = pytz.timezone("America/New_York")
    start_time = et_tz.localize(datetime.combine(t_date, dt_time(9, 30)))
    clock = SimClock(start_time, time_step_sec=5)
    broker = SimBroker(my_bars, clock)
    
    # Run
    acc = broker.get_account_info()
    run_trading_session(clock, broker, df_pool, equity=acc['equity'], start_bp=acc['buying_power'])
    
    # 3. Cache Data for Inspection (Transparency Upgrade)
    # Aligning with User Request: Single file per ticker in bot's data store
    from ORB_Live_Trader.pipeline.live_pipeline import persist_incremental_bars
    min5_bot_dir = ORB_ROOT / "data" / "bars" / "5min"
    min5_bot_dir.mkdir(parents=True, exist_ok=True)
    
    for symbol, df in my_bars.items():
        master_file = min5_bot_dir / f"{symbol}.parquet"
        # 5-min bars from SimBroker use 'datetime' column
        persist_incremental_bars(df, master_file, timestamp_col='datetime')
    
    log(f"Merged verification 5min bars for {len(my_bars)} symbols into {min5_bot_dir}")

    if isinstance(broker, SimBroker):
        # Calculate PNL from SimBroker internal tracking
        gross_pnl = sum(t['pnl'] for t in broker.completed_trades)
        total_fees = broker.total_fees
        net_pnl = gross_pnl - total_fees
        
        log("-" * 40, clock=clock)
        log(f"SESSION PNL SUMMARY (Verification: {target_date})", clock=clock)
        log("-" * 40, clock=clock)
        log(f"GROSS PNL: ${gross_pnl:,.2f}", clock=clock)
        log(f"FEES     : ${total_fees:,.2f}", clock=clock)
        log(f"NET PNL  : ${net_pnl:,.2f}", clock=clock)
        log("-" * 40, clock=clock)
        
        log("Full Order History Audit:", clock=clock)
        for o in broker.orders:
            fee_str = f"| Fee: ${o.get('commission', 0.0):.2f}"
            log(f"{o['submitted_at'].time()} {o['symbol']} {o['side']} {o['status']} @ {o.get('fill_price')} {fee_str}", clock=clock)

# -----------------------------------------------------------------------------
# Live Mode Setup
# -----------------------------------------------------------------------------

def run_live(dry_run: bool = False, gui: bool = True, date_override: str = None):
    """
    Executes a real-time trading session.
    """
    today = datetime.strptime(date_override, "%Y-%m-%d").date() if date_override else datetime.now().date()
    is_historical = date_override is not None
    
    # 1. Pipeline: Auto-Wait & Run (Matches Research 09:30 Cutoff)
    et_tz = pytz.timezone("America/New_York")
    now_et = datetime.now(et_tz)
    market_open_wait = et_tz.localize(datetime.combine(today, dt_time(9, 30, 1)))
    
    # Only wait if it's actually today and before open
    if not is_historical and now_et < market_open_wait:
        wait_secs = (market_open_wait - now_et).total_seconds()
        log(f"Waiting until 09:30:01 ET for final news capture... ({int(wait_secs)}s remaining)")
        time_module.sleep(wait_secs)
    
    from ORB_Live_Trader.pipeline.live_pipeline import sentiment_dir 
    sentiment_path = sentiment_dir / f"daily_{today}.parquet"
    
    if not sentiment_path.exists():
        log(f"Universe for {today} not found. Running Live Pipeline (09:30 Cutoff)...")
        pipeline.run_pipeline(today)
    else:
        log(f"Universe for {today} found. Using existing daily parquet.")

    # 2. Daily Watchlist Generation
    raw_uni = pd.read_parquet(sentiment_path)
    # Re-apply filters just in case (Durable)
    from ORB_Live_Trader.main import generate_initial_pool
    pool_df = generate_initial_pool(raw_uni, today)
    
    if pool_df.empty:
        log("No candidates qualified for today's watchlist. Session ended.")
        return
    
    log(f"Watchlist Subscribed: {len(pool_df)} symbols")
    log(f"Watchlist: {pool_df['symbol'].tolist()}")

    # 3. Setup Live Components
    tz_headless = not gui
    if dry_run:
        log("!!! DRY RUN MODE ACTIVE !!! Orders will NOT be submitted.")

    try:
        if date_override:
            # Start clock at 09:29:50 of that day to catch the open
            start_dt = datetime.combine(today, dt_time(9, 29, 50))
            if dry_run:
                # Fast Clock for Dry Run
                clock = SimClock(et_tz.localize(start_dt), time_step_sec=5)
                log(f"Fast Clock Active (Simulation Mode): {clock.now().strftime('%Y-%m-%d %H:%M:%S')}", clock=clock)
            else:
                # Real-time speed for Live/Gui runs
                clock = TimedLiveClock(start_dt)
                log(f"Clock Shifted: {clock.now().strftime('%Y-%m-%d %H:%M:%S')} (Timed Live Run)", clock=clock)
        else:
            clock = LiveClock()

        # Broker Selection
        real_tz = TradeZero(
            user_name=os.getenv("TRADEZERO_USERNAME"),
            password=os.getenv("TRADEZERO_PASSWORD"),
            headless=tz_headless
        )
        temp_broker = TradeZeroBroker(real_tz, dry_run=dry_run)
        
        # Always use real account data as the base
        acc = temp_broker.get_account_info()
        real_bp = acc['buying_power']
        equity = acc['equity']
        
        # RESTORED: Buying Power Override from Env. Supports BUYING_POWER_OVERRIDE (legacy) or ORB_MAX_BUYING_POWER
        bp_override = os.getenv("BUYING_POWER_OVERRIDE") or os.getenv("ORB_MAX_BUYING_POWER")
        if bp_override:
            try:
                limit_bp = float(bp_override)
                if limit_bp < real_bp:
                    log(f"!!! BUYING POWER OVERRIDE ACTIVE: Using ${limit_bp:,.2f} (Portfolio Real: ${real_bp:,.2f})", level="WARNING", clock=clock)
                    real_bp = limit_bp
            except ValueError:
                log(f"Invalid Buying Power Override value: {bp_override}", level="ERROR")

        log(f"Account Balance: ${equity:,.2f} | Buying Power: ${real_bp:,.2f}", clock=clock)

        if date_override and dry_run:
            # For historical dry runs, we use SimBroker (the backtest engine) 
            # so that orders can be "filled" against historical data.
            # But we initialize it with the REAL account values.
            from ORB_Live_Trader.backtest.universe import load_5min_full
            mock_bars = {}
            for symbol in pool_df['symbol'].tolist():
                full_bars = load_5min_full(symbol)
                if full_bars is not None:
                    day_bars = full_bars[full_bars['date_et'] == today].copy()
                    if not day_bars.empty:
                        mock_bars[symbol] = day_bars

            log(f"Injected historical 5min bars for {len(mock_bars)} symbols to enable historical fills.", clock=clock)
            log("Using Backtest Engine (Simulator) with real account BP for historical dry run.", clock=clock)
            broker = SimBroker(mock_bars, clock, equity=equity, buying_power=real_bp)
        else:
            broker = temp_broker

        # 4. Start Trading Session
        run_trading_session(clock, broker, pool_df, equity=equity, start_bp=real_bp)

        # 5. Session PNL Reporting (Audit Trail)
        if isinstance(broker, SimBroker) or dry_run:
            # We track PNL in the broker if it's the simulator
            # For real Live Broker, we might sum the realized_pnl tracker if we pass it out,
            # but for now we focus on the simulator's detailed net report.
            if isinstance(broker, SimBroker):
                gross_pnl = sum(t['pnl'] for t in broker.completed_trades)
                total_fees = broker.total_fees
                net_pnl = gross_pnl - total_fees
                
                log("-" * 40, clock=clock)
                log(f"SESSION PNL SUMMARY ({today})", clock=clock)
                log("-" * 40, clock=clock)
                log(f"GROSS PNL: ${gross_pnl:,.2f}", clock=clock)
                log(f"FEES     : ${total_fees:,.2f}", clock=clock)
                log(f"NET PNL  : ${net_pnl:,.2f}", clock=clock)
                log("-" * 40, clock=clock)
                
                log("Full Order History Audit:", clock=clock)
                for o in broker.orders:
                    fee_str = f"| Fee: ${o.get('commission', 0.0):.2f}"
                    log(f"{o['submitted_at'].time()} {o['symbol']} {o['side']} {o['status']} @ {o.get('fill_price')} {fee_str}", clock=clock)

    except Exception as e:
        log(f"Critical Live Session Error: {e}", level="ERROR")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="Run in historical verification mode")
    parser.add_argument("--date", type=str, help="Target date for verification (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate orders in live mode (no real money)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (Invisible)")
    args = parser.parse_args()
    
    # Default GUI to True, but allow --headless to turn it off
    use_gui = not args.headless
    
    if args.verify:
        if not args.date:
            print("Error: --date YYYY-MM-DD required for verification mode.")
            return
            
        # Re-configure logger for the specific verification date
        global trading_logger
        trading_logger = setup_daily_logging(args.date)
        
        run_verification(args.date)
    else:
        # Live Session: Default logger is already setup for today
        if args.date:
            trading_logger = setup_daily_logging(args.date)
            
        run_live(dry_run=args.dry_run, gui=use_gui, date_override=args.date)


if __name__ == "__main__":
    main()
