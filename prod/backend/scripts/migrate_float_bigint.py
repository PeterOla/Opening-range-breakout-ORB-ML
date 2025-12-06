import sys
from pathlib import Path
from sqlalchemy import text

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from db.database import engine

def main():
    print("Migrating 'float' column to BIGINT...")
    with engine.connect() as conn:
        try:
            # PostgreSQL syntax
            conn.execute(text("ALTER TABLE tickers ALTER COLUMN float TYPE BIGINT"))
            conn.commit()
            print("Successfully migrated 'float' column to BIGINT.")
        except Exception as e:
            print(f"Error migrating column: {e}")

if __name__ == "__main__":
    main()
