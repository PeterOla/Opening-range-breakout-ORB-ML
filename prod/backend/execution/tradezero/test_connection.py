from client import TradeZero, Order, TIF
import time

# REPLACE WITH YOUR CREDENTIALS
USERNAME = "YOUR_USERNAME"
PASSWORD = "YOUR_PASSWORD"

def main():
    print("Initializing TradeZero Client...")
    tz = TradeZero(USERNAME, PASSWORD, headless=False)
    
    # Give it time to load
    time.sleep(5)
    
    print(f"Current Symbol: {tz.current_symbol()}")
    
    # Test Data Fetch
    symbol = "AAPL"
    print(f"\nFetching data for {symbol}...")
    data = tz.get_market_data(symbol)
    if data:
        print(f"Bid: {data.bid}, Ask: {data.ask}, Last: {data.last}")
    
    # Test Portfolio
    print("\nFetching Portfolio...")
    portfolio = tz.get_portfolio()
    if portfolio is not None and not portfolio.empty:
        print(portfolio)
    else:
        print("Portfolio is empty or could not be read.")

    # Test Locate (Dry Run - won't accept if price > 0)
    # print("\nTesting Locate for a Microcap...")
    # locate = tz.locate_stock("MULN", 100, max_price=0.00) # 0.00 ensures we don't pay
    # print(f"Locate Result: {locate}")

    print("\nClosing...")
    tz.exit()

if __name__ == "__main__":
    main()
