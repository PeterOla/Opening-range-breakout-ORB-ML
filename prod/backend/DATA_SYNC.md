# Data Sync Documentation

## Overview

The ORB trading system requires daily market data (OHLCV) for all NYSE/NASDAQ stocks to compute indicators like ATR(14) and average volume. This data is fetched from **Polygon.io** and stored in a local SQLite database.

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    POLYGON.IO API                                │
│  ─────────────────────────────────────────────────────────────  │
│  • Grouped Daily Endpoint: 1 API call = all stocks for 1 day   │
│  • Ticker Reference: All NYSE/NASDAQ common stocks              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DATA SYNC SERVICE                             │
│  ─────────────────────────────────────────────────────────────  │
│  services/data_sync.py                                          │
│  • sync_daily_bars_fast() — bulk fetch all stocks               │
│  • compute_atr() — 14-day ATR calculation                       │
│  • compute_avg_volume() — 14-day average volume                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DATABASE TABLES                               │
│  ─────────────────────────────────────────────────────────────  │
│  tickers      — Stock universe (symbol, name, exchange, active) │
│  daily_bars   — OHLCV data + ATR(14) + avg_volume(14)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Automatic Sync Schedule

The scheduler (`services/scheduler.py`) runs data sync jobs automatically:

| Time (ET) | Day | Job | Description |
|-----------|-----|-----|-------------|
| 6:00 PM | Mon-Fri | `nightly_data_sync` | Fetch 14-day daily bars for all stocks |
| 6:00 PM | Sunday | `sunday_data_sync` | Sync ticker universe + 14-day bars |

### Why 6:00 PM ET?
- Market closes at 4:00 PM ET
- Polygon updates daily data by ~5:30 PM ET
- 6:00 PM gives buffer for data availability

---

## API Endpoints

### Ticker Sync

```http
POST /api/scanner/sync-tickers
```

Fetches all NYSE/NASDAQ common stocks from Polygon and stores in `tickers` table.

**Request Body (optional):**
```json
{
  "include_delisted": false
}
```

**Response:**
```json
{
  "status": "success",
  "total_fetched": 8500,
  "inserted": 8500,
  "updated": 0
}
```

**Notes:**
- Takes ~2-5 minutes (paginated API calls)
- Run once for initial setup, then weekly on Sundays

---

### Daily Bars Sync (Fast Method)

```http
POST /api/scanner/sync-daily?lookback_days=14
```

Fetches OHLCV data for **all stocks** using Polygon's grouped daily endpoint.

**Query Parameters:**
| Param | Default | Description |
|-------|---------|-------------|
| `lookback_days` | 14 | Number of days to fetch (7-30) |

**Response:**
```json
{
  "status": "success",
  "days_processed": 10,
  "days_failed": 0,
  "bars_synced": 85000,
  "unique_symbols": 8500,
  "metrics_updated": 7200
}
```

**How it works:**
1. Uses Polygon's **grouped daily** endpoint (1 call = all stocks for 1 day)
2. For 14-day lookback: ~20 API calls total
3. Computes ATR(14) and avg_volume(14) for each symbol
4. Updates filter flags on tickers table

**Runtime:** ~5 minutes for 14 days

---

### Manual Trigger via Scheduler

```http
POST /api/system/scheduler/trigger-sync
```

Manually triggers the nightly sync job. Useful for:
- Initial setup
- Catching up after downtime
- Testing

---

### Check Scheduler Status

```http
GET /api/system/scheduler
```

**Response:**
```json
{
  "status": "running",
  "jobs": [
    {
      "id": "nightly_data_sync",
      "name": "Nightly Data Sync",
      "next_run": "2025-11-26T18:00:00-05:00",
      "trigger": "cron[hour='18', minute='0', day_of_week='mon-fri']"
    }
  ]
}
```

---

## Database Schema

### `tickers` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `symbol` | VARCHAR(10) | Stock ticker (e.g., AAPL) |
| `name` | VARCHAR(255) | Company name |
| `primary_exchange` | VARCHAR(10) | XNYS (NYSE) or XNAS (NASDAQ) |
| `type` | VARCHAR(10) | CS = Common Stock |
| `active` | BOOLEAN | Currently trading |
| `meets_price_filter` | BOOLEAN | Price ≥ $5 |
| `meets_volume_filter` | BOOLEAN | Avg volume ≥ 1M |
| `meets_atr_filter` | BOOLEAN | ATR ≥ $0.50 |

### `daily_bars` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `symbol` | VARCHAR(10) | Stock ticker |
| `date` | DATETIME | Trading date |
| `open` | FLOAT | Open price |
| `high` | FLOAT | High price |
| `low` | FLOAT | Low price |
| `close` | FLOAT | Close price |
| `volume` | FLOAT | Trading volume |
| `vwap` | FLOAT | Volume-weighted avg price |
| `atr_14` | FLOAT | 14-day ATR (latest bar only) |
| `avg_volume_14` | FLOAT | 14-day avg volume (latest bar only) |

> **Note:** ATR and avg_volume are only stored on the latest bar per symbol to save space.
> For audit purposes, these values are **snapshotted into the trades table** at entry time.

### `trades` Table (Audit-Ready)

