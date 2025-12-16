"""
Data synchronisation service.

- Nightly job: Load daily bars from local Parquet files → daily_bars table
- Calculate ATR(14) and avg_volume(14) for each symbol
- Delete bars older than 30 days

Reads from: data/processed/daily/*.parquet
"""
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import and_, delete
import asyncio
import os
from pathlib import Path

from alpaca.trading.requests import GetCalendarRequest
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from execution.alpaca_client import get_alpaca_client, get_data_client

from db.database import SessionLocal
from db.models import DailyBar, Ticker
from core.config import settings

ET = ZoneInfo("America/New_York")

def get_trading_days(start_date: datetime, end_date: datetime) -> list[datetime]:
    """
    Get list of trading days using Alpaca calendar.
    """
    try:
        client = get_alpaca_client()
        # Ensure we pass date objects
        s = start_date.date() if isinstance(start_date, datetime) else start_date
        e = end_date.date() if isinstance(end_date, datetime) else end_date
        
        request = GetCalendarRequest(start=s, end=e)
        calendar = client.get_calendar(request)
        
        days = []
        for cal in calendar:
            d = cal.date
            # Convert to datetime at midnight to match expected interface
            dt = datetime.combine(d, datetime.min.time())
            days.append(dt)
        return days
    except Exception as e:
        print(f"Error fetching calendar: {e}")
        # Fallback to simple weekday check
        days = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
        return days

def get_data_dir() -> Path:
    """
    Resolve the data directory path.
    Assumes structure:
    root/
      data/
        processed/
          daily/
      prod/
        backend/
    """
    # Start from current file location
    current_file = Path(__file__).resolve()
    # Go up to prod/backend/services -> prod/backend -> prod -> root
    root_dir = current_file.parent.parent.parent.parent
    data_dir = root_dir / "data" / "processed" / "daily"
    
    if not data_dir.exists():
        # Fallback: try relative to CWD if running from root
        cwd_data = Path("data/processed/daily")
        if cwd_data.exists():
            return cwd_data.resolve()
            
    return data_dir




def compute_atr(bars: list[dict], period: int = 14) -> Optional[float]:
    """
    Compute ATR from list of daily bar dicts.
    Returns latest ATR value.
    """
    if len(bars) < period + 1:
        return None
    
    df = pd.DataFrame(bars).sort_values("timestamp").reset_index(drop=True)
    
    prev_close = df["close"].shift(1)
    high_low = df["high"] - df["low"]
    high_prev_close = (df["high"] - prev_close).abs()
    low_prev_close = (df["low"] - prev_close).abs()
    
    tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    
    latest = atr.iloc[-1] if not atr.empty else None
    return float(latest) if pd.notna(latest) else None


def compute_avg_volume(bars: list[dict], period: int = 14) -> Optional[float]:
    """
    Compute average volume from list of daily bar dicts.
    Returns latest avg volume value.
    """
    if len(bars) < period:
        return None
    
    df = pd.DataFrame(bars).sort_values("timestamp").reset_index(drop=True)
    avg_vol = df["volume"].rolling(window=period, min_periods=period).mean()
    
    latest = avg_vol.iloc[-1] if not avg_vol.empty else None
    return float(latest) if pd.notna(latest) else None


