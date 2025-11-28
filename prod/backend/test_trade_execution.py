"""
Test script for Alpaca trade execution with fixed 2x leverage.

Run this BEFORE market opens on Monday to verify:
1. Alpaca connection works
2. Account has sufficient buying power
3. Order placement works (paper trading)
4. Position sizing with 2x leverage is correct

Usage:
    python test_trade_execution.py
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from execution.order_executor import get_executor
from core.config import settings

ET = ZoneInfo("America/New_York")

# =============================================================================
# POSITION SIZING CONFIGURATION
# =============================================================================
CAPITAL = 1000.0          # Your trading capital
LEVERAGE = 2.0            # Fixed 2x leverage
RISK_PER_TRADE_PCT = 0.01 # 1% risk per trade = $10 on $1000

# With 2x leverage:
# - Buying power = $1000 * 2 = $2000
# - Max position = $2000 / number_of_trades
# - If Top 20 trades, max per trade = $100 position value


def calculate_position_size(
    entry_price: float,
    stop_price: float,
    capital: float = CAPITAL,
    leverage: float = LEVERAGE,
    risk_pct: float = RISK_PER_TRADE_PCT,
) -> dict:
    """
    Calculate position size with fixed 2x leverage.
    
    Two approaches:
    1. Risk-based: Size based on stop distance and risk tolerance
    2. Equal-weight: Divide leveraged capital equally across trades
    
    We use risk-based for this strategy.
    """
    # Risk in dollars
    risk_dollars = capital * risk_pct  # $10 on $1000 @ 1%
    
    # Stop distance
    stop_distance = abs(entry_price - stop_price)
    stop_distance_pct = stop_distance / entry_price * 100
    
    # Shares based on risk
    # If stop distance = $1, and risk = $10, then shares = 10
    shares_by_risk = int(risk_dollars / stop_distance) if stop_distance > 0 else 0
    
    # Position value
    position_value = shares_by_risk * entry_price
    
    # Actual leverage used
    actual_leverage = position_value / capital if capital > 0 else 0
    
    # Check if within leverage limit
    max_position_value = capital * leverage
    
    if position_value > max_position_value:
        # Cap at max leverage
        shares_capped = int(max_position_value / entry_price)
        position_value_capped = shares_capped * entry_price
        actual_leverage_capped = position_value_capped / capital
        
        return {
            "shares": shares_capped,
            "position_value": round(position_value_capped, 2),
            "leverage_used": round(actual_leverage_capped, 2),
            "capped": True,
            "original_shares": shares_by_risk,
            "stop_distance_pct": round(stop_distance_pct, 2),
            "risk_dollars": round(risk_dollars, 2),
        }
    
    return {
        "shares": shares_by_risk,
        "position_value": round(position_value, 2),
        "leverage_used": round(actual_leverage, 2),
        "capped": False,
        "stop_distance_pct": round(stop_distance_pct, 2),
        "risk_dollars": round(risk_dollars, 2),
    }


def test_account_connection():
    """Test 1: Verify Alpaca connection and account status."""
    print("\n" + "=" * 60)
    print("TEST 1: Account Connection")
    print("=" * 60)
    
    executor = get_executor()
    account = executor.get_account()
    
    if "error" in account:
        print(f"❌ FAILED: {account['error']}")
        return False
    
    print(f"✓ Connected to Alpaca")
    print(f"  Paper Mode: {settings.ALPACA_PAPER}")
    print(f"  Equity: ${account['equity']:,.2f}")
    print(f"  Cash: ${account['cash']:,.2f}")
    print(f"  Buying Power: ${account['buying_power']:,.2f}")
    print(f"  Day Trade Count: {account['day_trade_count']}")
    print(f"  PDT Status: {account['pattern_day_trader']}")
    print(f"  Trading Blocked: {account['trading_blocked']}")
    
    if account['trading_blocked']:
        print("❌ WARNING: Trading is blocked!")
        return False
    
    return True


def test_position_sizing():
    """Test 2: Verify position sizing calculations."""
    print("\n" + "=" * 60)
    print("TEST 2: Position Sizing (Fixed 2x Leverage)")
    print("=" * 60)
    
    print(f"  Capital: ${CAPITAL:,.2f}")
    print(f"  Fixed Leverage: {LEVERAGE}x")
    print(f"  Max Position Value: ${CAPITAL * LEVERAGE:,.2f}")
    print(f"  Risk per Trade: {RISK_PER_TRADE_PCT * 100}% = ${CAPITAL * RISK_PER_TRADE_PCT:.2f}")
    
    # Test scenarios
    test_cases = [
        {"entry": 50.00, "stop": 49.50, "side": "LONG", "desc": "Tight stop (1%)"},
        {"entry": 100.00, "stop": 95.00, "side": "LONG", "desc": "Wide stop (5%)"},
        {"entry": 25.00, "stop": 24.75, "side": "LONG", "desc": "Low price stock"},
        {"entry": 200.00, "stop": 198.00, "side": "LONG", "desc": "High price stock"},
    ]
    
    print("\n  Position Sizing Examples:")
    print("  " + "-" * 55)
    
    for tc in test_cases:
        sizing = calculate_position_size(tc["entry"], tc["stop"])
        
        print(f"\n  {tc['desc']}")
        print(f"    Entry: ${tc['entry']:.2f} | Stop: ${tc['stop']:.2f}")
        print(f"    Stop Distance: {sizing['stop_distance_pct']:.2f}%")
        print(f"    Shares: {sizing['shares']} | Value: ${sizing['position_value']:.2f}")
        print(f"    Leverage Used: {sizing['leverage_used']:.2f}x", end="")
        if sizing['capped']:
            print(f" (CAPPED from {sizing['original_shares']} shares)")
        else:
            print()
    
    return True


def test_order_placement_dry_run():
    """Test 3: Dry run order placement (doesn't actually submit)."""
    print("\n" + "=" * 60)
    print("TEST 3: Order Placement Dry Run")
    print("=" * 60)
    
    # Example trade
    symbol = "AAPL"
    entry_price = 230.00  # Example
    stop_price = 228.50   # 0.65% stop
    side = "LONG"
    
    sizing = calculate_position_size(entry_price, stop_price)
    
    print(f"  Symbol: {symbol}")
    print(f"  Side: {side}")
    print(f"  Entry Price: ${entry_price:.2f}")
    print(f"  Stop Price: ${stop_price:.2f}")
    print(f"  Shares: {sizing['shares']}")
    print(f"  Position Value: ${sizing['position_value']:.2f}")
    print(f"  Leverage: {sizing['leverage_used']:.2f}x")
    print(f"  Risk: ${sizing['risk_dollars']:.2f}")
    
    print("\n  [DRY RUN - Order NOT submitted]")
    print("  To test actual order placement, use test_live_order()")
    
    return True


def test_live_order():
    """
    Test 4: Place a REAL test order (paper account only!).
    
    ⚠️ Only run this on PAPER account!
    """
    print("\n" + "=" * 60)
    print("TEST 4: Live Order Test (Paper Account)")
    print("=" * 60)
    
    if not settings.ALPACA_PAPER:
        print("❌ ABORTED: This test only runs on paper account!")
        print("   Set ALPACA_PAPER=true in .env")
        return False
    
    executor = get_executor()
    
    # Use a cheap, liquid stock for testing
    symbol = "F"  # Ford - usually around $10-12
    
    # Get current price (approximate)
    # In real use, we'd get this from the scanner
    entry_price = 11.00  # Adjust based on current Ford price
    stop_price = 10.90   # 0.9% stop
    
    sizing = calculate_position_size(entry_price, stop_price)
    
    print(f"  Symbol: {symbol}")
    print(f"  Side: LONG")
    print(f"  Entry (Stop Order): ${entry_price:.2f}")
    print(f"  Stop Loss: ${stop_price:.2f}")
    print(f"  Shares: {sizing['shares']}")
    
    # Confirm before placing
    confirm = input("\n  Place this order? (yes/no): ").strip().lower()
    
    if confirm != "yes":
        print("  Order cancelled by user")
        return False
    
    # Place the order
    result = executor.place_entry_order(
        symbol=symbol,
        side="LONG",
        shares=sizing['shares'],
        entry_price=entry_price,
        stop_price=stop_price,
    )
    
    print(f"\n  Result: {result['status']}")
    if result['status'] == 'submitted':
        print(f"  ✓ Order ID: {result['order_id']}")
        print(f"  ✓ Order Status: {result['order_status']}")
        print("\n  Check Alpaca dashboard to verify order")
    else:
        print(f"  ❌ Reason: {result.get('reason', 'Unknown')}")
    
    return result['status'] == 'submitted'


def test_get_positions_and_orders():
    """Test 5: Get current positions and open orders."""
    print("\n" + "=" * 60)
    print("TEST 5: Current Positions & Orders")
    print("=" * 60)
    
    executor = get_executor()
    
    # Positions
    positions = executor.get_positions()
    print(f"\n  Open Positions: {len(positions)}")
    for p in positions:
        print(f"    {p['symbol']}: {p['qty']} shares @ ${p['entry_price']:.2f}")
        print(f"      P&L: ${p['unrealized_pnl']:.2f} ({p['unrealized_pnl_pct']:.2f}%)")
    
    # Orders
    orders = executor.get_open_orders()
    print(f"\n  Open Orders: {len(orders)}")
    for o in orders:
        print(f"    {o['symbol']}: {o['side']} {o['qty']} @ ${o.get('stop_price', 'N/A')}")
        print(f"      Status: {o['status']} | Type: {o['type']}")
    
    return True


def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("ALPACA TRADE EXECUTION TEST SUITE")
    print(f"Time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S ET')}")
    print("=" * 60)
    
    tests = [
        ("Account Connection", test_account_connection),
        ("Position Sizing", test_position_sizing),
        ("Order Placement Dry Run", test_order_placement_dry_run),
        ("Current Positions & Orders", test_get_positions_and_orders),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n❌ {name} FAILED with exception: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for name, passed in results:
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
    
    passed_count = sum(1 for _, p in results if p)
    print(f"\n  {passed_count}/{len(results)} tests passed")
    
    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print("  1. If all tests pass, run: test_live_order()")
    print("     This will place a real order on paper account")
    print("  2. Verify order appears in Alpaca dashboard")
    print("  3. Cancel the test order before market opens")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
