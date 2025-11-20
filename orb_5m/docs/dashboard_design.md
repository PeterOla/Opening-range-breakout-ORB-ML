# ORB Strategy Dashboard — Professional Design Plan

## Executive Summary

A professional trading analytics dashboard to visualize:
1. **Top N Daily Selection** — Which stocks made the cut each day by RVOL ranking
2. **Trade Execution Details** — Entry/exit points, P&L, and timing
3. **TradingView Integration** — Interactive price charts with annotated trades

**Tech Stack:**
- Backend: Python (FastAPI for API, pandas for data)
- Frontend: React + TradingView Lightweight Charts
- Alternative: Streamlit for rapid prototyping

---

## Design Philosophy

### Core Principles
1. **Data First** — Show actionable insights, not decorative metrics
2. **Speed** — Load times < 2s for daily view, < 5s for multi-year analysis
3. **Clarity** — Every chart tells one story; avoid cognitive overload
4. **Reproducibility** — Any view can be exported (CSV, PNG, or shareable URL)

### User Personas
- **You (Trader)** — Daily review: "Which stocks traded today? How did they perform?"
- **You (Analyst)** — Monthly review: "Which setups work best? RVOL patterns?"
- **You (Developer)** — Debugging: "Did the algo correctly rank and enter AAPL on 2024-03-15?"

---

## Dashboard Structure

### 1. Daily Overview Page
**Purpose:** Quick snapshot of today's (or selected date's) trading activity

#### Layout (3-column grid)
```
┌─────────────────────────────────────────────────────────────────┐
│  Header: Date Selector | Filters | Export                       │
├─────────────────┬───────────────────────┬───────────────────────┤
│  Top N Ranked   │  Trade Execution Log  │  Key Metrics          │
│  (List)         │  (Table)              │  (Cards)              │
│                 │                       │                       │
│  [Symbol cards] │  Symbol | Entry | P&L │  • Total P&L         │
│  showing RVOL,  │  Time | Exit | R     │  • Win Rate          │
│  OR details     │  [Quick chart icon]   │  • Avg RVOL          │
│                 │                       │  • Positions Taken   │
└─────────────────┴───────────────────────┴───────────────────────┘
```

#### Top N Ranked (Left Panel)
- **Format:** Card-based list (ranked 1–20)
- **Each card shows:**
  - Rank badge (1st = gold, 2–5 = silver, 6–20 = gray)
  - Symbol + Name
  - RVOL value (color-coded: >5 red, 2–5 orange, 1–2 green)
  - Opening Range: High/Low (with spread %)
  - Direction indicator: ↑ Long Setup / ↓ Short Setup / ⊗ Doji (skipped)
  - Status badge: "Traded" (green) / "Skipped" (yellow) / "Stopped Out" (red)
  
- **Interactions:**
  - Click card → open detail view with TradingView chart
  - Hover → tooltip with 14D avg OR volume vs today
  
- **Sort/Filter:**
  - Toggle: Show "All Ranked" vs "Traded Only"
  - Filter by direction (Long/Short/All)
  - Filter by outcome (Winners/Losers/All)

#### Trade Execution Log (Center Panel)
- **Format:** Sortable table
- **Columns:**
  1. Symbol (clickable → chart)
  2. Entry Time (HH:MM ET)
  3. Entry Price
  4. Stop Price (with % distance)
  5. Exit Time
  6. Exit Price
  7. Exit Reason (icon: 🛑 Stop / 🕐 EOD / 🎯 Target if added)
  8. P&L ($)
  9. P&L (R-multiples)
  10. Commission ($)
  11. Duration (minutes held)
  
- **Conditional Formatting:**
  - P&L > 0: green row background (light)
  - P&L < 0: red row background (light)
  - Exit Reason icons for quick scanning
  
- **Actions:**
  - Click symbol → open chart modal
  - Export selected rows to CSV
  - "Replay Trade" button → shows minute-by-minute price action

