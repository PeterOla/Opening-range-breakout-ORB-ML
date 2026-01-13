import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import duckdb

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from state.duckdb_store import DuckDBStateStore
from core.config import settings

def main():
    store = DuckDBStateStore()
    today = datetime.now(ZoneInfo("America/New_York")).date()
    
    print(f"Fetching signals for {today}...")
    
    # Use duckdb.connect directly since we know the path
    conn = duckdb.connect(str(store.path))
    try:
        # Check table schema first to be safe
        try:
            schema = conn.execute("DESCRIBE signals").df()
            # print(schema)
        except:
            print("Signals table might not exist yet.")
            return

        # Check generated signals
        query = f"""
            SELECT * 
            FROM signals 
            WHERE strftime(created_at, '%Y-%m-%d') = '{today}'
            AND symbol IN ('AEVA', 'IMSR')
        """
        df = conn.execute(query).df()
        
        if df.empty:
            print("No signals found in DB for AEVA or IMSR today.")
            # Maybe check candidates if signals weren't generated?
            c_query = f"""
                SELECT *
                FROM candidates
                WHERE date_trunc('day', created_at) = '{today}'
                AND symbol IN ('AEVA', 'IMSR')
            """
            c_df = conn.execute(c_query).df()
            if not c_df.empty:
                print("\nFound Candidates (but no signals?):")
                print(c_df)
            else:
                print("No candidates found either.")
        else:
            print(f"\nFound {len(df)} signals:")
            print(df.to_string())
            
            # Print specifically useful columns for execution
            print("\n--- Execution Details ---")
            for _, row in df.iterrows():
                print(f"Symbol: {row['symbol']}")
                print(f"  Side: {row['side']}")
                print(f"  Entry Limit: {row['entry_price']}")
                print(f"  Stop Loss:   {row['stop_price']}")
                # If shares aren't in signals table (usually calculated at runtime or stored in json metadata), we will calc them.
                # The schema might have 'quantity' or similar?
                print(f"  Columns: {df.columns.tolist()}")
                
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
