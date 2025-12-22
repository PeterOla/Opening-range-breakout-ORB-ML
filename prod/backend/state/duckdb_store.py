from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import duckdb

from core.config import settings


ET = ZoneInfo("America/New_York")


def _state_db_path() -> Path:
    # Keep state separate from market-data DuckDB.
    raw = getattr(settings, "DUCKDB_STATE_PATH", "") or ""
    if raw.strip():
        return Path(raw)

    # Default local path (repo-root relative when run from prod/backend).
    return Path("./data/trading_state.duckdb")


@dataclass(frozen=True)
class StateSignal:
    id: int
    symbol: str
    side: str
    entry_price: float
    stop_price: float
    confidence: float
    timestamp: Optional[str]


class DuckDBStateStore:
    """DuckDB-backed trading state store.

    Stores:
    - opening_ranges: scan results / candidates
    - signals: generated signals + execution status

    This avoids SQLite/Postgres/SQLAlchemy for live runs.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else _state_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(str(self.path))
        # Safer defaults for single-process local usage
        con.execute("PRAGMA threads=4")
        return con

    def ensure_tables(self) -> None:
        con = self._connect()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS opening_ranges (
                    date DATE NOT NULL,
                    symbol VARCHAR NOT NULL,

                    or_open DOUBLE,
                    or_high DOUBLE,
                    or_low DOUBLE,
                    or_close DOUBLE,
                    or_volume BIGINT,

                    direction INTEGER,
                    rvol DOUBLE,
                    atr DOUBLE,
                    avg_volume BIGINT,

                    passed_filters BOOLEAN,
                    rank INTEGER,
                    entry_price DOUBLE,
                    stop_price DOUBLE,

                    signal_generated BOOLEAN DEFAULT FALSE,
                    order_placed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP,

                    PRIMARY KEY(date, symbol)
                )
                """
            )

            con.execute("CREATE SEQUENCE IF NOT EXISTS signals_id_seq")

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id BIGINT PRIMARY KEY DEFAULT nextval('signals_id_seq'),
                    signal_date DATE NOT NULL,
                    timestamp TIMESTAMP,
                    symbol VARCHAR NOT NULL,
                    side VARCHAR NOT NULL,
                    confidence DOUBLE,
                    entry_price DOUBLE,
                    stop_price DOUBLE,
                    status VARCHAR NOT NULL,
                    order_id VARCHAR,
                    filled_price DOUBLE,
                    filled_time TIMESTAMP,
                    rejection_reason VARCHAR,
                    created_at TIMESTAMP,
                    UNIQUE(signal_date, symbol)
                )
                """
            )

            # Schema evolution (DuckDB doesn't support IF NOT EXISTS on ADD COLUMN).
            # We keep this best-effort so existing DBs can be upgraded in place.
            for ddl in [
                "ALTER TABLE signals ADD COLUMN stop_submitted BOOLEAN DEFAULT FALSE",
                "ALTER TABLE signals ADD COLUMN stop_submitted_at TIMESTAMP",
            ]:
                try:
                    con.execute(ddl)
                except Exception:
                    pass
        finally:
            con.close()

    def get_latest_signal_for_symbol(self, target_date: date, symbol: str) -> Optional[dict]:
        """Fetch the latest signal row for a symbol on a given date."""
        self.ensure_tables()
        con = self._connect()
        try:
            sym = str(symbol or "").upper().strip()
            if not sym:
                return None
            df = con.execute(
                """
                SELECT
                    id,
                    symbol,
                    side,
                    entry_price,
                    stop_price,
                    status,
                    order_id,
                    COALESCE(stop_submitted, FALSE) AS stop_submitted,
                    stop_submitted_at,
                    created_at
                FROM signals
                WHERE signal_date = ? AND symbol = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [target_date, sym],
            ).fetchdf()
            if df is None or df.empty:
                return None
            row = df.iloc[0]
            return {
                "id": int(row["id"]),
                "symbol": str(row["symbol"]).upper().strip(),
                "side": str(row["side"]).upper().strip(),
                "entry_price": float(row["entry_price"]) if row.get("entry_price") is not None else None,
                "stop_price": float(row["stop_price"]) if row.get("stop_price") is not None else None,
                "status": str(row["status"]).upper().strip(),
                "order_id": row.get("order_id"),
                "stop_submitted": bool(row.get("stop_submitted")),
                "stop_submitted_at": row.get("stop_submitted_at"),
            }
        finally:
            con.close()

    def mark_stop_submitted(self, signal_id: int) -> bool:
        """Mark a signal as having had a protective stop submitted."""
        self.ensure_tables()
        con = self._connect()
        try:
            con.execute(
                """
                UPDATE signals
                SET stop_submitted = TRUE,
                    stop_submitted_at = ?
                WHERE id = ?
                """,
                [datetime.utcnow(), int(signal_id)],
            )
            return True
        except Exception:
            return False
        finally:
            con.close()

    def replace_opening_ranges(self, target_date: date, candidates: list[dict]) -> None:
        self.ensure_tables()
        con = self._connect()
        try:
            con.execute("DELETE FROM opening_ranges WHERE date = ?", [target_date])

            now_ts = datetime.utcnow()
            rows = []
            for c in candidates:
                rows.append(
                    (
                        target_date,
                        str(c.get("symbol") or "").upper().strip(),
                        c.get("or_open"),
                        c.get("or_high"),
                        c.get("or_low"),
                        c.get("or_close"),
                        int(c.get("or_volume")) if c.get("or_volume") is not None else None,
                        int(c.get("direction")) if c.get("direction") is not None else None,
                        float(c.get("rvol")) if c.get("rvol") is not None else None,
                        float(c.get("atr")) if c.get("atr") is not None else None,
                        int(c.get("avg_volume")) if c.get("avg_volume") is not None else None,
                        bool(c.get("passed_filters")) if c.get("passed_filters") is not None else False,
                        int(c.get("rank")) if c.get("rank") is not None else None,
                        float(c.get("entry_price")) if c.get("entry_price") is not None else None,
                        float(c.get("stop_price")) if c.get("stop_price") is not None else None,
                        bool(c.get("signal_generated")) if c.get("signal_generated") is not None else False,
                        bool(c.get("order_placed")) if c.get("order_placed") is not None else False,
                        now_ts,
                    )
                )

            if rows:
                con.executemany(
                    """
                    INSERT INTO opening_ranges (
                        date, symbol,
                        or_open, or_high, or_low, or_close, or_volume,
                        direction, rvol, atr, avg_volume,
                        passed_filters, rank, entry_price, stop_price,
                        signal_generated, order_placed, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        finally:
            con.close()

    def get_todays_candidates(self, top_n: int, direction: str) -> list[dict]:
        self.ensure_tables()
        con = self._connect()
        try:
            today = datetime.now(ET).date()
            base = "SELECT * FROM opening_ranges WHERE date = ? AND passed_filters = TRUE"
            params = [today]

            dir_norm = (direction or "both").strip().lower()
            if dir_norm == "long":
                base += " AND direction = 1"
            elif dir_norm == "short":
                base += " AND direction = -1"

            base += " ORDER BY rank ASC NULLS LAST LIMIT ?"
            params.append(int(top_n))

            df = con.execute(base, params).fetchdf()
            if df is None or df.empty:
                return []

            out: list[dict] = []
            for _, row in df.iterrows():
                out.append(
                    {
                        "symbol": str(row.get("symbol") or "").upper().strip(),
                        "direction": int(row.get("direction")) if row.get("direction") is not None else None,
                        "entry_price": float(row.get("entry_price")) if row.get("entry_price") is not None else None,
                        "stop_price": float(row.get("stop_price")) if row.get("stop_price") is not None else None,
                        "rvol": float(row.get("rvol")) if row.get("rvol") is not None else None,
                        "atr": float(row.get("atr")) if row.get("atr") is not None else None,
                        "or_high": float(row.get("or_high")) if row.get("or_high") is not None else None,
                        "or_low": float(row.get("or_low")) if row.get("or_low") is not None else None,
                        "rank": int(row.get("rank")) if row.get("rank") is not None else None,
                    }
                )
            return out
        finally:
            con.close()

    def mark_signals_generated(self, target_date: date, symbols: list[str]) -> None:
        if not symbols:
            return
        self.ensure_tables()
        con = self._connect()
        try:
            syms = [str(s).upper().strip() for s in symbols if s]
            con.execute(
                "UPDATE opening_ranges SET signal_generated = TRUE WHERE date = ? AND symbol IN (SELECT * FROM UNNEST(?))",
                [target_date, syms],
            )
        finally:
            con.close()

    def list_existing_signal_symbols(self, target_date: date) -> set[str]:
        self.ensure_tables()
        con = self._connect()
        try:
            # Only treat non-terminal signals as "existing" so REJECTED/CANCELLED can be regenerated.
            df = con.execute(
                """
                SELECT symbol
                FROM signals
                WHERE signal_date = ?
                  AND status NOT IN ('REJECTED', 'CANCELLED')
                """,
                [target_date],
            ).fetchdf()
            if df is None or df.empty:
                return set()
            return {str(s).upper().strip() for s in df["symbol"].dropna().tolist()}
        finally:
            con.close()

    def insert_signals(self, target_date: date, signals: list[dict]) -> None:
        if not signals:
            return
        self.ensure_tables()
        con = self._connect()
        try:
            now_ts = datetime.utcnow()

            # If a symbol already exists for the day but is terminal (REJECTED/CANCELLED),
            # reset it so it can be executed again.
            for s in signals:
                sym = str(s.get("symbol") or "").upper().strip()
                if not sym:
                    continue
                con.execute(
                    """
                    UPDATE signals
                    SET
                        timestamp = ?,
                        side = ?,
                        confidence = ?,
                        entry_price = ?,
                        stop_price = ?,
                        status = 'PENDING',
                        order_id = NULL,
                        filled_price = NULL,
                        filled_time = NULL,
                        rejection_reason = NULL,
                        created_at = ?
                    WHERE signal_date = ?
                      AND symbol = ?
                      AND status IN ('REJECTED', 'CANCELLED')
                    """,
                    [
                        datetime.utcnow(),
                        str(s.get("side") or "").upper().strip(),
                        float(s.get("confidence")) if s.get("confidence") is not None else None,
                        float(s.get("entry_price")) if s.get("entry_price") is not None else None,
                        float(s.get("stop_price")) if s.get("stop_price") is not None else None,
                        now_ts,
                        target_date,
                        sym,
                    ],
                )

            rows = []
            for s in signals:
                rows.append(
                    (
                        target_date,
                        datetime.utcnow(),
                        str(s.get("symbol") or "").upper().strip(),
                        str(s.get("side") or "").upper().strip(),
                        float(s.get("confidence")) if s.get("confidence") is not None else None,
                        float(s.get("entry_price")) if s.get("entry_price") is not None else None,
                        float(s.get("stop_price")) if s.get("stop_price") is not None else None,
                        "PENDING",
                        None,
                        None,
                        None,
                        None,
                        now_ts,
                    )
                )

            # Use the UNIQUE(signal_date, symbol) constraint to dedupe.
            # DuckDB supports ON CONFLICT DO NOTHING.
            con.executemany(
                """
                INSERT INTO signals (
                    signal_date, timestamp, symbol, side, confidence,
                    entry_price, stop_price, status,
                    order_id, filled_price, filled_time, rejection_reason,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_date, symbol) DO NOTHING
                """,
                rows,
            )
        finally:
            con.close()

    def get_pending_signals(self) -> list[dict]:
        self.ensure_tables()
        con = self._connect()
        try:
            df = con.execute(
                """
                SELECT id, symbol, side, entry_price, stop_price,
                       COALESCE(confidence, 1.0) AS confidence,
                       timestamp
                FROM signals
                WHERE status = 'PENDING'
                  AND order_id IS NULL
                ORDER BY timestamp DESC NULLS LAST
                """
            ).fetchdf()
            if df is None or df.empty:
                return []

            out: list[dict] = []
            for _, row in df.iterrows():
                out.append(
                    {
                        "id": int(row["id"]),
                        "symbol": str(row["symbol"]).upper().strip(),
                        "side": str(row["side"]).upper().strip(),
                        "entry_price": float(row["entry_price"]),
                        "stop_price": float(row["stop_price"]),
                        "confidence": float(row["confidence"]),
                        "timestamp": row["timestamp"].isoformat() if row.get("timestamp") is not None else None,
                    }
                )
            return out
        finally:
            con.close()

    def list_signals(self, limit: int = 50, offset: int = 0) -> list[dict]:
        self.ensure_tables()
        con = self._connect()
        try:
            df = con.execute(
                """
                SELECT
                    id,
                    COALESCE(timestamp, created_at) AS ts,
                    symbol,
                    side,
                    confidence,
                    entry_price,
                    status,
                    filled_price,
                    filled_time,
                    rejection_reason
                FROM signals
                ORDER BY ts DESC NULLS LAST, id DESC
                LIMIT ? OFFSET ?
                """,
                [int(limit), int(offset)],
            ).fetchdf()
            if df is None or df.empty:
                return []

            out: list[dict] = []
            for _, row in df.iterrows():
                ts = row.get("ts")
                filled_time = row.get("filled_time")
                out.append(
                    {
                        "id": int(row["id"]),
                        "timestamp": ts,
                        "symbol": str(row["symbol"] or "").upper().strip(),
                        "side": str(row["side"] or "").upper().strip(),
                        "confidence": float(row["confidence"]) if row.get("confidence") is not None else None,
                        "entry_price": float(row["entry_price"]) if row.get("entry_price") is not None else None,
                        "status": str(row["status"] or "").upper().strip(),
                        "filled_price": float(row["filled_price"]) if row.get("filled_price") is not None else None,
                        "filled_time": filled_time,
                        "rejection_reason": row.get("rejection_reason"),
                    }
                )
            return out
        finally:
            con.close()

    def list_active_signals(self, limit: int = 200) -> list[dict]:
        self.ensure_tables()
        con = self._connect()
        try:
            today = datetime.now(ET).date()
            df = con.execute(
                """
                SELECT
                    id,
                    COALESCE(timestamp, created_at) AS ts,
                    symbol,
                    side,
                    confidence,
                    entry_price,
                    status,
                    filled_price,
                    filled_time,
                    rejection_reason
                FROM signals
                WHERE signal_date = ?
                  AND status IN ('PENDING', 'PARTIAL')
                ORDER BY ts DESC NULLS LAST, id DESC
                LIMIT ?
                """,
                [today, int(limit)],
            ).fetchdf()
            if df is None or df.empty:
                return []

            out: list[dict] = []
            for _, row in df.iterrows():
                ts = row.get("ts")
                filled_time = row.get("filled_time")
                out.append(
                    {
                        "id": int(row["id"]),
                        "timestamp": ts,
                        "symbol": str(row["symbol"] or "").upper().strip(),
                        "side": str(row["side"] or "").upper().strip(),
                        "confidence": float(row["confidence"]) if row.get("confidence") is not None else None,
                        "entry_price": float(row["entry_price"]) if row.get("entry_price") is not None else None,
                        "status": str(row["status"] or "").upper().strip(),
                        "filled_price": float(row["filled_price"]) if row.get("filled_price") is not None else None,
                        "filled_time": filled_time,
                        "rejection_reason": row.get("rejection_reason"),
                    }
                )
            return out
        finally:
            con.close()

    def update_signal_status(
        self,
        signal_id: int,
        status: str,
        order_id: Optional[str] = None,
        filled_price: Optional[float] = None,
        rejection_reason: Optional[str] = None,
    ) -> bool:
        self.ensure_tables()
        con = self._connect()
        try:
            existing = con.execute("SELECT id FROM signals WHERE id = ?", [int(signal_id)]).fetchone()
            if not existing:
                return False

            filled_time = datetime.utcnow() if filled_price is not None else None

            con.execute(
                """
                UPDATE signals
                SET status = ?,
                    order_id = COALESCE(?, order_id),
                    filled_price = COALESCE(?, filled_price),
                    filled_time = COALESCE(?, filled_time),
                    rejection_reason = COALESCE(?, rejection_reason)
                WHERE id = ?
                """,
                [
                    str(status),
                    order_id,
                    filled_price,
                    filled_time,
                    rejection_reason,
                    int(signal_id),
                ],
            )
            return True
        finally:
            con.close()
