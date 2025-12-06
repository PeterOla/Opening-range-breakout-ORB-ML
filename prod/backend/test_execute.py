"""Execute trades and show results."""
import asyncio
from services.scheduler import job_auto_execute_orb


async def main():
    print("Executing trades...")
    print()
    
    result = await job_auto_execute_orb()
    
    print()
    print(f"Orders placed: {result.get('orders_placed', 0)}")
    print(f"Orders failed: {result.get('orders_failed', 0)}")
    print()
    
    print("Details:")
    print("-" * 80)
    for r in result.get('results', []):
        symbol = r.get('symbol', '?')
        status = r.get('status', '?')
        reason = r.get('reason', r.get('order_status', 'ok'))
        shares = r.get('shares', 0)
        print(f"  {symbol:6} | {status:10} | {shares:3} shares | {str(reason)[:50]}")
    print("-" * 80)


if __name__ == "__main__":
    asyncio.run(main())
