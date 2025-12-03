"""
EOD Scheduler for ORB Strategy.

Automates:
1. 6:00 PM ET - Nightly data sync (tickers + daily bars)
2. Dynamic EOD flatten - 5 mins before market close (handles early close days)
3. 9:25 AM ET - Pre-market health check
4. 9:36 AM ET - Auto signal generation + execution (OR breakout)
5. 4:05 PM ET - Daily P&L logging
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from execution.order_executor import flatten_eod, get_executor
from services.market_calendar import get_market_calendar, is_early_close_today

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Scheduler instance
scheduler = AsyncIOScheduler(timezone=ET)


async def job_nightly_data_sync():
    """
    6:00 PM ET - Nightly data sync (after market close).
    
    1. Sync ticker universe from Polygon (weekly on Sundays only)
    2. Fetch last 14 days of daily bars for all stocks
    3. Compute ATR(14) and avg_volume(14)
    4. Update filter flags on tickers
    """
    from services.data_sync import sync_daily_bars_fast
    from services.ticker_sync import sync_tickers_from_polygon, update_ticker_filters
    
    logger.info("🌙 NIGHTLY DATA SYNC triggered at 6:00 PM ET")
    
    try:
        # Check if it's Sunday - sync tickers weekly
        today = datetime.now(ET)
        if today.weekday() == 6:  # Sunday
            logger.info("📊 Sunday - syncing ticker universe...")
            ticker_result = await sync_tickers_from_polygon(include_delisted=False)
            logger.info(f"  Tickers: {ticker_result}")
        
        # Sync daily bars (every day)
        logger.info("📈 Syncing daily bars (14 days)...")
        bars_result = await sync_daily_bars_fast(lookback_days=14)
        logger.info(f"  Bars: {bars_result}")
        
        # Update filter flags
        if bars_result.get("status") == "success":
            logger.info("🔄 Updating ticker filters...")
            filter_result = await update_ticker_filters()
            logger.info(f"  Filters: {filter_result}")
        
        logger.info("✅ Nightly data sync complete")
        return {"status": "success", "bars": bars_result}
    
    except Exception as e:
        logger.error(f"❌ Nightly data sync failed: {e}")
        raise


async def job_flatten_eod():
    """
    Dynamic EOD flatten - 5 mins before market close.
    Handles early close days (e.g., Black Friday - 1 PM close).
    Critical for day trading - no overnight exposure.
    """
    calendar = get_market_calendar()
    schedule = calendar.get_todays_schedule()
    
    logger.info(f"🔔 EOD FLATTEN triggered - Market closes at {schedule.get('close', '??')}")
    
    if schedule.get("early_close"):
        logger.warning("⚠️ EARLY CLOSE DAY - Flattening positions before 1 PM close")
    
    try:
        result = flatten_eod()
        logger.info(f"✅ EOD flatten complete: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ EOD flatten failed: {e}")
        raise


async def schedule_todays_eod_flatten():
    """
    Schedule today's EOD flatten based on market calendar.
    Called at market open to set the correct flatten time.
    
    - Regular day: 3:55 PM ET
    - Early close: 12:55 PM ET (or 5 mins before actual close)
    """
    calendar = get_market_calendar()
    flatten_time = calendar.get_flatten_time()
    
    if flatten_time is None:
        logger.info("📅 Not a trading day - no EOD flatten scheduled")
        return
    
    today = datetime.now(ET).date()
    flatten_dt = datetime.combine(today, flatten_time).replace(tzinfo=ET)
    now = datetime.now(ET)
    
    # Check if already past flatten time
    if now >= flatten_dt:
        logger.warning(f"⚠️ Already past flatten time ({flatten_time}), executing now!")
        await job_flatten_eod()
        return
    
    schedule = calendar.get_todays_schedule()
    close_time = schedule.get("close", "16:00")
    is_early = schedule.get("early_close", False)
    
    logger.info(f"📅 Market closes at {close_time} {'(EARLY CLOSE)' if is_early else ''}")
    logger.info(f"📅 Scheduling EOD flatten for {flatten_time}")
    
    # Remove existing dynamic job if present
    existing_job = scheduler.get_job("dynamic_eod_flatten")
    if existing_job:
        scheduler.remove_job("dynamic_eod_flatten")
    
    # Schedule one-time job for today's flatten
    scheduler.add_job(
        job_flatten_eod,
        DateTrigger(run_date=flatten_dt),
        id="dynamic_eod_flatten",
        name=f"EOD Flatten ({flatten_time.strftime('%H:%M')})",
        replace_existing=True,
    )
    
    logger.info(f"✅ EOD flatten scheduled for {flatten_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")


async def job_premarket_check():
    """
    9:25 AM ET - Pre-market health check.
    Verifies system is ready before market open.
    """
    logger.info("🌅 Pre-market check at 9:25 AM ET")
    
    try:
        executor = get_executor()
        
        # Check account status
        account = executor.get_account()
        if account.get("trading_blocked"):
            logger.error("⚠️ Trading is BLOCKED on this account!")
            return {"status": "blocked", "account": account}
        
        # Check kill switch
        if executor.is_kill_switch_active():
            logger.warning("⚠️ Kill switch is ACTIVE - trading disabled")
            return {"status": "kill_switch_active"}
        
        logger.info(f"✅ Account ready - Equity: ${account.get('equity', 0):,.2f}")
        return {"status": "ready", "account": account}
    
    except Exception as e:
        logger.error(f"❌ Pre-market check failed: {e}")
        raise


async def job_auto_execute_orb():
    """
    9:36 AM ET - Auto signal generation and execution.
    
    Runs 6 minutes after market open when the Opening Range is complete.
    1. Load strategy config (top_n, direction, risk_per_trade)
    2. Fetch LIVE equity from Alpaca (for compounding)
    3. Run ORB scanner → generate signals → execute orders
    """
    from services.signal_engine import run_signal_generation, get_pending_signals, calculate_position_size
    from execution.order_executor import get_executor
    from core.config import get_strategy_config
    from db.database import SessionLocal
    from db.models import Signal
    
    logger.info("🚀 AUTO-EXECUTE ORB triggered at 9:36 AM ET")
    
    # Load strategy configuration
    strategy = get_strategy_config()
    logger.info(f"🎯 Strategy: {strategy['name']} ({strategy['description']})")
    logger.info(f"   Top-N: {strategy['top_n']}, Direction: {strategy['direction']}, Risk/Trade: {strategy['risk_per_trade']*100:.1f}%")
    
    executor = get_executor()
    
    # Check kill switch first
    if executor.is_kill_switch_active():
        logger.warning("⚠️ Kill switch ACTIVE - skipping auto-execution")
        return {"status": "blocked", "reason": "kill_switch_active"}
    
    # Check market is open today
    calendar = get_market_calendar()
    if not calendar.is_market_open_today():
        logger.info("📅 Market closed today - skipping auto-execution")
        return {"status": "skipped", "reason": "market_closed"}
    
    try:
        # Fetch LIVE equity from Alpaca — this is key for compounding!
        # As you profit, equity grows → position sizes grow automatically
        account = executor.get_account()
        equity = float(account.get("equity", 10000))
        logger.info(f"💰 Live account equity: ${equity:,.2f} (compounding base)")
        
        # Step 1: Generate signals using strategy config
        logger.info("📊 Step 1: Running signal generation...")
        result = await run_signal_generation(
            account_equity=equity,
            risk_per_trade_pct=strategy["risk_per_trade"],
            max_positions=strategy["top_n"],
            direction=strategy["direction"],
        )
        
        signals_generated = result.get("signals_generated", 0)
        logger.info(f"📊 Generated {signals_generated} signals")
        
        if signals_generated == 0:
            logger.info("📊 No signals generated - nothing to execute")
            return {"status": "no_signals", "signals_generated": 0, "orders_placed": 0}
        
        # Step 2: Execute pending signals
        logger.info("💹 Step 2: Executing pending signals...")
        pending = get_pending_signals()
        
        if not pending:
            logger.warning("⚠️ Signals generated but none pending - already executed?")
            return {"status": "already_executed", "signals_generated": signals_generated}
        
        # Get current account equity for position sizing
        account = executor.get_account()
        equity = account.get("equity", 1500)
        
        orders_placed = 0
        orders_failed = 0
        results = []
        
        db = SessionLocal()
        try:
            for signal in pending:
                # Calculate shares based on risk
                shares = calculate_position_size(
                    entry_price=signal["entry_price"],
                    stop_price=signal["stop_price"],
                    account_equity=equity,
                )
                
                if shares > 0:
                    order_result = executor.place_entry_order(
                        symbol=signal["symbol"],
                        side=signal["side"],
                        shares=shares,
                        entry_price=signal["entry_price"],
                        stop_price=signal["stop_price"],
                        signal_id=signal["id"],
                    )
                    results.append(order_result)
                    
                    if order_result.get("status") == "submitted":
                        orders_placed += 1
                        logger.info(f"✅ Placed {signal['side']} order: {signal['symbol']} x{shares}")
                    else:
                        orders_failed += 1
                        logger.warning(f"❌ Failed order: {signal['symbol']} - {order_result.get('error')}")
                else:
                    orders_failed += 1
                    logger.warning(f"⚠️ Skipped {signal['symbol']} - calculated 0 shares")
        finally:
            db.close()
        
        logger.info(f"""
        ========== AUTO-EXECUTE COMPLETE ==========
        Signals Generated: {signals_generated}
        Orders Placed:     {orders_placed}
        Orders Failed:     {orders_failed}
        ============================================
        """)
        
        return {
            "status": "success",
            "signals_generated": signals_generated,
            "orders_placed": orders_placed,
            "orders_failed": orders_failed,
            "results": results,
        }
        
    except Exception as e:
        logger.error(f"❌ Auto-execute failed: {e}", exc_info=True)
        raise


async def job_daily_summary():
    """
    4:05 PM ET - Log daily P&L summary.
    Runs after market close to capture final figures.
    """
    logger.info("📊 Daily summary at 4:05 PM ET")
    
    try:
        executor = get_executor()
        account = executor.get_account()
        
        logger.info(f"""
        ========== DAILY SUMMARY ==========
        Equity:     ${account.get('equity', 0):,.2f}
        Cash:       ${account.get('cash', 0):,.2f}
        Day Trades: {account.get('day_trade_count', 0)}
        ===================================
        """)
        
        return {"status": "logged", "account": account}
    
    except Exception as e:
        logger.error(f"❌ Daily summary failed: {e}")
        raise


def start_scheduler():
    """
    Start the EOD scheduler with all jobs.
    Called during FastAPI startup.
    """
    if scheduler.running:
        logger.info("Scheduler already running")
        return
    
    # Job 0: Nightly data sync at 6:00 PM ET (Mon-Fri)
    scheduler.add_job(
        job_nightly_data_sync,
        CronTrigger(
            hour=18,
            minute=0,
            day_of_week="mon-fri",
            timezone=ET,
        ),
        id="nightly_data_sync",
        name="Nightly Data Sync",
        replace_existing=True,
    )
    logger.info("📅 Scheduled: Nightly data sync at 6:00 PM ET (Mon-Fri)")
    
    # Also run on Sunday evening for weekend catch-up + ticker sync
    scheduler.add_job(
        job_nightly_data_sync,
        CronTrigger(
            hour=18,
            minute=0,
            day_of_week="sun",
            timezone=ET,
        ),
        id="sunday_data_sync",
        name="Sunday Data Sync + Tickers",
        replace_existing=True,
    )
    logger.info("📅 Scheduled: Sunday data sync at 6:00 PM ET")
    
    # Job 1: Schedule dynamic EOD flatten at 9:30 AM (market open)
    # This will check market calendar and schedule for correct time
    # (3:55 PM regular days, 12:55 PM early close days)
    scheduler.add_job(
        schedule_todays_eod_flatten,
        CronTrigger(
            hour=9,
            minute=30,
            day_of_week="mon-fri",
            timezone=ET,
        ),
        id="schedule_eod_flatten",
        name="Schedule Dynamic EOD Flatten",
        replace_existing=True,
    )
    logger.info("📅 Scheduled: Dynamic EOD flatten setup at 9:30 AM ET (Mon-Fri)")
    
    # Job 1b: Fallback fixed EOD flatten at 3:55 PM (in case dynamic fails)
    scheduler.add_job(
        job_flatten_eod,
        CronTrigger(
            hour=15,
            minute=55,
            day_of_week="mon-fri",
            timezone=ET,
        ),
        id="eod_flatten_fallback",
        name="EOD Flatten Fallback (3:55 PM)",
        replace_existing=True,
    )
    logger.info("📅 Scheduled: EOD flatten fallback at 3:55 PM ET (Mon-Fri)")
    
    # Job 2: Pre-market check at 9:25 AM ET (Mon-Fri)
    scheduler.add_job(
        job_premarket_check,
        CronTrigger(
            hour=9,
            minute=25,
            day_of_week="mon-fri",
            timezone=ET,
        ),
        id="premarket_check",
        name="Pre-market Health Check",
        replace_existing=True,
    )
    logger.info("📅 Scheduled: Pre-market check at 9:25 AM ET (Mon-Fri)")
    
    # Job 2b: Auto signal generation + execution at 9:36 AM ET (Mon-Fri)
    # Runs 6 mins after market open when Opening Range is complete
    scheduler.add_job(
        job_auto_execute_orb,
        CronTrigger(
            hour=9,
            minute=36,
            day_of_week="mon-fri",
            timezone=ET,
        ),
        id="auto_execute_orb",
        name="Auto-Execute ORB Signals (9:36 AM)",
        replace_existing=True,
    )
    logger.info("📅 Scheduled: Auto ORB execution at 9:36 AM ET (Mon-Fri)")
    
    # Job 3: Daily summary - dynamic based on market close
    # Will run 5 mins after actual market close
    scheduler.add_job(
        job_daily_summary,
        CronTrigger(
            hour=16,
            minute=5,
            day_of_week="mon-fri",
            timezone=ET,
        ),
        id="daily_summary",
        name="Daily P&L Summary",
        replace_existing=True,
    )
    logger.info("📅 Scheduled: Daily summary at 4:05 PM ET (Mon-Fri)")
    
    # Start the scheduler
    scheduler.start()
    logger.info("✅ Scheduler started successfully")
    
    # If starting during market hours, schedule today's EOD flatten now
    import asyncio
    asyncio.create_task(_schedule_eod_if_needed())


async def _schedule_eod_if_needed():
    """
    Check if we're in market hours and schedule EOD flatten.
    Called on startup to handle server restarts during trading hours.
    """
    from datetime import time
    now = datetime.now(ET)
    
    # Only check on weekdays
    if now.weekday() > 4:  # Saturday or Sunday
        return
    
    # If after 9:30 AM and before market close, schedule EOD
    market_open = time(9, 30)
    if now.time() >= market_open:
        logger.info("🔄 Server started during market hours - scheduling EOD flatten")
        await schedule_todays_eod_flatten()


def stop_scheduler():
    """
    Stop the scheduler gracefully.
    Called during FastAPI shutdown.
    """
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 Scheduler stopped")


def get_scheduled_jobs() -> list[dict]:
    """Get list of all scheduled jobs and their next run times."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return jobs
