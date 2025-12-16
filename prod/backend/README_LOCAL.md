Local development setup (Postgres + DuckDB + Parquet)

1) Start local Postgres via Docker Compose (root of repo):

    docker-compose up -d

2) Verify Postgres: psql -h localhost -U orb -d orb

3) Update .env to set DATABASE_URL if needed (default points to local Postgres):

    DATABASE_URL=postgresql+psycopg2://orb:orb@localhost:5432/orb

4) Install dependencies for local dev (backend):

    pip install -r prod/backend/requirements.txt

5) Create necessary local directories:

    mkdir -p data/processed/1min
    mkdir -p data/deltas/1min

6) Merge deltas for all symbols (runs `sync_parquet.py` which calls `scripts/eod_merge` for each delta directory):

    python prod/backend/scripts/sync_parquet.py --interval 1min --verify

7) Run EOD merge example manually if you only want to merge a single symbol/day:

    python prod/backend/scripts/eod_merge.py --symbol AAPL --date 2025-12-05 --interval 1min

Notes:
- By default the app uses DuckDB for historical queries (local file `./data/duckdb_local.db`).
- This setup is local-only; no Neon or cloud storage is required.

---

## TradeZero (local execution)

This repo includes a Selenium-based TradeZero executor under `prod/backend/execution/tradezero/`.

### Install TradeZero deps

From repo root:

    pip install -r prod/backend/execution/tradezero/requirements.txt

### Configure `.env`

Minimum variables:

    EXECUTION_BROKER=tradezero
    ORB_UNIVERSE=micro_small
    ORB_STRATEGY=top5_both

    TRADEZERO_USERNAME=...
    TRADEZERO_PASSWORD=...
    TRADEZERO_HEADLESS=false

Safety defaults (recommended):

    TRADEZERO_DRY_RUN=true
    TRADEZERO_LOCATE_MAX_PPS=0.05
    TRADEZERO_DEFAULT_EQUITY=100000

### Run flow (dry-run first)

1) Run scanner (9:35 ET):

    POST /api/scanner/run

2) Generate signals (Top 5, BOTH):

    POST /api/signals/generate

3) Execute pending signals (TradeZero executor):

    POST /api/signals/execute

Alternative (single command, manual run):

    cd prod/backend
    python scripts/ORB/run_live_tradezero_once.py

When you are happy with behaviour, set `TRADEZERO_DRY_RUN=false` to place real orders.
