import sys
import logging
from pathlib import Path
from datetime import date

# Setup path
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from services.signal_engine import get_pending_signals, calculate_position_size
from execution.order_executor import get_executor
from core.config import get_strategy_config
from state.duckdb_store import DuckDBStateStore

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_rejected_signals():
    """Reset today's REJECTED signals to PENDING so we can retry them."""
    store = DuckDBStateStore()
    # Access the connection directly (hacky but effective for script)
    store.ensure_tables()
    con = store._connect()
    today = date.today()
    try:
        # Check count first
        count = con.execute(
            "SELECT COUNT(*) FROM signals WHERE status = 'REJECTED' AND signal_date = ?",
            [today]
        ).fetchone()[0]
        
        if count > 0:
            logger.info(f"Found {count} REJECTED signals. Resetting to PENDING...")
            con.execute(
                "UPDATE signals SET status = 'PENDING', rejection_reason = NULL WHERE status = 'REJECTED' AND signal_date = ?",
                [today]
            )
            logger.info(" Reset complete.")
        else:
            logger.info("No REJECTED signals found for today.")
            
    except Exception as e:
        logger.error(f"Failed to reset signals: {e}")
    finally:
        con.close()

def manual_execute():
    logger.info(" Starting Manual Execution of Pending Signals")
    
    # Reset rejected signals first
    reset_rejected_signals()
    
    # Get pending signals
    pending = get_pending_signals()
    logger.info(f"Found {len(pending)} pending signals")
    
    if not pending:
        return

    executor = get_executor()
    strategy = get_strategy_config()
    
    # Get account info
    try:
        account = executor.get_account()
        equity = float(account.get("equity", 10000))
        buying_power = float(account.get("buying_power", equity))
    except Exception as e:
        logger.error(f"Failed to fetch account info: {e}")
        equity = 10000.0
        buying_power = 10000.0
    
    logger.info(f"Account Equity: ")
    logger.info(f"Buying Power: ")
    
    # Cap each position
    max_position_value = buying_power / strategy["top_n"]
    
    for signal in pending:
        logger.info(f"\nProcessing {signal['symbol']} ({signal['side']})...")
        
        # Calculate shares
        shares = calculate_position_size(
            entry_price=signal["entry_price"],
            stop_price=signal["stop_price"],
            account_equity=equity,
            max_position_value=max_position_value,
        )
        
        logger.info(f"Calculated shares: {shares}")
        
        if shares > 0:
            logger.info(f"Placing order for {signal['symbol']}...")
            order_result = executor.place_entry_order(
                symbol=signal["symbol"],
                side=signal["side"],
                shares=shares,
                entry_price=signal["entry_price"],
                stop_price=signal["stop_price"],
                signal_id=signal["id"],
            )
            
            if order_result.get("status") == "submitted":
                logger.info(f" Placed {signal['side']} order: {signal['symbol']} x{shares}")
            else:
                # Log the FULL result to see the error
                logger.error(f" Failed order: {signal['symbol']}")
                logger.error(f"Reason: {order_result.get('reason')}")
                logger.error(f"Full Result: {order_result}")
        else:
            logger.warning(f" Skipped {signal['symbol']} - calculated 0 shares")

if __name__ == "__main__":
    manual_execute()
