# TradeZero Trading Roadmap (Prerequisite: Shares Outstanding)

## Goal
Start executing the ORB strategy on TradeZero with automation, while keeping the system realistic (liquidity + HTB constraints) and the universe classification correct (shares outstanding).

## Non‑Negotiable Prerequisite
**Shares outstanding must be sourced reliably and for free**, because:
- Universe buckets (Micro/Small/Large) depend on it.
- Backtests and live decisions must match the same classification logic.

## Milestones (in order)

## Progress Tracking

### Checklist (tick as we go)
- [ ] ~~Milestone 1 — Shares outstanding (SEC XBRL) working end-to-end~~ (skipped for now)
  - [ ] ~~Audit existing shares sourcing + usage~~
  - [ ] ~~Implement ticker→CIK + Company Facts fetch~~
  - [ ] ~~Extract `EntityCommonStockSharesOutstanding` into a normalised table~~
  - [ ] ~~Cache raw responses + derived shares table locally~~
  - [ ] ~~Implement as-of-date lookup (closest on/before trade date)~~
  - [ ] ~~Coverage reporting (known vs unknown) per day~~

- [ ] Milestone 2 — Backtests + reporting (current focus)
  - [ ] ~~Universe build joins shares as-of date~~
  - [ ] Add Volume/Gap Filter (e.g., Gap > 2%)

  - [ ] ~~Backtester reads `shares_outstanding` from universe outputs~~
  - [ ] ~~Post-run report includes PnL attribution for Unknown shares~~
  - [ ] Overwrite baseline ORB backtests
    - [ ] Baseline matrix (Top 20)
      - [x] Micro — BOTH
      - [x] Micro — LONG
      - [x] Small — BOTH
      - [x] Small — LONG
      - [x] Large — BOTH
      - [x] Large — LONG
      - [x] Micro + Small — BOTH
      - [x] Micro + Small — LONG
      - [x] Micro + Small + Unknown — BOTH
      - [x] Micro + Small + Unknown — LONG
      - [x] Micro + Unknown — BOTH
      - [x] Micro + Unknown — LONG
      - [x] Unknown — BOTH
      - [x] Unknown — LONG
      - [x] All — BOTH
    - [x] Select best 5 baseline combinations (define ranking rule)
      - Rule: rank by Profit Factor (PF) across baseline runs (all have 10k+ entered trades)
      - Top 5 (by PF):
        - compound_micro_liquidity_1pct_atr050_both
        - compound_micro_small_unknown_liquidity_1pct_atr050_both
        - compound_micro_small_liquidity_1pct_atr050_both
        - compound_micro_unknown_liquidity_1pct_atr050_both
        - compound_all_liquidity_1pct_atr050_both
    - [x] Rerun best 5 with Top 10
      - Runs:
        - compound_micro_liquidity_1pct_atr050_top10_both
        - compound_micro_small_unknown_liquidity_1pct_atr050_top10_both
        - compound_micro_small_liquidity_1pct_atr050_top10_both
        - compound_micro_unknown_liquidity_1pct_atr050_top10_both
        - compound_all_liquidity_1pct_atr050_top10_both
    - [x] Rerun best 5 with Top 5
      - Runs:
        - compound_micro_liquidity_1pct_atr050_top5_both
        - compound_micro_small_unknown_liquidity_1pct_atr050_top5_both
        - compound_micro_small_liquidity_1pct_atr050_top5_both
        - compound_micro_unknown_liquidity_1pct_atr050_top5_both
        - compound_all_liquidity_1pct_atr050_top5_both
      - LONG-only reruns (Top 5):
        - compound_micro_liquidity_1pct_atr050_top5_long
        - compound_micro_small_unknown_liquidity_1pct_atr050_top5_long
        - compound_micro_small_liquidity_1pct_atr050_top5_long
        - compound_micro_unknown_liquidity_1pct_atr050_top5_long
        - compound_all_liquidity_1pct_atr050_top5_long
    - [x] Regenerate comparison reports + per-run `summary.md`
      - Updated: data/backtest/orb/reports/comparison_summary.md

- [ ] Milestone 3 — TradeZero execution layer stable
  - [ ] Broker interface contract defined (methods + behaviour)
  - [ ] Locate workflow with max-fee safety guard
  - [ ] Place/cancel orders + reconciliation (active orders / positions)
  - [ ] Selenium hardening (waits, retries, screenshots on failure)
  - [ ] Kill switch + risk limits wired in

- [ ] Milestone 4 — Daily trading loop automated
  - [ ] Scanner → watchlist → executor wiring
  - [ ] Pre-flight checks (session, BP, locate fees, shares coverage)
  - [ ] Execution logs + end-of-day report produced in one run

### Alternatives (if you prefer stronger tracking than markdown)
- Option 1: GitHub Issues (one issue per checkbox group) + labels (`shares`, `execution`, `ops`)
- Option 2: GitHub Projects (Kanban: Backlog → In Progress → Blocked → Done)
- Option 3: A single `TASKS.md` with dates/owners (useful if working offline)

