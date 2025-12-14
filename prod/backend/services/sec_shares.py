"""SEC-based shares outstanding fetcher (free).

Why this exists
- Alpha Vantage is rate-limited and frequently missing/incorrect for microcaps.
- SEC XBRL Company Facts is free, reasonably complete for SEC filers, and gives
  time-stamped shares outstanding values from filings.

What we store
- A historical series (typically quarterly/filing cadence) per symbol.
- Downstream enrichment uses merge_asof to pick the latest value as-of each
  trading date.

Notes
- SEC requires a descriptive User-Agent with contact details.
  Set `SEC_USER_AGENT` in your environment/.env.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd
import requests


SEC_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _repo_root() -> Path:
    # .../prod/backend/services/sec_shares.py -> repo root is 4 parents up
    return Path(__file__).resolve().parents[4]


def _data_raw_dir() -> Path:
    return _repo_root() / "data" / "raw"


def normalise_ticker(symbol: str) -> str:
    """Normalise tickers to match SEC conventions (e.g. BRK.B -> BRK-B)."""
    s = (symbol or "").strip().upper()
    s = s.replace(".", "-")
    s = s.replace("/", "-")
    return s


def _require_sec_user_agent() -> str:
    ua = os.getenv("SEC_USER_AGENT", "").strip()
    if not ua:
        raise RuntimeError(
            "SEC_USER_AGENT is not set. SEC requests require a descriptive User-Agent "
            "with contact details (e.g. 'ORBResearch/1.0 you@email.com')."
        )
    return ua


@dataclass(frozen=True)
class SecCachePaths:
    base_dir: Path

    @property
    def ticker_map(self) -> Path:
        return self.base_dir / "sec_company_tickers.json"

    @property
    def companyfacts_dir(self) -> Path:
        return self.base_dir / "sec_companyfacts"


class SecSharesClient:
    def __init__(self, user_agent: Optional[str] = None, cache_dir: Optional[Path] = None):
        self.user_agent = (user_agent or os.getenv("SEC_USER_AGENT", "")).strip()
        self.cache = SecCachePaths(base_dir=(cache_dir or (_data_raw_dir() / "sec_cache")))
        self.cache.base_dir.mkdir(parents=True, exist_ok=True)
        self.cache.companyfacts_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        ua = self.user_agent or _require_sec_user_agent()
        return {
            "User-Agent": ua,
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov",
        }

    def _get_json(self, url: str, *, host: str, timeout: int = 30) -> Dict[str, Any]:
        headers = dict(self._headers())
        headers["Host"] = host
        resp = self._session.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def load_or_fetch_ticker_cik_map(self, *, force_refresh: bool = False) -> Dict[str, str]:
        """Return mapping of TICKER -> zero-padded 10-digit CIK string."""
        if self.cache.ticker_map.exists() and not force_refresh:
            data = json.loads(self.cache.ticker_map.read_text(encoding="utf-8"))
        else:
            data = self._get_json(SEC_TICKER_CIK_URL, host="www.sec.gov")
            self.cache.ticker_map.write_text(json.dumps(data), encoding="utf-8")

        # SEC format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
        mapping: Dict[str, str] = {}
        for _, row in data.items():
            try:
                ticker = normalise_ticker(row.get("ticker", ""))
                cik_int = int(row.get("cik_str"))
                mapping[ticker] = f"{cik_int:010d}"
            except Exception:
                continue
        return mapping

    def ticker_to_cik(self, symbol: str, *, force_refresh_map: bool = False) -> Optional[str]:
        sym = normalise_ticker(symbol)
        mapping = self.load_or_fetch_ticker_cik_map(force_refresh=force_refresh_map)
        return mapping.get(sym)

    def load_or_fetch_company_facts(self, cik: str, *, force_refresh: bool = False, polite_sleep_s: float = 0.15) -> Dict[str, Any]:
        cik = str(cik).zfill(10)
        cache_path = self.cache.companyfacts_dir / f"CIK{cik}.json"
        if cache_path.exists() and not force_refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        url = SEC_COMPANY_FACTS_URL.format(cik=cik)
        data = self._get_json(url, host="data.sec.gov")
        cache_path.write_text(json.dumps(data), encoding="utf-8")
        # Be polite to SEC (avoid hammering endpoints)
        if polite_sleep_s:
            time.sleep(polite_sleep_s)
        return data

    @staticmethod
    def _extract_shares_fact_units(companyfacts: Dict[str, Any]) -> Optional[list[dict]]:
        facts = (companyfacts or {}).get("facts", {})
        # This fact is typically under `dei`, but some feeds also carry it under `us-gaap`.
        for taxonomy in ("dei", "us-gaap"):
            node = facts.get(taxonomy, {}).get("EntityCommonStockSharesOutstanding")
            if not node:
                continue
            units = node.get("units", {})
            if "shares" in units and isinstance(units["shares"], list):
                return units["shares"]
        return None

    def get_shares_series(self, symbol: str, *, force_refresh: bool = False) -> pd.DataFrame:
        """Return a historical shares outstanding series for `symbol`.

        Output columns: symbol, date, shares_outstanding
        """
        cik = self.ticker_to_cik(symbol)
        if not cik:
            return pd.DataFrame(columns=["symbol", "date", "shares_outstanding"])

        facts = self.load_or_fetch_company_facts(cik, force_refresh=force_refresh)
        rows = self._extract_shares_fact_units(facts) or []
        if not rows:
            return pd.DataFrame(columns=["symbol", "date", "shares_outstanding"])

        records: list[dict] = []
        for r in rows:
            end = r.get("end") or r.get("date")
            val = r.get("val")
            if not end or val is None:
                continue
            try:
                shares = int(float(val))
                if shares <= 0:
                    continue
                records.append(
                    {
                        "symbol": normalise_ticker(symbol),
                        "date": pd.to_datetime(end),
                        "shares_outstanding": shares,
                    }
                )
            except Exception:
                continue

        if not records:
            return pd.DataFrame(columns=["symbol", "date", "shares_outstanding"])

        df = pd.DataFrame(records)
        df = df.dropna(subset=["date", "shares_outstanding"])
        df = df.drop_duplicates(subset=["symbol", "date"], keep="last")
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        return df

    def fetch_shares_for_symbols(self, symbols: Iterable[str], *, force_refresh: bool = False) -> pd.DataFrame:
        """Fetch shares outstanding series for multiple symbols."""
        out = []
        for s in symbols:
            df = self.get_shares_series(s, force_refresh=force_refresh)
            if not df.empty:
                out.append(df)
        if not out:
            return pd.DataFrame(columns=["symbol", "date", "shares_outstanding"])
        return pd.concat(out, ignore_index=True)


def get_latest_shares_outstanding(symbol: str, *, user_agent: Optional[str] = None) -> Optional[int]:
    client = SecSharesClient(user_agent=user_agent)
    df = client.get_shares_series(symbol)
    if df.empty:
        return None
    return int(df.iloc[-1]["shares_outstanding"])
