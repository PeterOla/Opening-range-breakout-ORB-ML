# DataPipeline - ORB Data Fetch & Enrichment

Unified data pipeline for fetching, enriching, and validating market data from Alpaca to parquet files.

**Single command**: `daily_sync.py` orchestrates the entire pipeline → fetch → enrich → validate.

### ⚠️ CRITICAL: Environment Setup Required

Before running the pipeline, ensure:

1. **`.env` file exists** in `prod/backend/.env` with:
   - `ALPACA_API_KEY=...`
   - `ALPACA_API_SECRET=...` (not ALPACA_SECRET_KEY)

2. **Config loads `.env` automatically** via `load_dotenv()` in `config.py`

3. **Data format expectations** (see Data Format Specification section):
   - Daily data: `datetime64[ns]` (naive UTC, no timezone)
   - 5-min data: `datetime64[ns, America/New_York]` (timezone-aware)
   - **These are NOT interchangeable** — each has specific requirements

  4. **SEC User-Agent** (required for shares sync)
    - Set `SEC_USER_AGENT` in `prod/backend/.env` (or your environment)
    - Example: `SEC_USER_AGENT=ORBResearch/1.0 you@email.com`

## CLI Reference

### Command Syntax
```bash
python -m DataPipeline.daily_sync [OPTIONS]
```

### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--symbols` | List[str] | All symbols | Specific symbols to sync (e.g., `AAPL MSFT TSLA`). If omitted, syncs all symbols in `data/processed/daily/` |
| `--skip-fetch` | Flag | False | Skip Alpaca fetch step (use pre-existing data) |
| `--skip-enrich` | Flag | False | Skip enrichment step (add metrics + shares) |
| `--log-level` | Choice | INFO | Logging verbosity: DEBUG, INFO, WARNING, ERROR |
| `-h, --help` | Flag | - | Show help message and exit |

### Examples

**Full sync (all symbols, all steps)**:
```bash
python -m DataPipeline.daily_sync
```
Time: 45-90 minutes

**Test mode (single symbol, all steps)**:
```bash
python -m DataPipeline.daily_sync --symbols A
```
Time: ~5 minutes

**Test mode (multiple symbols)**:
```bash
python -m DataPipeline.daily_sync --symbols AAPL MSFT TSLA
```
Time: ~10 minutes

**Fetch only (skip enrichment and validation)**:
```bash
python -m DataPipeline.daily_sync --symbols A --skip-enrich
```
Time: ~2 minutes (fetch A from Alpaca)

**Enrich only (skip fetch and validation)**:
```bash
python -m DataPipeline.daily_sync --symbols A --skip-fetch
```
Time: ~1 minute (enrich existing A.parquet)

**Debug mode (verbose logging)**:
```bash
python -m DataPipeline.daily_sync --symbols A --log-level DEBUG
```
Outputs: Detailed execution trace to console + logs/

## Shares-Only Sync (Start Shares Fetch)

If you want to fetch shares outstanding **without** running the full Alpaca fetch/enrich pipeline:

```bash
python -m DataPipeline.run_shares_sync
```

For specific symbols:

```bash
python -m DataPipeline.run_shares_sync --symbols AAPL MSFT TSLA
```

## Missing Shares Ignore List — Instrument Breakdown

If you want to understand how many ignored symbols are likely **ETFs/ETNs/preferreds/units/warrants** (vs real operating companies), run:

```bash
python scripts/DataPipeline/analyse_missing_shares.py
```

Optional: probe SEC live for a small sample of ignored tickers to see which now return shares data:

```bash
python scripts/DataPipeline/analyse_missing_shares.py --probe 60
```

Outputs:
- `data/backtest/orb/reports/missing_shares_analysis.md`
- `data/backtest/orb/reports/assets/missing_shares_categories.png`
- `data/backtest/orb/reports/assets/probe_hits.csv`

### Output Files

