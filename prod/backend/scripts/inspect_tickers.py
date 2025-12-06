import sys
from pathlib import Path
import pandas as pd

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from db.database import engine
from sqlalchemy import text

def main():
    print("Inspecting 'tickers' table...")
    with engine.connect() as conn:
        # Check columns
        try:
            result = conn.execute(text("SELECT * FROM tickers LIMIT 1"))
            columns = result.keys()
            print(f"Columns: {list(columns)}")
            
            if 'float' in columns:
                print("✅ 'float' column exists.")
            else:
                print("❌ 'float' column MISSING.")
                return
        except Exception as e:
            print(f"Error inspecting columns: {e}")
            return

        # Check data stats
        try:
            total = conn.execute(text("SELECT COUNT(*) FROM tickers")).scalar()
            with_float = conn.execute(text("SELECT COUNT(*) FROM tickers WHERE float IS NOT NULL")).scalar()
            low_float = conn.execute(text("SELECT COUNT(*) FROM tickers WHERE float < 10000000 AND float IS NOT NULL")).scalar()
            
            print(f"\nTotal tickers: {total}")
            print(f"Tickers with float data: {with_float} ({with_float/total*100:.1f}%)")
            print(f"Low float tickers (< 10M): {low_float}")
            
            # Show sample
            print("\nSample with float data:")
            df = pd.read_sql("SELECT symbol, float FROM tickers WHERE float IS NOT NULL LIMIT 10", conn)
            print(df)
            
        except Exception as e:
            print(f"Error querying data: {e}")

if __name__ == "__main__":
    main()