#### Key Metrics (Right Panel)
- **Daily Summary Cards:**
  1. **Total P&L** — $ and % of starting equity
  2. **Win Rate** — X/Y trades (Z%)
  3. **Avg RVOL** — Mean of top 20 ranked
  4. **Positions Taken** — X of 20 possible (leverage usage)
  5. **Best Trade** — Symbol + R
  6. **Worst Trade** — Symbol + R
  
- **Micro-charts (sparklines):**
  - Intraday equity curve (cumulative P&L)
  - RVOL distribution histogram (0–20 ranked stocks)

---

### 2. TradingView Chart Integration

#### Chart Modal (Full-screen overlay)
**Trigger:** Click any symbol from ranked list or trade log

**Layout:**
```
┌─────────────────────────────────────────────────────────────────┐
│  [Symbol] — [Date] — Direction: [Long/Short]         [Close ×]  │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│                   TradingView Chart Canvas                        │
│                   (5-min or 1-min bars)                          │
│                                                                   │
│   Annotations:                                                    │
│   • Opening Range box (9:30–9:35) shaded yellow                 │
│   • Entry line (green arrow up / red arrow down)                │
│   • Stop line (dashed red)                                      │
│   • Exit marker (circle: green win / red loss)                  │
│   • ATR band (semi-transparent blue)                            │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  Trade Stats Overlay (bottom-right):                             │
│  Entry: $X.XX @ HH:MM  |  Stop: $Y.YY  |  Exit: $Z.ZZ @ HH:MM  │
│  P&L: $XXX (+X.XX%)   |  R: +X.XR     |  Duration: XX min       │
└─────────────────────────────────────────────────────────────────┘
```

#### Chart Features
1. **Time Range:** Pre-market (9:00) to close (16:00) for context
2. **Candlestick Style:** 5-min bars (default) or 1-min (toggle)
3. **Volume Subplot:** Below price chart (highlight OR bar in yellow)
4. **Annotations:**
   - **Opening Range Box:** Vertical yellow zone 9:30–9:35 + horizontal lines at OR high/low
   - **Entry Point:** Arrow marker (↑ green for long, ↓ red for short) at entry price + time
   - **Stop Level:** Dashed red horizontal line
   - **Exit Point:** Circle marker (🟢 profit / 🔴 loss) at exit price + time
   - **ATR Band:** Semi-transparent blue zone = entry ± 0.1×ATR (stop distance visualization)
   
5. **Interactivity:**
   - Crosshair tooltip shows OHLCV + time for any bar
   - Zoom/pan enabled
   - "Export Chart" → PNG download
   - "View on TradingView.com" → opens external link with symbol (if public API available)

#### Technical Implementation
**Option A: TradingView Lightweight Charts (Recommended)**
- Library: https://github.com/tradingview/lightweight-charts
- Pros: Free, fast rendering, React-friendly, <200KB bundle
- Cons: Limited to basic shapes (use custom plugins for annotations)
- Code snippet:
  ```typescript
  import { createChart } from 'lightweight-charts';
  
  const chart = createChart(container, { width: 800, height: 600 });
  const candlestickSeries = chart.addCandlestickSeries();
  candlestickSeries.setData(priceData); // [{time, open, high, low, close}]
  
  // Add markers
  candlestickSeries.setMarkers([
    { time: entryTime, position: 'belowBar', color: 'green', shape: 'arrowUp', text: 'Entry' },
    { time: exitTime, position: 'aboveBar', color: 'red', shape: 'circle', text: 'Exit' }
  ]);
  
  // Add price lines
  const stopLine = candlestickSeries.createPriceLine({
    price: stopPrice,
    color: 'red',
    lineStyle: 2, // dashed
    lineWidth: 2,
    title: 'Stop'
  });
  ```

**Option B: Plotly (Python/Streamlit)**
- Library: `plotly.graph_objects.Candlestick`
- Pros: Python-native, easy server-side rendering
- Cons: Heavier bundle, less interactive than TradingView
- Use for: Quick prototyping in Streamlit

---

### 3. Multi-Day Analysis Page
**Purpose:** Compare performance across multiple days or months

#### Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  Date Range Selector: [2024-01-01] to [2024-12-31]   [Apply]   │
├─────────────────────────────────────────────────────────────────┤
│  Equity Curve (Top Half — Full Width)                           │
│  [Line chart: cumulative P&L over time, with drawdown shading]  │
├───────────────────────┬─────────────────────────────────────────┤
│  Daily P&L Heatmap    │  RVOL Bucket Analysis                   │
│  (Calendar grid)      │  (Bar chart: Avg R by RVOL range)      │
├───────────────────────┼─────────────────────────────────────────┤
│  Top Performers       │  Trade Distribution                     │
│  (Symbols leaderboard)│  (Histogram: P&L in $ bins)            │
└───────────────────────┴─────────────────────────────────────────┘
```

#### Components

**Equity Curve:**
- X-axis: Dates
- Y-axis: Cumulative P&L ($) or % of starting equity
- Shaded area: Drawdown periods (red fill below previous peak)
- Benchmark overlay (optional): SPY returns for comparison
- Hover: Show daily P&L + # trades + win rate

**Daily P&L Heatmap:**
- Grid: Rows = weeks, Columns = weekdays (Mon–Fri)
- Color scale: Green (profit) → White (breakeven) → Red (loss)
- Cell tooltip: Date, P&L, # trades
- Click cell → filter Daily Overview to that date

**RVOL Bucket Analysis:**
- X-axis: RVOL ranges (1–1.5, 1.5–2, 2–3, 3–5, >5)
- Y-axis: Average R-multiple per trade
- Bar color: Green if avg R > 0, red otherwise
- Shows: "Do higher RVOL setups actually perform better?"

**Top Performers Table:**
- Columns: Symbol | Total Trades | Win Rate | Cumulative R | Total P&L
- Sort by: Cumulative R (default) or Total P&L
- Click symbol → show all trades for that symbol

**Trade Distribution Histogram:**
- X-axis: P&L bins (-$2k, -$1k, $0, +$1k, +$2k, etc.)
- Y-axis: # of trades
- Normal distribution overlay (theoretical)
- Shows: Skew and fat-tails (are wins bigger than losses?)

---

### 4. Symbol Deep-Dive Page
**Purpose:** Analyze all trades for a single symbol over time

#### Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  Symbol: [NVDA ▼]  |  Date Range: [2024-01-01] to [2024-12-31] │
├─────────────────────────────────────────────────────────────────┤
│  Symbol Stats Card:                                              │
│  • Times Ranked in Top 20: X days                               │
│  • Times Traded: Y trades                                       │
│  • Win Rate: Z%                                                 │
│  • Avg RVOL when ranked: X.XX                                   │
│  • Best Trade: +X.XR on [Date]                                  │
│  • Worst Trade: -X.XR on [Date]                                 │
├─────────────────────────────────────────────────────────────────┤
│  Trade Timeline (Scatter Plot)                                   │
│  X-axis: Date  |  Y-axis: P&L (R)  |  Marker size: RVOL        │
├─────────────────────────────────────────────────────────────────┤
│  All Trades Table (Sortable)                                     │
│  [Date | RVOL | Entry | Exit | P&L | R | Chart]                │
└─────────────────────────────────────────────────────────────────┘
```

**Insights to surface:**
- Does this symbol have consistent setups? (cluster in RVOL ranges)
- Are there patterns in losses? (time of day, RVOL extremes)
- Click any trade → open TradingView chart modal

---

## Data Pipeline (Backend)

### API Endpoints (FastAPI)

#### 1. GET `/api/daily-overview?date=YYYY-MM-DD`
**Response:**
```json
{
  "date": "2024-03-15",
  "top_n_ranked": [
    {
      "rank": 1,
      "symbol": "NVDA",
      "rvol": 5.23,
      "or_high": 875.50,
      "or_low": 872.10,
      "direction": "long",
      "traded": true,
      "outcome": "win"
    },
    ...
  ],
  "trades": [
    {
      "symbol": "NVDA",
      "entry_time": "2024-03-15T09:42:00-04:00",
      "entry_price": 876.20,
      "stop_price": 870.15,
      "exit_time": "2024-03-15T15:58:00-04:00",
      "exit_price": 882.50,
      "exit_reason": "eod",
      "pnl_dollars": 1250.80,
      "pnl_r": 1.04,
      "commission": 7.00,
      "duration_minutes": 376
    },
    ...
  ],
  "metrics": {
    "total_pnl": 5432.10,
    "win_rate": 0.55,
    "avg_rvol": 2.87,
    "positions_taken": 18
  }
}
```

