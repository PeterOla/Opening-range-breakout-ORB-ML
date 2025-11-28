"""Test historical scanner."""
import asyncio
from services.historical_scanner import get_historical_top20

async def test():
    print("Testing historical scanner for 2025-11-21...")
    result = await get_historical_top20('2025-11-21', top_n=20)
    
    print(f"Status: {result.get('status')}")
    print(f"Mode: {result.get('mode')}")
    
    if result.get('error'):
        print(f"Error: {result.get('error')}")
    
    if result.get('candidates'):
        print(f"\nCandidates: {len(result['candidates'])}")
        for c in result['candidates'][:5]:
            print(f"  #{c['rank']} {c['symbol']} RVOL={c['rvol']} {c['direction_label']} entry=${c['entry_price']}")
    
    if result.get('summary'):
        s = result['summary']
        print(f"\nSummary:")
        print(f"  Total: {s['total_candidates']}")
        print(f"  Entered: {s['trades_entered']}")
        print(f"  W/L: {s['winners']}/{s['losers']}")
        print(f"  Win Rate: {s['win_rate']}%")
        print(f"  Total P&L: {s['total_pnl_pct']}%")

if __name__ == "__main__":
    asyncio.run(test())
