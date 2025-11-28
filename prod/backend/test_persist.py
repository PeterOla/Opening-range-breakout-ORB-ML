"""Test historical scanner with trade persistence."""
import asyncio
from datetime import date
from services.historical_scanner import get_historical_top20


async def test():
    result = await get_historical_top20('2025-11-21', top_n=20)
    print(f"Status: {result['status']}")
    print(f"Summary: {result.get('summary')}")
    
    # Check if saved to DB
    from db.database import SessionLocal
    from db.models import SimulatedTrade
    from sqlalchemy import func
    
    db = SessionLocal()
    target = date(2025, 11, 21)
    
    trades = db.query(SimulatedTrade).filter(
        func.date(SimulatedTrade.trade_date) == target
    ).order_by(SimulatedTrade.rvol_rank).all()
    
    print(f"\n{'='*60}")
    print(f"Trades saved to DB: {len(trades)}")
    print(f"{'='*60}")
    
    for t in trades[:5]:
        print(f"  #{t.rvol_rank} {t.ticker} ({t.side.value}) - {t.exit_reason} - P&L: {t.pnl_pct}%")
    
    if len(trades) > 5:
        print(f"  ... and {len(trades) - 5} more")
    
    db.close()


if __name__ == "__main__":
    asyncio.run(test())
