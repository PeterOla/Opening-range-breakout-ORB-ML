# Production Trading System Design

## Architecture

```
prod/
├── backend/           # FastAPI server
│   ├── api/
│   │   └── routes/   # REST endpoints (scanner, positions, account, etc.)
│   ├── core/         # Config, settings
│   ├── db/           # SQLAlchemy models + database
│   ├── execution/    # Alpaca executor & order management
│   ├── services/     # Business logic
│   │   ├── polygon_client.py   # Polygon API for historical data
│   │   ├── data_sync.py        # Nightly data refresh
│   │   ├── orb_scanner.py      # Hybrid scanner (DB + Alpaca)
│   │   ├── signal_engine.py    # ORB signal generation
│   │   └── universe.py         # Stock universe management
│   └── main.py       # FastAPI app entry
│
├── frontend/         # Next.js dashboard
│   ├── src/
│   │   ├── app/      # Next.js 14 app router
│   │   ├── components/  # React components
│   │   └── lib/      # API client, WebSocket hooks
│   └── package.json
│
└── shared/           # Common types/schemas
    └── types.py      # Pydantic models shared across stack
```

---

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────┐     ┌──────────────────────────────────────┐  │
│  │   Polygon API   │────▶│          daily_bars table            │  │
│  │  (Nightly Sync) │     │  symbol, date, OHLCV, ATR, avg_vol   │  │
│  └─────────────────┘     │  Rolling 30-day window               │  │
│                          └──────────────────────────────────────┘  │
│                                         │                           │
│                                         ▼                           │
│  ┌─────────────────┐     ┌──────────────────────────────────────┐  │
│  │   Alpaca API    │────▶│       opening_ranges table           │  │
│  │  (Live @ 9:35)  │     │  OR bar, direction, RVOL, rank       │  │
│  └─────────────────┘     │  Candidates that pass filters        │  │
│                          └──────────────────────────────────────┘  │
│                                         │                           │
└─────────────────────────────────────────┼───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       SIGNAL LAYER                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                     Signal Engine                             │  │
│  │  ──────────────────────────────────────────────────────────  │  │
│  │  1. Direction: Bullish OR → LONG | Bearish OR → SHORT        │  │
│  │  2. Entry: Stop order at OR high (long) / OR low (short)     │  │
│  │  3. Stop Loss: 10% of 14-day ATR from entry                  │  │
│  │  4. Position Size: 1-2% risk per trade                       │  │
│  │  5. Max 20 positions (top 20 by RVOL)                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                         │                           │
└─────────────────────────────────────────┼───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      EXECUTION LAYER                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Alpaca Orders                              │  │
│  │  ──────────────────────────────────────────────────────────  │  │
│  │  • Stop orders placed after 9:35 ET                          │  │
│  │  • Bracket orders (entry + stop loss)                        │  │
│  │  • EOD exit: Close all positions by 3:55 PM ET               │  │
│  │  • Kill switch: Immediately cancel all open orders           │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## ORB Strategy Rules (Implemented)

### Universe Filter (Pre-market/Nightly)
| Criterion | Value | Source |
|-----------|-------|--------|
| Price | ≥ $5 | Polygon daily close |
| 14D Avg Volume | ≥ 1,000,000 shares | Polygon daily bars |
| 14D ATR | ≥ $0.50 | Computed from Polygon |

### Opening Range Scan (9:35 ET)
| Criterion | Value | Source |
|-----------|-------|--------|
| OR Bar | First 5-min candle (9:30-9:35) | Alpaca 5-min bars |
| Direction | Bullish (close > open) or Bearish | OR candle |
| RVOL | ≥ 100% | OR volume vs avg volume |
| Selection | Top 20 by RVOL | Ranked |

### Entry Logic
| Direction | Entry Level | Stop Loss |
|-----------|-------------|-----------|
| LONG | Buy stop at OR High | Entry - (10% × ATR) |
| SHORT | Sell stop at OR Low | Entry + (10% × ATR) |

