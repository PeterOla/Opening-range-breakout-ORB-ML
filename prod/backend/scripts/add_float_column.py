import sys
from pathlib import Path
from sqlalchemy import text

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from db.database import engine

def main():
    print("Adding 'float' column to 'tickers' table...")
    with engine.connect() as conn:
        try:
            # Check if column exists first (Postgres/SQLite specific syntax might vary, but let's try generic ADD COLUMN)
            # For SQLite, ADD COLUMN is supported.
            conn.execute(text("ALTER TABLE tickers ADD COLUMN float INTEGER"))
            conn.commit()
            print("Successfully added 'float' column.")
        except Exception as e:
            print(f"Error (column might already exist): {e}")

if __name__ == "__main__":
    main()
