# Data Update Pipeline - Current Status

## Step 1: Fetch Missing Data (CURRENTLY RUNNING)
**Status**: IN PROGRESS  
**Job ID**: PowerShell Job "AlpacaFetch" (ID 1)  
**Progress**: ~118/5012 symbols (2%)  
**Command**: `python data/scripts/fetch_alpaca_data.py --update-all --end 2025-12-08`

**What's happening**:
- Fetching 25 trading days of data (2025-11-14 to 2025-12-08)
- Appending to existing parquet files from Polygon
- Processing both daily and 5-minute bars
- Date format: Daily bars converted to string format (YYYY-MM-DD) to match Polygon schema

**Estimated Duration**: 3-5 hours (5,012 symbols × 2 data frequencies)

**To check status**:
```powershell
Receive-Job -Name "AlpacaFetch" -Keep | Select-Object -Last 30
```

**To wait for completion**:
```powershell
Wait-Job -Name "AlpacaFetch"
Receive-Job -Name "AlpacaFetch"  # Get final output
```

---

## Steps 2-4: Once Fetch Completes

### Step 2: Enrich Daily Data with Shares
**Script**: `prod/backend/scripts/enrich_daily_data.py`  
**Purpose**: Add `shares_outstanding` column to daily parquet files  
**Command**: 
```bash
python prod/backend/scripts/enrich_daily_data.py
```

### Step 3: Rebuild ORB Universes
**Script**: `prod/backend/scripts/build_universe.py`  
**Purpose**: Compute RVOL, ATR14, TR for all symbols/dates  
**Output**: `data/backtest/universe_020_*.parquet` and `universe_050_*.parquet`  
**Command**:
```bash
python prod/backend/scripts/build_universe.py --start 2021-01-01 --end 2025-12-08
```

### Step 4: Rebuild RC Universe
**Script**: `prod/backend/scripts/build_ross_cameron_universe.py`  
**Purpose**: Filter by RC criteria (price $2-20, gap 2%, RVOL ≥5.0, float <10M)  
**Output**: `data/backtest/universes/universe_rc_*.parquet`  
**Command**:
```bash
python prod/backend/scripts/build_ross_cameron_universe.py --start 2021-01-01 --end 2025-12-08
```

---

## Summary

- **Daily Data**: Last updated 2025-11-13 → Will be updated to 2025-12-05 (Alpaca's latest)
- **5-Min Data**: Last updated 2025-11-13 → Will be updated to 2025-12-05  
- **Symbols**: 5,012 total  
- **Total Runtime**: ~6-8 hours (fetch + enrich + universe build)

Once complete, we'll be ready for Ross Cameron backtest with the latest data.