#### 2. GET `/api/chart-data?symbol=NVDA&date=YYYY-MM-DD&resolution=5`
**Response:**
```json
{
  "symbol": "NVDA",
  "date": "2024-03-15",
  "resolution": "5min",
  "bars": [
    {"time": "2024-03-15T09:30:00-04:00", "open": 872.10, "high": 875.50, "low": 871.90, "close": 874.20, "volume": 2500000},
    ...
  ],
  "annotations": {
    "or_box": {"start": "09:30", "end": "09:35", "high": 875.50, "low": 872.10},
    "entry": {"time": "09:42", "price": 876.20, "direction": "long"},
    "stop": {"price": 870.15},
    "exit": {"time": "15:58", "price": 882.50, "reason": "eod"}
  },
  "atr": 8.50
}
```

#### 3. GET `/api/multi-day-stats?start=YYYY-MM-DD&end=YYYY-MM-DD`
**Response:**
```json
{
  "equity_curve": [
    {"date": "2024-01-02", "cumulative_pnl": 1200.50, "daily_pnl": 1200.50},
    ...
  ],
  "rvol_buckets": [
    {"range": "1.0-1.5", "avg_r": 0.25, "count": 120},
    {"range": "1.5-2.0", "avg_r": 0.42, "count": 85},
    ...
  ],
  "top_performers": [
    {"symbol": "NVDA", "trades": 45, "win_rate": 0.62, "cumulative_r": 15.8, "total_pnl": 25400.00},
    ...
  ]
}
```

### Data Storage
- **Source:** Existing CSV files (`portfolio_trades.csv`, `portfolio_daily_pnl.csv`)
- **Processing:**
  - On dashboard load, read CSVs into pandas DataFrames
  - Cache in memory (Redis for production, simple dict for dev)
  - Refresh on user action or schedule (e.g., daily at market close)
  
- **Optimization:**
  - Pre-compute aggregations (daily metrics, RVOL buckets) and save to `processed/` folder
  - Use Parquet for faster read times (10–50× faster than CSV for large datasets)

---

## Frontend Implementation

### Option A: React + TradingView Lightweight Charts (Production-Ready)

**Tech Stack:**
- Framework: React 18 + TypeScript
- Charting: TradingView Lightweight Charts
- UI: Tailwind CSS + shadcn/ui components
- State: React Query (data fetching) + Zustand (global state)
- Build: Vite

**File Structure:**
```
frontend/
  src/
    components/
      DailyOverview/
        TopNRanked.tsx       # Card list
        TradeLog.tsx         # Table component
        MetricsCards.tsx     # Summary cards
      Charts/
        TVChart.tsx          # TradingView wrapper
        ChartModal.tsx       # Full-screen modal
      MultiDay/
        EquityCurve.tsx      # Line chart
        RVOLBuckets.tsx      # Bar chart
        Heatmap.tsx          # Calendar heatmap
    pages/
      DailyOverviewPage.tsx
      MultiDayPage.tsx
      SymbolDeepDivePage.tsx
    api/
      client.ts            # Fetch from FastAPI backend
    types/
      trade.types.ts       # TypeScript interfaces
```

**Key Dependencies:**
```json
{
  "dependencies": {
    "react": "^18.2.0",
    "lightweight-charts": "^4.1.0",
    "@tanstack/react-query": "^5.0.0",
    "zustand": "^4.5.0",
    "tailwindcss": "^3.4.0",
    "date-fns": "^3.0.0",
    "recharts": "^2.10.0"
  }
}
```

---

### Option B: Streamlit (Rapid Prototyping)

**Pros:** 
- Pure Python, no frontend code
- Built-in widgets (date pickers, tables, charts)
- Deploy in minutes

**Cons:**
- Less polished UI
- TradingView integration limited (use Plotly instead)
- Single-user session management (not ideal for multi-user)

