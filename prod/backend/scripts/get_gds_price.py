import sys
from pathlib import Path
# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from execution.alpaca_client import get_data_client
from alpaca.data.requests import StockLatestQuoteRequest

try:
    client = get_data_client()
    req = StockLatestQuoteRequest(symbol_or_symbols=["GDS"])
    quote = client.get_stock_latest_quote(req)
    gds = quote["GDS"]
    print(f"GDS Price (Alpaca): Bid={gds.bid_price}, Ask={gds.ask_price}")
except Exception as e:
    print(f"Alpaca Fetch Failed: {e}")
    # Fallback to yfinance if available
    try:
        import yfinance as yf
        ticker = yf.Ticker("GDS")
        hist = ticker.history(period="1d")
        if not hist.empty:
            print(f"GDS Price (Yahoo): {hist['Close'].iloc[-1]}")
        else:
            print("Yahoo Finance: No data found")
    except ImportError:
        print("yfinance not installed")
    except Exception as e2:
        print(f"Yahoo Fetch Failed: {e2}")
