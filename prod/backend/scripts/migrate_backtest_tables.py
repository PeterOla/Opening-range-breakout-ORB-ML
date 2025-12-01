"""
Migration script to add historical backtest tables.

Run this once to create the new tables:
- daily_metrics_historical
- backtest_runs  
- daily_performance

Also updates simulated_trades with new columns.
"""
import sys
sys.path.insert(0, ".")

from sqlalchemy import text, inspect
from db.database import engine, Base
from db.models import (
    DailyMetricsHistorical,
    BacktestRun,
    DailyPerformance,
    SimulatedTrade,
)

def migrate():
    print("Creating new backtest tables...")
    
    # Create all tables (only creates if they don't exist)
    Base.metadata.create_all(bind=engine)
    
    # Get inspector for checking tables/columns
    inspector = inspect(engine)
    
    # Check if tables were created
    tables = inspector.get_table_names()
    
    for table_name in ['daily_metrics_historical', 'backtest_runs', 'daily_performance']:
        if table_name in tables:
            print(f"✓ {table_name} table exists")
        else:
            print(f"✗ {table_name} table NOT created")
    
    # Check for new columns in simulated_trades
    if 'simulated_trades' in tables:
        columns = [col['name'] for col in inspector.get_columns('simulated_trades')]
        
        new_cols = {
            'backtest_run_id': 'INTEGER',
            'entry_time': 'VARCHAR(10)',
            'exit_time': 'VARCHAR(10)',
            'base_dollar_pnl': 'FLOAT',
        }
        
        with engine.connect() as conn:
            for col, col_type in new_cols.items():
                if col in columns:
                    print(f"✓ simulated_trades.{col} exists")
                else:
                    print(f"⚠ simulated_trades.{col} missing - adding...")
                    try:
                        conn.execute(text(f"ALTER TABLE simulated_trades ADD COLUMN {col} {col_type}"))
                        conn.commit()
                        print(f"  ✓ Added {col}")
                    except Exception as e:
                        print(f"  ✗ Failed to add {col}: {e}")
    
    print("\nMigration complete!")

if __name__ == "__main__":
    migrate()
