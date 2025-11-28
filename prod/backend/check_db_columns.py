"""Check production DB columns"""
import sys
sys.path.insert(0, ".")

from db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'trades' ORDER BY ordinal_position"
    ))
    columns = [r[0] for r in result]
    print("Production trades columns:")
    for col in columns:
        print(f"  - {col}")
    print(f"\nTotal: {len(columns)} columns")
