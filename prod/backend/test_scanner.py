"""
Test script for ORB scanner with hybrid data approach.

Usage:
1. Start server: python -m uvicorn main:app --host 127.0.0.1 --port 8000
2. Run this: python test_scanner.py
"""
import requests

BASE_URL = "http://127.0.0.1:8000"

# Test health
print("=" * 50)
print("Testing /api/scanner/health...")
r = requests.get(f"{BASE_URL}/api/scanner/health")
print(f"Status: {r.status_code}")
print(r.json())

# Test universe (should be empty until synced)
print("\n" + "=" * 50)
print("Testing /api/scanner/universe...")
r = requests.get(f"{BASE_URL}/api/scanner/universe")
print(f"Status: {r.status_code}")
data = r.json()
print(f"Symbols in DB: {data.get('count', 0)}")

# Test data sync (small batch for testing)
print("\n" + "=" * 50)
print("Testing /api/scanner/sync with 5 test symbols...")
test_symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
r = requests.post(
    f"{BASE_URL}/api/scanner/sync",
    json={"symbols": test_symbols, "lookback_days": 20}
)
print(f"Status: {r.status_code}")
print(r.json())

# Check universe again
print("\n" + "=" * 50)
print("Testing /api/scanner/universe after sync...")
r = requests.get(f"{BASE_URL}/api/scanner/universe")
print(f"Status: {r.status_code}")
data = r.json()
print(f"Symbols in DB: {data.get('count', 0)}")
if data.get('symbols'):
    for s in data['symbols'][:5]:
        print(f"  {s['symbol']}: close=${s.get('close')}, ATR={s.get('atr_14')}, AvgVol={s.get('avg_volume_14')}")

# Test scanner run (will only work during market hours)
print("\n" + "=" * 50)
print("Testing /api/scanner/run...")
r = requests.get(f"{BASE_URL}/api/scanner/run?top_n=5")
print(f"Status: {r.status_code}")
data = r.json()
print(f"Status: {data.get('status')}")
if data.get('error'):
    print(f"Error: {data.get('error')}")
if data.get('candidates'):
    print(f"Found {len(data['candidates'])} candidates:")
    for c in data['candidates']:
        print(f"  {c['symbol']}: RVOL={c['rvol']}, Dir={c['direction_label']}, Entry=${c['entry_price']}, Stop=${c['stop_price']}")