After successful run, check:
- **Parquet files**: `data/processed/daily/{SYMBOL}.parquet` (updated with new dates)
- **Log files**: `logs/orb_sync_*.log` (human-readable) and `logs/orb_sync_*.json` (structured results)

## Pipeline Stages

### 1. **Fetch** (alpaca_fetch.py)
- Fetches daily + 5-minute bars from Alpaca (premium tier, no rate limits)
- Parallel: 5 concurrent requests
- **Smart resume**: Detects last date in existing parquet, fetches only new data
- **Deduplication**: Removes duplicate dates before appending
- **Schema validation**: Converts Timestamp → string date, adds symbol column

**Output**:
- `data/processed/daily/{SYMBOL}.parquet` (date, symbol, open, high, low, close, volume)
- `data/processed/5min/{SYMBOL}.parquet` (datetime, symbol, open, high, low, close, volume, trade_count, vwap)

### 2. **Enrich** (enrichment.py)
Computes metrics and adds required columns:

#### A. Shares Enrichment (SharesEnricher)
- Loads `data/raw/historical_shares.parquet` (from Alpha Vantage quarterly reports)
- Joins most recent shares report ≤ trade date
- Forward-fills up to 365 days if gaps exist
- Adds `shares_outstanding` column

#### B. Metrics Computation (MetricsComputer)
- **True Range**: TR = max(H-L, |H-PC|, |L-PC|)
- **ATR14**: 14-day simple moving average of TR
- **Avg Volume 14**: 14-day rolling average of volume

**Output**: Enhanced parquets with new columns (tr, atr_14, avg_volume_14)

### 3. **Validate** (validators.py)
Pre/post-write validation:
- ✓ Schema compliance (required columns, correct types)
- ✓ Date continuity (warn on missing trading days)
- ✓ No critical NaNs in essential columns
- ✓ File size bounds (1KB - 100MB)
- ✓ Numeric ranges (close > 0, volume ≥ 0)
- ✓ Data freshness (warn if >14 days stale)
- ✓ Completeness (warn if <1,200 rows per symbol)

**Output**: Validation report with errors/warnings

## Data Format Specification

**CRITICAL**: Daily and 5-minute data use different datetime formats. Alpaca returns timestamps that must be converted correctly.

### Daily Data Format
**File**: `data/processed/daily/{SYMBOL}.parquet`

| Column | Type | Format | Example | Notes |
|--------|------|--------|---------|-------|
| `date` | `datetime64[ns, UTC]` | **UTC timezone-aware** midnight (00:00:00+0000) | `2025-12-08 00:00:00+0000` | **ALWAYS timezone-aware.** Used for merges with shares data. |
| `open` | `float64` | Decimal | `118.94` | OHLC from Alpaca |
| `high` | `float64` | Decimal | `120.09` | |
| `low` | `float64` | Decimal | `118.70` | |
| `close` | `float64` | Decimal | `119.50` | |
| `volume` | `float64` | Integer | `1234567.0` | Daily volume in shares |
| `symbol` | `object` | String | `"A"` | Ticker symbol |
| `tr` | `float64` | Decimal | `1.39` | True Range (H-L, \|H-PC\|, \|L-PC\|) |
| `atr_14` | `float64` | Decimal | `0.87` | 14-day ATR, NaN for first 14 days |
| `shares_outstanding` | `int64` | Integer | `311000000` | From Alpha Vantage quarterly reports |

**Conversion from Alpaca**:
- Alpaca returns daily bars as `TimeFrame.Day` with timestamp `datetime64[ns, UTC]`
- Keep timezone-aware: `pd.to_datetime(bar.timestamp).dt.normalize()` preserves UTC
- Result: `datetime64[ns, UTC]` (timezone-aware UTC midnight)
- **Code**: `alpaca_fetch.py` line 126

