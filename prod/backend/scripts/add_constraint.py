"""Add missing unique constraint to simulated_trades table."""
import sys
sys.path.insert(0, ".")

from db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Check existing constraints
    result = conn.execute(text("""
        SELECT constraint_name FROM information_schema.table_constraints 
        WHERE table_name='simulated_trades' AND constraint_type='UNIQUE'
    """))
    existing = [r[0] for r in result.fetchall()]
    print('Existing constraints:', existing)
    
    # Add constraint if not exists
    if 'uix_simtrade_run_date_ticker' not in existing:
        conn.execute(text("""
            ALTER TABLE simulated_trades 
            ADD CONSTRAINT uix_simtrade_run_date_ticker 
            UNIQUE (backtest_run_id, trade_date, ticker)
        """))
        conn.commit()
        print('✓ Constraint added')
    else:
        print('✓ Constraint already exists')
