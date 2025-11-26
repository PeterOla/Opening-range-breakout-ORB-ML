"""
EOD Scheduler for ORB Strategy.

Automates:
1. 6:00 PM ET - Nightly data sync (tickers + daily bars)
2. 3:55 PM ET - Flatten all positions (EOD exit)
3. 9:25 AM ET - Pre-market health check
4. 4:05 PM ET - Daily P&L logging
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from execution.order_executor import flatten_eod, get_executor

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
    3:55 PM ET - Close all positions and cancel orders.
    Critical for day trading - no overnight exposure.
    """
    logger.info("🔔 EOD FLATTEN triggered at 3:55 PM ET")
    
    try:
        result = flatten_eod()
        logger.info(f"✅ EOD flatten complete: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ EOD flatten failed: {e}")
        raise


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
    
    # Job 1: EOD Flatten at 3:55 PM ET (Mon-Fri)
    scheduler.add_job(
        job_flatten_eod,
        CronTrigger(
            hour=15,
            minute=55,
            day_of_week="mon-fri",
            timezone=ET,
        ),
        id="eod_flatten",
        name="EOD Position Flatten",
        replace_existing=True,
    )
    logger.info("📅 Scheduled: EOD flatten at 3:55 PM ET (Mon-Fri)")
    
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
    
    # Job 3: Daily summary at 4:05 PM ET (Mon-Fri)
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
