"""
Migrate production trades table to add missing columns.
Run once to sync model with production DB.
"""
import sys
sys.path.insert(0, ".")

from db.database import engine
from sqlalchemy import text

# Columns to add (that exist in model but not in production)
COLUMNS_TO_ADD = [
    # exit_reason already exists as 'exit_reason' in model
    ("exit_reason", "VARCHAR(50)"),
    ("pnl_percent", "FLOAT"),
    ("alpaca_exit_order_id", "VARCHAR(50)"),
    ("target_price", "FLOAT"),
    # Rename take_price to target_price handled separately
    
    # Opening Range audit fields
    ("or_open", "FLOAT"),
    ("or_high", "FLOAT"),
    ("or_low", "FLOAT"),
    ("or_close", "FLOAT"),
    ("or_volume", "FLOAT"),
    
    # Indicator audit fields
    ("atr_14", "FLOAT"),
    ("avg_volume_14", "FLOAT"),
    ("rvol", "FLOAT"),
    ("prev_close", "FLOAT"),
    
    # Selection metadata
    ("rank", "INTEGER"),
    
    # Timestamps
    ("created_at", "TIMESTAMP DEFAULT NOW()"),
    ("updated_at", "TIMESTAMP DEFAULT NOW()"),
]

def migrate():
    with engine.connect() as conn:
        # First, get existing columns
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'trades'"
        ))
        existing = {r[0] for r in result}
        print(f"Existing columns: {existing}")
        
        # Add missing columns
        for col_name, col_type in COLUMNS_TO_ADD:
            if col_name not in existing:
                sql = f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}"
                print(f"Adding column: {col_name}")
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    print(f"  ✓ Added {col_name}")
                except Exception as e:
                    print(f"  ✗ Failed: {e}")
            else:
                print(f"  - {col_name} already exists")
        
        # Special case: rename take_price to target_price if take_price exists
        if "take_price" in existing and "target_price" not in existing:
            print("Renaming take_price to target_price...")
            try:
                conn.execute(text("ALTER TABLE trades RENAME COLUMN take_price TO target_price"))
                conn.commit()
                print("  ✓ Renamed take_price to target_price")
            except Exception as e:
                print(f"  ✗ Failed: {e}")
        
        # Verify final state
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'trades' ORDER BY ordinal_position"
        ))
        final_columns = [r[0] for r in result]
        print(f"\nFinal columns ({len(final_columns)}):")
        for col in final_columns:
            print(f"  - {col}")


if __name__ == "__main__":
    print("Migrating trades table...")
    migrate()
    print("\n✓ Migration complete!")