async def sync_daily_bars_from_parquet(lookback_days: int = 30) -> dict:
    """
    Sync daily bars from local Parquet files to database.
    
    Returns:
        Dict with sync stats
    """
    db = SessionLocal()
    
    try:
        data_dir = get_data_dir()
        if not data_dir.exists():
            return {"status": "error", "error": f"Data directory not found: {data_dir}"}
            
        parquet_files = list(data_dir.glob("*.parquet"))
        if not parquet_files:
            return {"status": "error", "error": f"No parquet files found in {data_dir}"}
            
        print(f"Found {len(parquet_files)} parquet files in {data_dir}")
        
        # Get active tickers to filter (optional, but good for performance)
        active_symbols = set(
            row[0] for row in db.query(Ticker.symbol).filter(Ticker.active == True).all()
        )
        
        files_to_process = []
        for p in parquet_files:
            sym = p.stem  # filename without extension
            if not active_symbols or sym in active_symbols:
                files_to_process.append(p)
                
        print(f"Syncing {len(files_to_process)} symbols from parquet...")
        
        cutoff_date = datetime.now(ET) - timedelta(days=lookback_days + 20) # Buffer
        
        synced_count = 0
        metrics_updated = 0
        
        for i, p_file in enumerate(files_to_process):
            symbol = p_file.stem
            if i % 100 == 0:
                print(f"Processing {i}/{len(files_to_process)}: {symbol}")
                
            try:
                df = pd.read_parquet(p_file)
                
                # Ensure columns exist
                required_cols = ['open', 'high', 'low', 'close', 'volume']
                if not all(col in df.columns for col in required_cols):
                    print(f"Skipping {symbol}: missing columns")
                    continue
                
                # Handle index as date if needed, or 'date' column
                if 'date' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['date'])
                elif isinstance(df.index, pd.DatetimeIndex):
                    df['timestamp'] = df.index
                else:
                    # Try to find a date column
                    print(f"Skipping {symbol}: no date column")
                    continue
                
                # Filter by date
                df = df[df['timestamp'] >= cutoff_date.replace(tzinfo=None)]
                
                if df.empty:
                    continue
                
                # Convert to list of dicts for processing
                bars = []
                for _, row in df.iterrows():
                    bars.append({
                        "timestamp": row['timestamp'],
                        "open": row['open'],
                        "high": row['high'],
                        "low": row['low'],
                        "close": row['close'],
                        "volume": row['volume'],
                        "vwap": row.get('vwap')
                    })
                
                # Compute metrics
                atr_14 = compute_atr(bars, 14)
                avg_vol_14 = compute_avg_volume(bars, 14)
                
                # Upsert to DB
                # First delete existing in range to avoid duplicates/conflicts
                min_date = df['timestamp'].min()
                db.execute(
                    delete(DailyBar).where(
                        and_(
                            DailyBar.symbol == symbol,
                            DailyBar.date >= min_date
                        )
                    )
                )
                
                for bar in bars:
                    is_latest = (bar == bars[-1])
                    db_bar = DailyBar(
                        symbol=symbol,
                        date=bar["timestamp"],
                        open=bar["open"],
                        high=bar["high"],
                        low=bar["low"],
                        close=bar["close"],
                        volume=bar["volume"],
                        vwap=bar.get("vwap"),
                        atr_14=atr_14 if is_latest else None,
                        avg_volume_14=avg_vol_14 if is_latest else None
                    )
                    db.add(db_bar)
                
                synced_count += len(bars)
                if atr_14 is not None:
                    metrics_updated += 1
                    
                # Commit every 10 symbols
                if i % 10 == 0:
                    db.commit()
                    
            except Exception as e:
                print(f"Error processing {symbol}: {e}")
                db.rollback()
        
        db.commit()
        return {
            "status": "success",
            "symbols_processed": len(files_to_process),
            "bars_synced": synced_count,
            "metrics_updated": metrics_updated
        }
        
    except Exception as e:
        db.rollback()
        return {"status": "error", "error": str(e)}
    
    finally:
        db.close()