**File Structure:**
```
streamlit_app/
  app.py                    # Main entry point
  pages/
    1_Daily_Overview.py
    2_Multi_Day.py
    3_Symbol_Deep_Dive.py
  components/
    tv_chart.py             # Plotly candlestick wrapper
    metrics_cards.py
  data/
    loader.py               # Read CSVs, cache with @st.cache_data
```

**Sample Code (Daily Overview):**
```python
import streamlit as st
import pandas as pd
from datetime import date

st.set_page_config(page_title="ORB Dashboard", layout="wide")

# Date selector
selected_date = st.date_input("Select Date", value=date.today())

# Load data
trades = pd.read_csv(f"results_active_{selected_date.year}_top20/portfolio_trades.csv")
trades['date'] = pd.to_datetime(trades['date']).dt.date
day_trades = trades[trades['date'] == selected_date]

# Layout
col1, col2, col3 = st.columns([1, 2, 1])

with col1:
    st.subheader("Top 20 Ranked")
    # Show ranked list (parse from daily selection logic)
    
with col2:
    st.subheader("Trades Executed")
    st.dataframe(day_trades[['symbol', 'entry_time', 'exit_time', 'net_pnl']])
    
with col3:
    st.subheader("Metrics")
    st.metric("Total P&L", f"${day_trades['net_pnl'].sum():,.2f}")
    st.metric("Win Rate", f"{(day_trades['net_pnl'] > 0).mean():.1%}")
```

---

## Implementation Roadmap

### Phase 1: MVP (1–2 days)
- [ ] Backend: FastAPI server with 3 endpoints (daily overview, chart data, multi-day stats)
- [ ] Frontend: Streamlit app with Daily Overview page (table + basic metrics)
- [ ] Chart: Plotly candlestick with entry/exit markers (no TradingView yet)
- [ ] Data: Read from existing CSV files, no database

**Goal:** Functional dashboard to review yesterday's trades

### Phase 2: TradingView Integration (1 day)
- [ ] Replace Plotly with TradingView Lightweight Charts
- [ ] Add annotations: OR box, entry/exit markers, stop line
- [ ] Modal for full-screen chart view
- [ ] Export chart as PNG

**Goal:** Professional-looking charts matching broker platforms

### Phase 3: Multi-Day Analysis (1 day)
- [ ] Equity curve with drawdown shading
- [ ] RVOL bucket analysis (bar chart)
- [ ] Daily P&L heatmap (calendar view)
- [ ] Top performers leaderboard

**Goal:** Identify patterns across weeks/months

### Phase 4: Polish + Deploy (1 day)
- [ ] Responsive design (mobile-friendly)
- [ ] Loading states and error handling
- [ ] Export to CSV/PNG buttons
- [ ] Deploy to cloud (Streamlit Cloud free tier or Railway for FastAPI)

**Goal:** Shareable link, accessible from any device

---

## Design Assets

### Color Palette (Professional Trading Theme)
- **Background:** `#0a0e27` (dark navy)
- **Cards:** `#1a1f3a` (lighter navy)
- **Text Primary:** `#e0e6ed` (light gray)
- **Text Secondary:** `#8b93a7` (muted gray)
- **Accent (Profit):** `#26a69a` (teal green)
- **Accent (Loss):** `#ef5350` (red)
- **Accent (Neutral):** `#ffa726` (amber)
- **Borders:** `#2d3447` (subtle gray)

### Typography
- **Headings:** Inter Bold (16–24px)
- **Body:** Inter Regular (14px)
- **Monospace (prices, P&L):** JetBrains Mono (14px)

### Icons
- Use Heroicons or Lucide React (open-source, consistent style)
- Examples:
  - 📈 Trend Up (long setups)
  - 📉 Trend Down (short setups)
  - 🛑 Stop Circle (stopped out)
  - 🕐 Clock (EOD exit)

---

## Example Screenshots (Mockups)

