from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
import pandas as pd

# Connect to local DB
DATABASE_URL = "postgresql+psycopg2://orb:orb@127.0.0.1:5433/orb"
engine = create_engine(DATABASE_URL)

def inspect_db():
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    print(f"\n📊 Database Inspection ({DATABASE_URL})")
    print("-" * 50)
    
    if not tables:
        print("No tables found.")
        return

    for table in tables:
        # Get row count
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        
        print(f"Table: {table:<20} | Rows: {count}")
        
        # Show first 3 rows
        try:
            df = pd.read_sql(f"SELECT * FROM {table} LIMIT 3", engine)
            if not df.empty:
                print(df.to_string(index=False))
            print("-" * 50)
        except Exception as e:
            print(f"Error reading table: {e}")

if __name__ == "__main__":
    inspect_db()