async def sync_daily_bars_from_alpaca(symbols: Optional[list[str]] = None, lookback_days: int = 14) -> dict:
    """
    Sync daily bars from Alpaca for active tickers.
    If symbols provided, syncs only those. Otherwise syncs all active tickers.
    """
    db = SessionLocal()
    data_client = get_data_client()
    
    try:
        if symbols:
            active_symbols = symbols
        else:
            # Get active tickers
            active_symbols = [
                row[0] for row in db.query(Ticker.symbol).filter(Ticker.active == True).all()
            ]
        
        if not active_symbols:
            return {"status": "error", "error": "No active tickers"}
            
        print(f"Syncing bars for {len(active_symbols)} tickers from Alpaca...")
        
        end_dt = datetime.now(ET)
        start_dt = end_dt - timedelta(days=lookback_days + 5) # Buffer
        
        # Chunk symbols to avoid huge requests
        chunk_size = 100
        total_synced = 0
        metrics_updated = 0
        
        for i in range(0, len(active_symbols), chunk_size):
            chunk = active_symbols[i:i+chunk_size]
            print(f"Fetching chunk {i//chunk_size + 1}/{(len(active_symbols)-1)//chunk_size + 1} ({len(chunk)} symbols)...")
            
            try:
                request = StockBarsRequest(
                    symbol_or_symbols=chunk,
                    timeframe=TimeFrame.Day,
                    start=start_dt,
                    end=end_dt,
                    adjustment='all'
                )
                
                bars_map = data_client.get_stock_bars(request)
                
                # Process bars
                for symbol, bars in bars_map.data.items():
                    if not bars:
                        continue
                        
                    # Convert to list of dicts
                    bar_dicts = []
                    for b in bars:
                        bar_dicts.append({
                            "timestamp": b.timestamp,
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                            "vwap": b.vwap
                        })
                    
                    # Compute metrics
                    atr_14 = compute_atr(bar_dicts, 14)
                    avg_vol_14 = compute_avg_volume(bar_dicts, 14)
                    
                    # Upsert
                    # Delete existing in range
                    min_date = bar_dicts[0]["timestamp"]
                    db.execute(
                        delete(DailyBar).where(
                            and_(
                                DailyBar.symbol == symbol,
                                DailyBar.date >= min_date
                            )
                        )
                    )
                    
                    for b_dict in bar_dicts:
                        is_latest = (b_dict == bar_dicts[-1])
                        db_bar = DailyBar(
                            symbol=symbol,
                            date=b_dict["timestamp"],
                            open=b_dict["open"],
                            high=b_dict["high"],
                            low=b_dict["low"],
                            close=b_dict["close"],
                            volume=b_dict["volume"],
                            vwap=b_dict["vwap"],
                            atr_14=atr_14 if is_latest else None,
                            avg_volume_14=avg_vol_14 if is_latest else None
                        )
                        db.add(db_bar)
                    
                    total_synced += len(bar_dicts)
                    if atr_14 is not None:
                        metrics_updated += 1
                
                db.commit()
                
            except Exception as e:
                print(f"Error fetching chunk: {e}")
                db.rollback()
                
        return {
            "status": "success",
            "symbols_processed": len(active_symbols),
            "bars_synced": total_synced,
            "metrics_updated": metrics_updated
        }
        
    except Exception as e:
        db.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


async def cleanup_old_bars(days_to_keep: int = 30) -> int:
    """
    Delete daily bars older than specified days.
    Returns number of rows deleted.
    """
    db = SessionLocal()
    
    try:
        cutoff = datetime.now(ET) - timedelta(days=days_to_keep)
        
        result = db.execute(
            delete(DailyBar).where(DailyBar.date < cutoff)
        )
        
        db.commit()
        return result.rowcount
    
    except Exception as e:
        db.rollback()
        print(f"Error cleaning up old bars: {e}")
        return 0
    
    finally:
        db.close()