**⚠️ CRITICAL BUG (FIXED)**:
- **Problem**: Calling `pd.to_datetime()` on already-datetime columns strips timezone
- **Impact**: Causes `datetime64[ns, UTC]` → `datetime64[ns]` (naive), breaking merges
- **Example**: A.parquet was `datetime64[ns, UTC]` but AAPL/MSFT were naive `datetime64[ns]`
- **Root Cause**: Line 201 in old code: `df_combined['date'] = pd.to_datetime(df_combined['date'])`
- **Fix** (lines 201-208): Check dtype first, only convert if string/object, otherwise add timezone if missing

### 5-Minute Data Format
**File**: `data/processed/5min/{SYMBOL}.parquet`

| Column | Type | Format | Example | Notes |
|--------|------|--------|---------|-------|
| `timestamp` | `datetime64[ns, America/New_York]` | **Timezone-aware** EST/EDT | `2021-01-04 09:30:00-05:00` | **Intraday bars are timezone-aware.** Includes market hours timezone. |
| `open` | `float64` | Decimal | `118.94` | OHLC from Alpaca |
| `high` | `float64` | Decimal | `119.31` | |
| `low` | `float64` | Decimal | `118.70` | |
| `close` | `float64` | Decimal | `118.89` | |
| `volume` | `float64` | Integer | `60756.0` | 5-min bar volume in shares |
| `symbol` | `object` | String | `"A"` | Ticker symbol |

**Conversion from Alpaca**:
- Alpaca returns 5-min bars as `TimeFrame(5, TimeFrameUnit.Minute)` with timestamp `datetime64[ns, UTC]`
- Convert UTC to market timezone: `bar.timestamp.tz_convert('America/New_York')`
- Result: `2021-01-04 09:30:00-05:00` (timezone-aware, EST/EDT)
- **Do NOT strip timezone** for 5-min data — trading logic depends on market hours awareness
- **Code**: `alpaca_fetch.py` lines 140 (TimeFrame) + 167-169 (tz conversion)

### Key Differences
| Aspect | Daily | 5-Minute |
|--------|-------|----------|
| Column name | `date` | `timestamp` |
| Datetime type | `datetime64[ns]` (naive) | `datetime64[ns, tz]` (aware) |
| Timezone | None (UTC midnight) | `America/New_York` |
| Rows per day | 1 | ~78 (market hours: 9:30-16:00, 1 bar per 5 min) |
| Use case | Backtesting, daily filters | Intraday trading, ORB calculations |

## Configuration

All settings in `DataPipeline/config.py`:

```python
# Fetch settings
FETCH_CONFIG = {
    "symbols_per_batch": 100,      # Parallel batch size
    "lookback_days": 14,            # How far back to fetch on update
    "start_date": "2021-01-01",     # Full historical backfill
}

# Enrichment settings
ENRICHMENT_CONFIG = {
    "atr_period": 14,               # ATR window
    "volume_period": 14,            # Avg volume window
    "min_price": 5.0,               # Price filter
    "min_atr": 0.50,                # ATR filter
    "min_volume": 1_000_000,        # Volume filter
}

# Validation settings
VALIDATION_CONFIG = {
    "min_file_size_bytes": 1000,
    "max_file_size_bytes": 100_000_000,
    "check_date_continuity": True,
}
```

## Logs & Results

Results saved to `logs/`:
- `orb_sync_YYYYMMDD_HHMMSS.log` — Detailed execution log
- `orb_sync_YYYYMMDD_HHMMSS.json` — Structured results (success/failure, timings, row counts)

Example JSON output:
```json
{
  "timestamp": "2025-12-09T18:00:15.123456",
  "total_symbols": 5012,
  "fetch": {
    "status": "success",
    "duration_seconds": 1800,
    "successful": 5012,
    "failed": 0,
    "rows_daily": 6_250_000
  },
  "enrich": {
    "status": "success",
    "duration_seconds": 300,
    "successful": 5012,
    "rows_processed": 6_250_000
  },
  "validation": {
    "status": "passed",
    "errors": [],
    "warnings": ["Stale data for 2 symbols"]
  },
  "db_sync": {
    "status": "success",
    "duration_seconds": 120,
    "successful": 5012
  },
  "total_duration_seconds": 2220,
  "status": "success"
}
```

