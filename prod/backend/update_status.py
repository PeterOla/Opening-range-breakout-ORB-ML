"""Update existing OPEN trades to PENDING and add PENDING to enum"""
import sys
sys.path.insert(0, ".")

from db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # First add PENDING to the PostgreSQL enum type
    try:
        conn.execute(text("ALTER TYPE positionstatus ADD VALUE IF NOT EXISTS 'PENDING'"))
        conn.commit()
        print("Added PENDING to positionstatus enum")
    except Exception as e:
        print(f"Enum update skipped (may already exist): {e}")
        conn.rollback()
    
    # Now update existing OPEN trades to PENDING
    result = conn.execute(text("UPDATE trades SET status = 'PENDING' WHERE status = 'OPEN'"))
    conn.commit()
    print(f"Updated {result.rowcount} trades to PENDING")