### Daily Overview
```
╔═══════════════════════════════════════════════════════════════════╗
║  ORB Dashboard — March 15, 2024               [Export] [Settings] ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                     ║
║  ┌─────────────────┐  ┌────────────────────────┐  ┌────────────┐ ║
║  │ 🥇 #1 NVDA      │  │ NVDA | 09:42 | +$1.2K │  │ Total P&L  │ ║
║  │ RVOL: 5.23 🔥   │  │ Entry: $876.20         │  │ +$5,432    │ ║
║  │ OR: 872–875     │  │ Exit:  $882.50 (EOD)   │  └────────────┘ ║
║  │ Direction: ↑    │  │ [📊 Chart]             │                 ║
║  │ ✅ Traded       │  ├────────────────────────┤  ┌────────────┐ ║
║  └─────────────────┘  │ TSLA | 09:38 | -$420  │  │ Win Rate   │ ║
║                       │ Entry: $185.30         │  │ 55% (11/20)│ ║
║  ┌─────────────────┐  │ Exit:  $183.10 (STOP) │  └────────────┘ ║
║  │ 🥈 #2 TSLA      │  │ [📊 Chart]             │                 ║
║  │ RVOL: 3.87      │  └────────────────────────┘                 ║
║  │ ...             │                                              ║
╚═══════════════════════════════════════════════════════════════════╝
```

### TradingView Chart Modal
```
╔═══════════════════════════════════════════════════════════════════╗
║  NVDA — March 15, 2024 — Long Setup                      [Close ×]║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                     ║
║      $890 ┤                                                        ║
║           │                    ╱╲                                  ║
║      $880 ┤                   ╱  ╲        ● Exit ($882.50)        ║
║           │      ┌──────┐    ╱    ╲      ╱                        ║
║      $870 ┤━━━━━━┥ OR   ┝━━━━━━━━━━━━━━━  ← Stop ($870.15)       ║
║           │      │ 9:30 │  ↑ Entry ($876.20)                      ║
║      $860 ┤      └──────┘                                          ║
║           │                                                         ║
║           └─────────────────────────────────────────               ║
║            09:00   10:00   11:00   12:00   13:00   14:00   16:00  ║
║                                                                     ║
║  📊 Entry: $876.20 @ 09:42  |  Stop: $870.15  |  Exit: $882.50    ║
║  💰 P&L: +$1,250 (+0.71%)   |  R: +1.04       |  Duration: 376min ║
╚═══════════════════════════════════════════════════════════════════╝
```

---

## Next Steps

1. **Choose your path:**
   - **Fast (Streamlit):** Start with `streamlit_app/app.py`, iterate daily
   - **Production (React):** Set up FastAPI + React scaffold, takes longer but scales better

2. **Immediate tasks:**
   - [ ] Create `src/api/` folder with FastAPI endpoints
   - [ ] Write data loader: `load_daily_overview(date)` function
   - [ ] Build first page: Daily Overview (table only, no charts)
   - [ ] Test with 1–2 recent trading dates

3. **Decision point (after MVP):**
   - If Streamlit feels limiting → migrate to React + TradingView
   - If Streamlit works → add more pages, stay in Python

---

## Resources

### Libraries
- **TradingView Lightweight Charts:** https://tradingview.github.io/lightweight-charts/
- **FastAPI:** https://fastapi.tiangolo.com/
- **Streamlit:** https://streamlit.io/
- **shadcn/ui (React components):** https://ui.shadcn.com/
- **Recharts (React charts):** https://recharts.org/

### Inspiration
- **TradingView Desktop:** Study their trade marker placement, color schemes
- **Interactive Brokers TWS:** Professional trader UI patterns
- **TradingView Pine Script Editor:** Chart annotation system

### Learning
- **TradingView Lightweight Charts Tutorial:** https://tradingview.github.io/lightweight-charts/tutorials/
- **FastAPI + React Integration:** https://testdriven.io/blog/fastapi-react/

---

## Metrics to Track (Meta)
- Dashboard load time (target: <2s)
- Time to insights (how fast can you answer "Why did X lose money?")
- Export usage (are you actually using CSV/PNG exports?)
- Most-viewed charts (which symbols/dates are you reviewing repeatedly?)

This tells you if the dashboard is **useful** vs just **pretty**.