## Scheduler Integration

Currently called via APScheduler in `main.py`:

```python
scheduler.add_job(
    func=run_daily_sync,
    trigger="cron",
    hour=18,  # 6 PM ET
    minute=0,
    day_of_week="mon-fri",
    id="orb_daily_sync",
)

def run_daily_sync():
    """Triggered at 6 PM ET (Mon-Fri)"""
    orchestrator = DailySyncOrchestrator()
    results = orchestrator.run()
    # Log results, trigger universe builds, etc.
```

## Error Handling

**Fetch errors**: Logged per-symbol, pipeline continues. Failed symbols skipped.

**Enrich errors**: Logged, column filled with NaN if enrichment fails.

**Validation warnings**: Logged but don't fail the pipeline.

**DB sync errors**: Logged per-symbol, pipeline continues.

**Critical errors**: Pipeline exits with status="failed" and non-zero exit code.

## Retained Utility Scripts

The following scripts are retained for analysis/reporting (not part of daily sync):

- `generate_rc_report.py` — Post-backtest report generation
- `generate_trade_charts.py` — Trade visualization
- `inspect_tickers.py` — Debug tool for ticker inspection
- `migrate_backtest_tables.py` — Database schema migrations
- `plot_debug.py` — Diagnostic plotting

## Performance Expectations

**Runtime** (all 5,012 symbols):
- Fetch: ~30-60 minutes (parallel, Alpaca rate-limited)
- Enrich: ~10-15 minutes (sequential, one symbol at a time)
- Validate: ~1-2 minutes
- DB sync: ~5-10 minutes
- **Total**: ~45-90 minutes (depending on data volume)

**Incremental update** (only new dates):
- Fetch: ~5-10 minutes (only missing dates)
- Enrich: ~2-3 minutes (only updated rows)
- Validate: <1 minute
- DB sync: ~2-3 minutes
- **Total**: ~10-20 minutes

## Development Usage

### Test fetch for 3 symbols
```bash
python DataPipeline/daily_sync.py --symbols AAPL MSFT TSLA --skip-enrich --skip-validation --skip-db-sync
```

### Test enrichment for 3 symbols
```bash
python DataPipeline/daily_sync.py --symbols AAPL MSFT TSLA --skip-fetch --skip-validation --skip-db-sync
```

### Dry run (validate existing data)
```bash
python DataPipeline/daily_sync.py --skip-fetch --skip-enrich --skip-db-sync
```

### Enable debug logging
```bash
python DataPipeline/daily_sync.py --log-level DEBUG
```

## Troubleshooting

**Issue**: Fetch stuck or very slow
- Check Alpaca API connectivity: `python -c "from alpaca.data.historical import StockHistoricalDataClient; print('OK')"`
- Check ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables
- Premium tier should handle 5 parallel requests

**Issue**: Enrichment produces NaN for shares_outstanding
- Check `data/raw/historical_shares.parquet` exists and has data
- Forward-fill set to 365 days by default

**Issue**: Validation warnings about stale data
- Expected if Alpaca data hasn't updated (weekend, holiday, or API lag)
- Safe to ignore if <2 days stale

**Issue**: Database sync failures
- Check DATABASE_URL environment variable
- Ensure PostgreSQL/SQLite is running
- Check `daily_metrics_historical` table exists in database

## Next Steps

After daily sync completes, trigger universe builds:

```bash
# Build ORB universe (Top-50 ATR ≥ 0.50)
python ORB/build_universe.py --start $(date -d yesterday +%Y-%m-%d) --end $(date +%Y-%m-%d)

# Build RC universe (gap ≥2%, RVOL ≥5.0, float <10M)
python RossCameron/build_universe.py --start $(date -d yesterday +%Y-%m-%d) --end $(date +%Y-%m-%d)
```

Then run backtests on fresh universes.