Full trade lifecycle with metrics captured at entry time:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `trade_date` | DATETIME | Trading day |
| `ticker` | VARCHAR(10) | Stock ticker |
| `side` | ENUM | LONG or SHORT |
| `entry_price` | FLOAT | Filled entry price |
| `entry_time` | DATETIME | Entry timestamp |
| `exit_price` | FLOAT | Exit price (when closed) |
| `exit_time` | DATETIME | Exit timestamp |
| `exit_reason` | VARCHAR(50) | STOP_LOSS, EOD, MANUAL, TARGET |
| `shares` | INTEGER | Position size |
| `pnl` | FLOAT | Profit/loss in dollars |
| `pnl_percent` | FLOAT | Profit/loss percentage |
| `status` | ENUM | OPEN or CLOSED |
| **Audit Fields** | | *Snapshot at entry time* |
| `or_open` | FLOAT | Opening range open |
| `or_high` | FLOAT | Opening range high |
| `or_low` | FLOAT | Opening range low |
| `or_close` | FLOAT | Opening range close |
| `or_volume` | FLOAT | Opening range volume |
| `atr_14` | FLOAT | 14-day ATR at entry |
| `avg_volume_14` | FLOAT | 14-day avg volume at entry |
| `rvol` | FLOAT | Relative volume (OR vol ÷ avg vol) |
| `prev_close` | FLOAT | Previous day close |
| `rank` | INTEGER | RVOL rank (1-20) |

### `signals` Table

Generated signals before order placement:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `signal_date` | DATETIME | Trading day |
| `ticker` | VARCHAR(10) | Stock ticker |
| `side` | ENUM | LONG or SHORT |
| `entry_price` | FLOAT | Target entry (OR high/low) |
| `stop_price` | FLOAT | Stop loss level |
| `status` | ENUM | PENDING, FILLED, REJECTED, CANCELLED |
| `trade_id` | INTEGER | Link to trades table (when filled) |
| **Audit Fields** | | *Same as trades table* |

---

## Usage Workflow

### First-Time Setup

1. **Sync ticker universe:**
   ```bash
   curl -X POST http://localhost:8000/api/scanner/sync-tickers
   ```

2. **Fetch 14-day daily data:**
   ```bash
   curl -X POST "http://localhost:8000/api/scanner/sync-daily?lookback_days=14"
   ```

3. **Verify:**
   ```bash
   curl http://localhost:8000/api/scanner/health
   curl http://localhost:8000/api/scanner/ticker-stats
   ```

### Daily Operations

The scheduler handles everything automatically:
- **6:00 PM ET** — Daily bars sync (Mon-Fri)
- **6:00 PM ET Sunday** — Ticker refresh + daily bars

### Manual Catch-Up

If the system was down, trigger sync manually:
```bash
curl -X POST http://localhost:8000/api/system/scheduler/trigger-sync
```

---

## Rate Limiting

Polygon.io Starter tier: **5 API calls/minute**

The sync service handles this by:
- Using grouped daily endpoint (1 call = all stocks)
- 12-second delay between API calls
- ~20 calls for 14-day sync = ~4 minutes

---

## Computed Indicators

### ATR (Average True Range)

14-day ATR computed as:
```
TR = max(High - Low, |High - PrevClose|, |Low - PrevClose|)
ATR = SMA(TR, 14)
```

Used for:
- Stop loss sizing (10% of ATR from entry)
- Universe filtering (ATR ≥ $0.50)

### Average Volume

14-day simple moving average of daily volume.

Used for:
- RVOL calculation (Opening Range volume ÷ avg volume)
- Universe filtering (avg volume ≥ 1M shares)

---

## Troubleshooting

### No data after sync

Check Polygon API key:
```bash
curl http://localhost:8000/api/scanner/health
```

### Sync taking too long

- Reduce `lookback_days` to 7 for daily refresh
- Use 14 days only for initial setup or weekly refresh

### Missing ATR/volume metrics

Requires at least 14 days of data. Check:
```bash
curl "http://localhost:8000/api/scanner/universe?min_price=0&min_atr=0&min_avg_volume=0"
```

---

## Trade Audit Queries

All metrics are captured at entry time, enabling full trade analysis:

### Daily Trade Summary
```sql
SELECT 
    trade_date,
    COUNT(*) as trades,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winners,
    SUM(pnl) as total_pnl,
    AVG(rvol) as avg_rvol,
    AVG(atr_14) as avg_atr
FROM trades
WHERE status = 'CLOSED'
GROUP BY trade_date
ORDER BY trade_date DESC;
```

### Analyse Winners vs Losers by RVOL
```sql
SELECT 
    CASE WHEN pnl > 0 THEN 'Winner' ELSE 'Loser' END as outcome,
    AVG(rvol) as avg_rvol,
    AVG(atr_14) as avg_atr,
    AVG(or_volume) as avg_or_volume,
    COUNT(*) as count
FROM trades
WHERE status = 'CLOSED'
GROUP BY outcome;
```

### Top 20 Trades by P&L
```sql
SELECT 
    trade_date, ticker, side, 
    entry_price, exit_price, pnl, pnl_percent,
    rvol, atr_14, rank, exit_reason
FROM trades
WHERE status = 'CLOSED'
ORDER BY pnl DESC
LIMIT 20;
```

### Filter Performance by Rank
```sql
SELECT 
    rank,
    COUNT(*) as trades,
    AVG(pnl) as avg_pnl,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
FROM trades
WHERE status = 'CLOSED' AND rank IS NOT NULL
GROUP BY rank
ORDER BY rank;
```