### Position Sizing
- Risk per trade: ~1-2% of equity
- Max positions: 20 (top 20 by RVOL)
- Max leverage: 4x

### Exit Rules
- Stop loss hit → Exit
- EOD (3:55 PM ET) → Flatten all positions

---

## Dashboard Pages

### 1. **Live Trading View** (Main Page)
**Route:** `/`

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│  [Kill Switch: ON/OFF]  Paper Mode: ✓  |  Account: $50k │
├─────────────────────────────────────────────────────────┤
│  Open Positions (5)                                      │
│  ┌────────┬────────┬──────────┬──────────┬──────────┐  │
│  │ Ticker │ Side   │ Entry    │ Current  │ P&L      │  │
│  ├────────┼────────┼──────────┼──────────┼──────────┤  │
│  │ AAPL   │ LONG   │ 150.00   │ 151.50   │ +$150    │  │
│  │ TSLA   │ SHORT  │ 220.00   │ 219.00   │ +$100    │  │
│  └────────┴────────┴──────────┴──────────┴──────────┘  │
├─────────────────────────────────────────────────────────┤
│  Today's Performance                                     │
│  P&L: +$450  |  Win Rate: 60%  |  Trades: 12            │
│  [Intraday P&L Chart - Real-time line]                  │
└─────────────────────────────────────────────────────────┘
```

**Features:**
- **Kill switch toggle** (top-right) — immediately stops new orders
- **Live position table** — updates via WebSocket every 1s
- **Real-time P&L chart** — intraday equity curve
- **Account summary** — buying power, equity, day P&L

---

### 2. **Signal Monitor**
**Route:** `/signals`

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│  Active Signals (3)                    [Refresh: Auto]   │
│  ┌────────┬────────┬────────┬─────────┬─────────────┐  │
│  │ Time   │ Ticker │ Side   │ Conf    │ Status      │  │
│  ├────────┼────────┼────────┼─────────┼─────────────┤  │
│  │ 09:31  │ AAPL   │ LONG   │ 0.85    │ ✅ Filled   │  │
│  │ 09:35  │ NVDA   │ SHORT  │ 0.78    │ ⏳ Pending  │  │
│  │ 09:40  │ MSFT   │ LONG   │ 0.92    │ ❌ Rejected │  │
│  └────────┴────────┴────────┴─────────┴─────────────┘  │
├─────────────────────────────────────────────────────────┤
│  Signal History (Last 50)                                │
│  [Filterable table with signal → order → fill chain]    │
└─────────────────────────────────────────────────────────┘
```

**Features:**
- **Active signals** — generated by strategy_orb.py (ORB breakouts)
- **Signal-to-order mapping** — track latency, rejections
- **Filters** — by ticker, side, status, date

---

### 3. **Historical Performance**
**Route:** `/history`

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│  Date Range: [Last 30 Days ▼]   Strategy: [ORB 2%]     │
├─────────────────────────────────────────────────────────┤
│  Cumulative P&L                                          │
│  [Line chart: Daily equity curve]                        │
├─────────────────────────────────────────────────────────┤
│  Key Metrics                                             │
│  Total P&L: $2,450  |  Win Rate: 58%  |  Sharpe: 1.2   │
│  Max DD: -$350      |  Avg Win: $85   |  Avg Loss: -$45│
├─────────────────────────────────────────────────────────┤
│  Trade Log                                               │
│  [Table: Date, Ticker, Side, Entry, Exit, P&L, Duration]│
└─────────────────────────────────────────────────────────┘
```

**Features:**
- **Equity curve** — daily cumulative returns
- **Performance metrics** — Sharpe, Sortino, max drawdown
- **Trade log export** — CSV download

---

### 4. **System Logs**
**Route:** `/logs`

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│  Severity: [All ▼]   Component: [All ▼]                 │
├─────────────────────────────────────────────────────────┤
│  Live Logs (Auto-scroll)                                 │
│  [09:31:12] INFO  | Executor    | Placed order AAPL     │
│  [09:31:15] INFO  | Executor    | Fill confirmed AAPL   │
│  [09:32:01] WARN  | RiskManager | Position limit hit    │
│  [09:35:00] ERROR | Alpaca      | API timeout retry     │
└─────────────────────────────────────────────────────────┘
```

