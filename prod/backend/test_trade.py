"""Test signal generation and execution with buying power constraint."""
import asyncio
from services.signal_engine import run_signal_generation
from core.config import get_strategy_config
from execution.alpaca_client import get_alpaca_client


async def main():
    # Check account
    client = get_alpaca_client()
    account = client.get_account()
    print(f"Account Equity: ${float(account.equity):,.2f}")
    print(f"Buying Power: ${float(account.buying_power):,.2f}")
    print()
    
    # Get strategy
    strategy = get_strategy_config()
    print(f"Strategy: {strategy['name']}")
    print(f"Top-N: {strategy['top_n']}, Direction: {strategy['direction']}")
    print(f"Risk/Trade: {strategy['risk_per_trade']*100}%")
    print()
    
    # Generate signals
    print("Generating signals...")
    result = await run_signal_generation()
    
    print(f"Status: {result['status']}")
    print(f"Signals generated: {result.get('signals_generated', 0)}")
    print()
    
    if result.get('signals'):
        print("Signals:")
        print("-" * 60)
        for s in result['signals']:
            print(f"  {s['symbol']:6} {s['side']:5} {s['shares']:4} shares @ ${s['entry_price']:.2f} = ${s['position_value']:.0f}")
        print("-" * 60)
        print(f"Total position value: ${result.get('total_position_value', 0):,.0f}")
        print(f"Total risk: ${result.get('total_risk', 0):,.2f}")
    
    return result


if __name__ == "__main__":
    asyncio.run(main())
