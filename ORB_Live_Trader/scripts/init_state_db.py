"""
Initialize DuckDB state database for live ORB trading.
Creates tables for universe, orders, positions, and trade audit trail.

Run once on setup: python scripts/init_state_db.py
"""
import duckdb
from pathlib import Path
from datetime import datetime

# Paths
STATE_DIR = Path(__file__).parent.parent / "state"
DB_PATH = STATE_DIR / "orb_state.duckdb"

def log(message: str):
    """Simple terminal logger"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [INFO] [INIT_DB] {message}")

def init_database():
    """Create DuckDB schema for live trading state"""
    
    log(f"Initializing DuckDB at {DB_PATH}")
    
    con = duckdb.connect(str(DB_PATH))
    
    # Table 1: Daily Universe (Top 5 candidates selected each day)
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_universe (
            date DATE NOT NULL,
            symbol VARCHAR NOT NULL,
            rvol DOUBLE,
            entry_price DOUBLE,
            stop_price DOUBLE,
            atr_14 DOUBLE,
            or_high DOUBLE,
            or_low DOUBLE,
            or_open DOUBLE,
            or_close DOUBLE,
            or_volume BIGINT,
            avg_volume_14 DOUBLE,
            direction INTEGER,
            sentiment_score DOUBLE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (date, symbol)
        )
    """)
    log("Created table: daily_universe")
    
    # Table 2: Active Orders (pending/filled orders)
    con.execute("""
        CREATE TABLE IF NOT EXISTS active_orders (
            order_id VARCHAR PRIMARY KEY,
            symbol VARCHAR NOT NULL,
            side VARCHAR NOT NULL,
            order_type VARCHAR NOT NULL,
            price DOUBLE,
            shares INTEGER NOT NULL,
            status VARCHAR NOT NULL,
            submitted_at TIMESTAMP NOT NULL,
            filled_at TIMESTAMP,
            fill_price DOUBLE,
            tz_order_num VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    log("Created table: active_orders")
    
    # Table 3: Filled Positions (currently open positions)
    con.execute("""
        CREATE TABLE IF NOT EXISTS filled_positions (
            symbol VARCHAR PRIMARY KEY,
            entry_price DOUBLE NOT NULL,
            shares INTEGER NOT NULL,
            stop_price DOUBLE NOT NULL,
            entry_time TIMESTAMP NOT NULL,
            stop_order_id VARCHAR,
            current_price DOUBLE,
            current_pnl DOUBLE,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    log("Created table: filled_positions")
    
    # Table 4: Closed Trades (permanent audit trail)
    con.execute("""
        CREATE TABLE IF NOT EXISTS closed_trades (
            trade_id INTEGER PRIMARY KEY,
            symbol VARCHAR NOT NULL,
            entry_time TIMESTAMP NOT NULL,
            exit_time TIMESTAMP NOT NULL,
            entry_price DOUBLE NOT NULL,
            exit_price DOUBLE NOT NULL,
            shares INTEGER NOT NULL,
            pnl_gross DOUBLE NOT NULL,
            pnl_net DOUBLE NOT NULL,
            commission DOUBLE NOT NULL,
            exit_reason VARCHAR NOT NULL,
            stop_distance_pct DOUBLE,
            hold_time_minutes INTEGER,
            rvol DOUBLE,
            atr_14 DOUBLE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    log("Created table: closed_trades")
    
    # Table 5: Equity Snapshots (daily equity tracking)
    con.execute("""
        CREATE TABLE IF NOT EXISTS equity_snapshots (
            snapshot_date DATE PRIMARY KEY,
            start_equity DOUBLE NOT NULL,
            end_equity DOUBLE NOT NULL,
            daily_pnl DOUBLE NOT NULL,
            trades_today INTEGER NOT NULL,
            winners_today INTEGER NOT NULL,
            losers_today INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    log("Created table: equity_snapshots")
    
    # Verify tables created
    tables = con.execute("SHOW TABLES").fetchall()
    log(f"Database initialized with {len(tables)} tables: {[t[0] for t in tables]}")
    
    con.close()
    log("Database connection closed")

if __name__ == "__main__":
    init_database()
    print("\n✅ DuckDB state database initialized successfully")
    print(f"📁 Location: {DB_PATH}")