**Features:**
- **Real-time log stream** — WebSocket updates
- **Filters** — ERROR/WARN/INFO, by component
- **Search** — full-text across logs

---

## Tech Stack

### Backend
- **FastAPI** (Python 3.10+)
- **SQLAlchemy** + SQLite (dev) / PostgreSQL (prod)
- **alpaca-py** for Alpaca REST/streaming
- **WebSocket** for real-time updates (FastAPI native)
- **Pydantic** for request/response validation

### Frontend
- **Next.js 14** (App Router)
- **React 18** + TypeScript
- **TailwindCSS** for styling
- **Recharts** for charts (P&L, equity curves)
- **SWR** for data fetching + WebSocket hooks
- **shadcn/ui** for components (tables, buttons, modals)

### Database Schema
```sql
-- Trade execution records
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    ticker VARCHAR(10),
    side VARCHAR(5),  -- LONG/SHORT
    entry_price REAL,
    exit_price REAL,
    shares INTEGER,
    pnl REAL,
    status VARCHAR(20),  -- OPEN/CLOSED
    alpaca_order_id VARCHAR(50),
    stop_price REAL,
    entry_time DATETIME,
    exit_time DATETIME
);

-- Trading signals generated by scanner
CREATE TABLE signals (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    ticker VARCHAR(10),
    side VARCHAR(5),
    confidence REAL,
    entry_price REAL,
    stop_price REAL,
    order_id VARCHAR(50),  -- Link to Alpaca order
    status VARCHAR(20)  -- PENDING/FILLED/REJECTED
);

-- System logs
CREATE TABLE logs (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    level VARCHAR(10),  -- INFO/WARN/ERROR
    component VARCHAR(50),
    message TEXT,
    extra_data TEXT
);

-- Daily performance metrics
CREATE TABLE daily_metrics (
    id INTEGER PRIMARY KEY,
    date DATETIME UNIQUE,
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    total_pnl REAL,
    max_drawdown REAL,
    win_rate REAL,
    starting_equity REAL,
    ending_equity REAL
);

-- Historical daily bars from Polygon (rolling 30-day)
CREATE TABLE daily_bars (
    id INTEGER PRIMARY KEY,
    symbol VARCHAR(10),
    date DATETIME,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    vwap REAL,
    atr_14 REAL,        -- Pre-computed 14-day ATR
    avg_volume_14 REAL  -- Pre-computed 14-day avg volume
);

-- Opening range data captured each trading day
CREATE TABLE opening_ranges (
    id INTEGER PRIMARY KEY,
    symbol VARCHAR(10),
    date DATETIME,
    or_open REAL,
    or_high REAL,
    or_low REAL,
    or_close REAL,
    or_volume REAL,
    direction INTEGER,      -- 1=bullish, -1=bearish, 0=doji
    rvol REAL,
    atr REAL,
    avg_volume REAL,
    passed_filters BOOLEAN,
    rank INTEGER,           -- RVOL rank (1-20 = top 20)
    entry_price REAL,
    stop_price REAL,
    signal_generated BOOLEAN,
    order_placed BOOLEAN
);
```

---

## API Endpoints

### REST — Scanner & Data
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scanner/run` | GET/POST | Run ORB scan (hybrid: DB + Alpaca) |
| `/api/scanner/today` | GET | Get today's scanned candidates |
| `/api/scanner/sync` | POST | Sync daily bars from Polygon |
| `/api/scanner/universe` | GET | Get symbols passing base filters |
| `/api/scanner/health` | GET | Scanner status + DB stats |
| `/api/scanner/cleanup` | DELETE | Remove old daily bars (>30 days) |

### REST — Trading & Account
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/positions` | GET | Current open positions |
| `/api/account` | GET | Account balance, buying power |
| `/api/trades` | GET | Historical trade log (paginated) |
| `/api/signals` | GET | Recent signals + statuses |
| `/api/metrics` | GET | Performance stats (Sharpe, win rate) |
| `/api/system/kill-switch` | POST | Toggle kill switch on/off |
| `/api/logs` | GET | System logs (paginated, filterable) |

