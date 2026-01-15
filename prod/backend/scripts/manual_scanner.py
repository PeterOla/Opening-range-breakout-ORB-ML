
import asyncio
import sys
from pathlib import Path

# Force UTF-8 for Windows consoles 🚀
if sys.platform == "win32":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

# Setup path
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

# Import AFTER path setup
from services.orb_scanner import scan_orb_candidates
from core.config import settings

async def main():
    print("\n🔍 STARTING MANUAL ORB SCANNER...")
    print(f"   Environment: {'PAPER' if settings.ALPACA_PAPER else 'LIVE'}")
    
    try:
        result = await scan_orb_candidates()
        
        status = result.get('status')
        if status == 'success':
            total = result.get('candidates_total', 0)
            top_n = result.get('candidates_top_n', 0)
            
            print(f"\n✅ SCAN COMPLETE")
            print(f"   Candidates Found: {total}")
            print(f"   Top Candidates:   {top_n}")
            
            print("\n📋 TOP CANDIDATES:")
            # We need to fetch the results from DB ideally, or print what return gave us if detailed
            # The return of scan_orb_candidates is just status dict usually.
            # Let's check if we can query the DB for the results just generated.
            from state.duckdb_store import DuckDBStateStore
            from datetime import date
            
            store = DuckDBStateStore()
            con = store._connect()
            today = date.today()
            
            query = """
                SELECT symbol, rvol, or_high, or_low, or_volume
                FROM opening_ranges 
                WHERE date = ? 
                ORDER BY rvol DESC 
                LIMIT 5
            """
            rows = con.execute(query, [today]).fetchall()
            
            if not rows:
                print("   (No candidates found in database)")
            else:
                print(f"   {'Symbol':<10} {'RVOL':<10} {'High':<10} {'Low':<10} {'Vol':<10}")
                print(f"   {'-'*50}")
                for row in rows:
                    sym, rvol, h, l, v = row
                    print(f"   {sym:<10} {rvol:<10.2f} {h:<10.2f} {l:<10.2f} {v:<10.0f}")
                    
        else:
            print(f"\n❌ SCAN FAILED: {result.get('error')}")
            
    except Exception as e:
        print(f"\n💥 CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
