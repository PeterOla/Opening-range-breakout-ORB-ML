"""Delete stale test trades"""
import sys
sys.path.insert(0, ".")

from db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text("DELETE FROM trades WHERE ticker = 'F' AND status = 'PENDING'"))
    conn.commit()
    print(f"Deleted {result.rowcount} stale test trades")