### WebSocket
- `/ws/live` — Streams:
  - Position updates (every 1s)
  - Trade fills (real-time)
  - P&L changes
  - New signals
  - Log messages

---

## Safety & Controls

1. **Kill Switch** — Frontend toggle → backend stops all new orders
2. **Paper Mode Toggle** — Switch Alpaca env without redeployment
3. **Daily Loss Limit** — Auto-stop if down >5% (configurable)
4. **Max Positions** — Hard limit (default: 5)
5. **Manual Override** — Force-close position from dashboard

---

## Deployment Plan

### Phase 1: Local Development
- Backend: `uvicorn main:app --reload` (port 8000)
- Frontend: `npm run dev` (port 3000)
- SQLite for data

### Phase 2: Paper Trading Staging
- Docker Compose: backend + frontend + PostgreSQL
- Deploy to VPS (DigitalOcean/AWS)
- Alpaca paper account

### Phase 3: Live Production
- Same infrastructure, switch Alpaca to live keys
- Add Nginx reverse proxy
- Set up monitoring (Sentry, Grafana)

---

## Next Steps

### Completed ✅
1. ~~Backend skeleton~~ — FastAPI app + DB models
2. ~~Frontend skeleton~~ — Next.js pages + API client  
3. ~~Polygon client~~ — Daily bars fetching
4. ~~Data sync service~~ — Nightly refresh + ATR/volume calc
5. ~~Hybrid scanner~~ — DB metrics + Alpaca live OR
6. ~~Database tables~~ — daily_bars, opening_ranges

### In Progress 🔄
7. **Signal engine** — Generate signals from scan results
8. **Order execution** — Place stop orders on Alpaca

### Pending ⏳
9. **EOD scheduler** — Flatten positions at 3:55 PM ET
10. **WebSocket streaming** — Live position updates
11. **Frontend wiring** — Connect dashboard to new endpoints
12. **Paper trade validation** — 2-4 weeks testing

---
                                      
## Daily Operations Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│  NIGHTLY (After Market Close)                                    │
│  ─────────────────────────────────────────────────────────────  │
│  POST /api/scanner/sync                                          │
│  • Fetch 14-day daily bars from Polygon                         │
│  • Compute ATR(14), avg_volume(14) for each symbol              │
│  • Store in daily_bars table                                    │
│  • Delete bars older than 30 days                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  9:35 AM ET (After Opening Range Formed)                         │
│  ─────────────────────────────────────────────────────────────  │
│  GET /api/scanner/run                                            │
│  • Fetch live 5-min bars from Alpaca                            │
│  • Extract OR (9:30-9:35 bar)                                   │
│  • Compute RVOL, apply filters                                  │
│  • Rank by RVOL, select top 20                                  │
│  • Store in opening_ranges table                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  9:36+ AM ET (Trading Session)                                   │
│  ─────────────────────────────────────────────────────────────  │
│  Signal Engine generates orders:                                 │
│  • LONG: Buy stop at OR high, stop loss at entry - 10% ATR      │
│  • SHORT: Sell stop at OR low, stop loss at entry + 10% ATR     │
│  • Position size based on 1-2% risk                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3:55 PM ET (Before Close)                                       │
│  ─────────────────────────────────────────────────────────────  │
│  EOD Scheduler:                                                  │
│  • Cancel unfilled stop orders                                  │
│  • Close all open positions at market                           │
│  • Log daily P&L to daily_metrics                               │
└─────────────────────────────────────────────────────────────────┘
```
