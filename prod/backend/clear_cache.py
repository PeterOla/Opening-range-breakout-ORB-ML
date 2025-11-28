"""Clear scanner cache for today and check opening_ranges"""
import sys
sys.path.insert(0, ".")

from db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Check opening_ranges
    result = conn.execute(text("SELECT COUNT(*) as cnt FROM opening_ranges WHERE date::date = '2025-11-28'"))
    row = result.fetchone()
    print(f"Opening ranges for today: {row[0]}")
    
    # Check scanner_cache
    result = conn.execute(text("SELECT * FROM scanner_cache WHERE scan_date::date = '2025-11-28'"))
    rows = result.fetchall()
    print(f"Scanner cache entries for today: {len(rows)}")
    for r in rows:
        print(f"  - {r}")