### Milestone 0 — Definition of Done (DoD)
- One canonical dataset for shares outstanding exists locally (cached, versioned, reproducible).
- Universe builder can query shares outstanding **as-of a trade date**.
- Strategy runner can place orders via TradeZero with safety checks.

---

### Milestone 1 — Shares Outstanding: Replace Alpha Vantage (Free)
**Target outcome:** A dependable, free shares-outstanding pipeline with caching.

**Approach (recommended): SEC XBRL “Company Facts”**
- Source: SEC `companyfacts` endpoint (free; requires User-Agent).
- Field: `EntityCommonStockSharesOutstanding`.
- Key requirement: choose the value **closest on/before** the trade date.

**Tasks**
- Audit the current shares pipeline and where it feeds classification.
- Implement:
  - ticker → CIK mapping (SEC provides a JSON mapping file).
  - CIK → company facts fetcher.
  - extraction + normalisation into a standard record:
    - `ticker`, `cik`, `as_of_date`, `shares_outstanding`, `source`, `fetched_at`.
  - caching:
    - raw JSON responses cached to disk.
    - derived shares table cached to parquet/duckdb.
  - rate limiting + retries.

**Acceptance criteria**
- For a sample set (AAPL + 10 microcaps), fetch succeeds for the majority and failures are logged.
- For each ticker/date, `shares_outstanding_asof(trade_date)` is deterministic.
- Universe classification reports % coverage (known vs unknown) per day.

**Risks / sceptic notes**
- SEC facts are reported on filing dates; you must treat as “last known on/before date”, not “true daily float”.
- Some tickers (recent IPOs, OTC, foreign listings) may have gaps.

---

### Milestone 2 — Universe + Backtest Integration
**Target outcome:** Shares outstanding is the default input to universe creation and backtest outputs.

**Tasks**
- Update universe build scripts to join shares outstanding as-of trade date.
- Ensure the backtester uses the universe file’s shares column, not ad-hoc fetches.
- Emit artefacts:
  - `data/backtest/universe_*.parquet` includes `shares_outstanding` and `shares_source`.
  - `data/processed/shares_outstanding.parquet` (or similar canonical cache).

**Acceptance criteria**
- “Unknown shares” contribution to PnL can be computed automatically after each run.
- The “All universe” run reports coverage and does not silently default to unknown.

---

### Milestone 3 — TradeZero Automation (Execution Layer)
**Target outcome:** A stable local executor that can place/cancel orders and handle HTB locates.

**Key design decision**
TradeZero automation is Selenium-based (web UI). That means:
- It’s brittle to DOM changes.
- It needs defensive engineering: waits, retries, screenshots, and idempotent actions.

**Tasks**
- Define a broker interface contract:
  - `connect()`, `heartbeat()`, `get_quote()`, `locate()`, `place_order()`, `cancel_order()`, `positions()`, `active_orders()`.
- Implement safety rails:
  - max locate fee per share and total.
  - max position size.
  - time windows (locate availability).
  - kill-switch.
- Implement order primitives needed by ORB:
  - entry (limit/market)
  - exits: if TradeZero cannot reliably place bracket orders, emulate with monitoring loop.

**Acceptance criteria**
- A scripted dry-run can:
  - login,
  - load symbol,
  - fetch bid/ask,
  - request a locate (decline if over limit),
  - place a limit order,
  - read active orders,
  - cancel order.

---

### Milestone 4 — End-to-End Daily Trading Loop
**Target outcome:** From scanner → watchlist → execution → logs.

**Tasks**
- Connect your signal generator to the executor.
- Add a daily “pre-flight” check:
  - market open,
  - session valid,
  - cash/BP,
  - watchlist non-empty,
  - shares coverage above threshold (e.g., >90% for today’s universe).
- Standardise logs:
  - signals, orders, fills, errors, screenshots.

**Acceptance criteria**
- One command produces:
  - watchlist for the day,
  - planned orders,
  - execution log,
  - end-of-day report.

---

## Free Shares Outstanding: Options (ranked)

### Option A (Recommended): SEC XBRL Company Facts
- Free and official.
- Best for US-listed equities.
- “As-of filing date” reality: use last known on/before date.

### Option B: SEC Filings (10-Q/10-K) HTML scrape
- Also free, but more fragile and slower.
- Useful fallback when company facts don’t expose what we need.

### Option C: Stooq / other free endpoints
- Often incomplete for microcaps.
- Usually not reliable enough for classification-critical data.

**Recommendation:** Build Option A first with caching, then optionally add B as a fallback.

---

## Operational Checklist (Go-Live)
- Credentials stored in `.env` (never hard-coded).
- Single “kill switch” flag (file-based or env var).
- Max daily loss / max trades / max locate spend.
- Screenshot on every failure state.
- Manual playbook: what to do when locates fail, DOM changes, or session expires.

---

## Immediate Next Step
Start with Milestone 1: implement SEC shares outstanding fetch + cache and wire it into universe generation.