def get_latest_metrics(symbol: str, db: Optional[Session] = None) -> dict:
    """
    Get latest ATR and avg volume for a symbol from database.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True
    
    try:
        latest = db.query(DailyBar).filter(
            DailyBar.symbol == symbol
        ).order_by(DailyBar.date.desc()).first()
        
        if latest:
            return {
                "symbol": symbol,
                "date": latest.date,
                "close": latest.close,
                "atr_14": latest.atr_14,
                "avg_volume_14": latest.avg_volume_14,
            }
        
        return {}
    
    finally:
        if close_session:
            db.close()


def get_universe_with_metrics(
    min_price: float = 5.0,
    min_atr: float = 0.50,
    min_avg_volume: float = 1_000_000,
    allowed_symbols: Optional[set[str]] = None,
    db: Optional[Session] = None,
) -> list[dict]:
    """
    Get all symbols from daily_bars that pass base filters.
    Returns list of symbols with their latest metrics.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    def _repo_root() -> Path:
        # services/data_sync.py -> services -> backend -> prod -> repo_root
        return Path(__file__).resolve().parents[3]

    def _daily_parquet_dir() -> Path:
        p1 = _repo_root() / "data" / "processed" / "daily"
        p2 = Path("data/processed/daily")
        return p1 if p1.exists() else p2

    def _get_universe_with_metrics_from_local_parquet() -> list[dict]:
        import duckdb

        daily_dir = _daily_parquet_dir()
        if not daily_dir.exists():
            return []

        glob_path = str((daily_dir / "*.parquet").resolve()).replace("\\", "/")
        duckdb_path = getattr(settings, "DUCKDB_PATH", None)
        con = duckdb.connect(database=(duckdb_path or ":memory:"))

        allowed_df = None
        if allowed_symbols is not None:
            allowed_df = pd.DataFrame({"symbol": [str(s).upper().strip() for s in allowed_symbols if s]})
            if not allowed_df.empty:
                con.register("allowed_symbols", allowed_df)

        base_query = """
            WITH raw AS (
                SELECT
                    symbol,
                    date,
                    close,
                    atr_14,
                    avg_volume_14
                FROM read_parquet(? )
                WHERE atr_14 IS NOT NULL
                  AND avg_volume_14 IS NOT NULL
            ),
            latest AS (
                SELECT
                    symbol,
                    max(date) AS date,
                    arg_max(close, date) AS close,
                    arg_max(atr_14, date) AS atr_14,
                    arg_max(avg_volume_14, date) AS avg_volume_14
                FROM raw
                GROUP BY symbol
            )
            SELECT
                l.symbol,
                l.date,
                l.close,
                l.atr_14,
                l.avg_volume_14
            FROM latest l
        """

        if allowed_df is not None and not allowed_df.empty:
            base_query += " JOIN allowed_symbols a ON a.symbol = l.symbol "

        base_query += """
            WHERE l.close >= ?
              AND l.atr_14 >= ?
              AND l.avg_volume_14 >= ?
        """

        df = con.execute(base_query, [glob_path, float(min_price), float(min_atr), float(min_avg_volume)]).fetchdf()
        if df is None or df.empty:
            return []

        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        return [
            {
                "symbol": row["symbol"],
                "date": row["date"],
                "close": float(row["close"]),
                "atr_14": float(row["atr_14"]),
                "avg_volume_14": float(row["avg_volume_14"]),
            }
            for _, row in df.iterrows()
        ]
    
    try:
        # Prefer DB path when available; fall back to local Parquet via DuckDB.
        try:
            # Get latest bar per symbol with metrics
            from sqlalchemy import func

            # Subquery for latest date per symbol
            subq = db.query(
                DailyBar.symbol,
                func.max(DailyBar.date).label("max_date")
            ).group_by(DailyBar.symbol).subquery()

            # Join to get full bar data
            latest_bars = db.query(DailyBar).join(
                subq,
                and_(
                    DailyBar.symbol == subq.c.symbol,
                    DailyBar.date == subq.c.max_date,
                )
            ).filter(
                DailyBar.close >= min_price,
                DailyBar.atr_14 >= min_atr,
                DailyBar.avg_volume_14 >= min_avg_volume,
            ).all()

            if latest_bars:
                out = [
                    {
                        "symbol": bar.symbol,
                        "date": bar.date,
                        "close": bar.close,
                        "atr_14": bar.atr_14,
                        "avg_volume_14": bar.avg_volume_14,
                    }
                    for bar in latest_bars
                ]
                if allowed_symbols is not None:
                    allowed = {str(s).upper().strip() for s in allowed_symbols if s}
                    out = [r for r in out if r["symbol"].upper() in allowed]
                return out

        except Exception:
            # Common case: sqlite DB exists but daily_bars table isn't created/populated.
            pass

        return _get_universe_with_metrics_from_local_parquet()
    
    finally:
        if close_session:
            db.close()
