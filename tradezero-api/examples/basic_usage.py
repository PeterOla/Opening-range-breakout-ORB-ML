import os
import time
from tradezero import TradeZero, Order, TIF

def main():
    # Load credentials from environment variables or hardcode them (not recommended)
    username = os.getenv("TRADEZERO_USERNAME")
    password = os.getenv("TRADEZERO_PASSWORD")

    if not username or not password:
        print("Please set TRADEZERO_USERNAME and TRADEZERO_PASSWORD environment variables.")
        return

    print("Initializing TradeZero Client...")
    tz = TradeZero(username, password, headless=False)

    try:
        # Get Market Data
        symbol = "AAPL"
        print(f"\nFetching data for {symbol}...")
        data = tz.get_market_data(symbol)
        if data:
            print(f"Data: {data}")

        # Check Portfolio
        print("\nChecking Portfolio...")
        portfolio = tz.get_portfolio()
        if not portfolio.empty:
            print(portfolio)
        else:
            print("Portfolio is empty.")

        # Example: Place a Limit Buy Order (far below market to avoid fill)
        # print(f"\nPlacing Test Order for {symbol}...")
        # tz.limit_order(Order.BUY, symbol, 1, 100.00, TIF.DAY)
        
        # Example: Cancel the order (you would need the order ID)
        # orders = tz.get_active_orders()
        # if not orders.empty:
        #     print("Active Orders:", orders)
        #     # tz.cancel_order(orders.iloc[0]['ref_number'])

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        print("\nClosing client...")
        # tz.exit() # Uncomment to close the browser automatically

if __name__ == "__main__":
    main()
