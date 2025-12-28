# TradeZero API

A robust wrapper for the TradeZero Web Platform using Selenium, available for both **Python** and **Node.js**. This library allows you to automate trading on TradeZero, including placing orders, managing positions, and locating shares for shorting.

## Features

- **Automated Login**: Handles login to the TradeZero web platform.
- **Order Management**: Place Limit, Market, and Stop orders.
- **Short Selling**: Automated share locating (Easy to Borrow & Hard to Borrow).
- **Portfolio Management**: Retrieve current positions and active orders.
- **Market Data**: Get real-time Level 1 data (Bid, Ask, Last, Volume).
- **Headless Mode**: Run in the background without a visible browser window.

---

## Python Installation

1. Install via pip (local):
   ```bash
   pip install .
   ```

### Python Usage

```python
from tradezero import TradeZero, Order, TIF

# Initialize
tz = TradeZero("username", "password")

# Buy 100 shares of AAPL at $150.00
tz.limit_order(Order.BUY, "AAPL", 100, 150.00, TIF.DAY)

# Short Sell with Auto-Locate
locate = tz.locate_stock("SPCE", 500, max_price=0.03)
if locate.status == 'success':
    tz.limit_order(Order.SHORT, "SPCE", 500, 15.50)
```

---

## Node.js Installation

1. Install via npm (local):
   ```bash
   npm install .
   ```

### Node.js Usage

```javascript
const { TradeZero, Order, TIF } = require('tradezero-api');

(async () => {
    // Initialize
    const tz = new TradeZero("username", "password");
    await tz.init();

    // Buy 100 shares of AAPL at $150.00
    await tz.limitOrder(Order.BUY, "AAPL", 100, 150.00, TIF.DAY);

    // Market Sell
    await tz.marketOrder(Order.SELL, "TSLA", 50);

    await tz.exit();
})();
```

## Disclaimer

This software is for educational purposes only. Use at your own risk. The authors are not responsible for any financial losses incurred while using this software. Automated trading carries significant risk.
