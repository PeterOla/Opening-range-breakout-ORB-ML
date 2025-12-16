"""Analyse tickers in missing_shares_ignore.json.

Goals
- Estimate how many ignored tickers are ETFs/ETNs/preferreds/units/warrants (and other non-common-stock types).
- Show which ignored tickers *actually* have shares data in data/raw/historical_shares.parquet.

Outputs (default)
- data/backtest/orb/reports/missing_shares_analysis.md
- data/backtest/orb/reports/assets/missing_shares_categories.png
- data/backtest/orb/reports/assets/recovered_shares_hist.png
- data/backtest/orb/reports/assets/recovered_shares_sample.csv

Run
  cd prod/backend
  python scripts/DataPipeline/analyse_missing_shares.py

Notes
- Uses SEC company_tickers.json "title" field for best-effort classification.
- This is heuristic (tickers are messy). It’s meant to guide universe filtering decisions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import argparse

import pandas as pd

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

from services.sec_shares import SecSharesClient


REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_RAW = REPO_ROOT / "data" / "raw"
BACKTEST_REPORTS = REPO_ROOT / "data" / "backtest" / "orb" / "reports"
ASSETS_DIR = BACKTEST_REPORTS / "assets"

IGNORE_FILE = DATA_RAW / "missing_shares_ignore.json"
HIST_SHARES = DATA_RAW / "historical_shares.parquet"

SEC_CACHE_DIR = DATA_RAW / "sec_cache"
SEC_TICKER_FILE = SEC_CACHE_DIR / "sec_company_tickers.json"


@dataclass(frozen=True)
class Classified:
    symbol: str
    title: str
    category: str
    category_reason: str


def _load_sec_ticker_titles() -> pd.DataFrame:
    """Load SEC company_tickers.json (cached by SecSharesClient) and return DataFrame with ticker/title."""
    if not SEC_TICKER_FILE.exists():
        # Trigger fetch + cache if needed (requires SEC_USER_AGENT).
        client = SecSharesClient()
        _ = client.load_or_fetch_ticker_cik_map(force_refresh=False)
        if not SEC_TICKER_FILE.exists():
            raise FileNotFoundError(
                f"SEC ticker cache still missing after fetch attempt: {SEC_TICKER_FILE}. "
                "Check SEC_USER_AGENT and network access."
            )

    raw = json.loads(SEC_TICKER_FILE.read_text(encoding="utf-8"))
    rows = []
    for _, r in raw.items():
        ticker = str(r.get("ticker", "")).strip().upper()
        title = str(r.get("title", "")).strip()
        if ticker:
            rows.append({"symbol": ticker, "title": title})
    return pd.DataFrame(rows).drop_duplicates(subset=["symbol"], keep="last")


def _categorise(symbol: str, title: str) -> tuple[str, str]:
    s = (symbol or "").upper().strip()
    t = (title or "").upper()

    # Strong suffix heuristics (common in NASDAQ for warrants/units/rights)
    if s.endswith("WS") or s.endswith("W"):
        return "Warrant", "symbol suffix W/WS"
    if s.endswith("U"):
        return "Unit", "symbol suffix U"
    if s.endswith("R"):
        return "Right", "symbol suffix R"

    # Title heuristics
    if "ETF" in t or "EXCHANGE TRADED FUND" in t:
        return "ETF", "title contains ETF"
    if "ETN" in t or "EXCHANGE TRADED NOTE" in t:
        return "ETN", "title contains ETN"

    # Preferred / depositary shares
    if "PREFERRED" in t or "DEPOSITARY" in t or "DEP SHS" in t or "PFD" in t:
        return "Preferred/Depositary", "title contains preferred/depositary"

    if "WARRANT" in t:
        return "Warrant", "title contains warrant"
    if "RIGHT" in t:
        return "Right", "title contains right"
    if "UNIT" in t:
        return "Unit", "title contains unit"

    # Other non-common-stock buckets (useful for deciding what to exclude)
    if "FUND" in t or "TRUST" in t or "PORTFOLIO" in t or "INCOME FUND" in t or "CLOSED-END" in t or "CLOSED END" in t:
        return "Fund/Trust", "title suggests fund/trust"
    if "NOTE" in t or "NOTES" in t or "BOND" in t or "DEBENTURE" in t:
        return "Debt/Note", "title suggests debt/note"

    return "Operating Co/Common", "default"


def _plot_category_counts(df_counts: pd.DataFrame, out_png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.figure(figsize=(12, 6))
    x = df_counts["category"].tolist()
    y = df_counts["count"].tolist()

    plt.bar(x, y)
    plt.title("Missing Shares Ignore List — Instrument Breakdown", fontsize=14)
    plt.ylabel("Count", fontsize=12)
    plt.xticks(rotation=30, ha="right", fontsize=11)
    plt.yticks(fontsize=11)
    plt.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=150)
    plt.close()


def _plot_recovered_hist(df_recovered: pd.DataFrame, out_png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if df_recovered.empty:
        return

    # Shares can be huge; use log10 scale for readability
    series = df_recovered["latest_shares"].dropna().astype(float)
    if series.empty:
        return

    plt.figure(figsize=(12, 6))
    plt.hist(series, bins=30)
    plt.title("Recovered (Ignored) Tickers With Shares — Latest Shares Outstanding", fontsize=14)
    plt.xlabel("Shares outstanding (raw)", fontsize=12)
    plt.ylabel("Count", fontsize=12)
    plt.xticks(fontsize=11)
    plt.yticks(fontsize=11)
    plt.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=150)
    plt.close()


def main() -> None:
    # Load environment variables (SEC_USER_AGENT typically lives in prod/backend/.env)
    if load_dotenv is not None:
        env_path = (REPO_ROOT / "prod" / "backend" / ".env")
        if env_path.exists():
            load_dotenv(env_path)

    ap = argparse.ArgumentParser(description="Analyse missing_shares_ignore.json instrument types")
    ap.add_argument(
        "--probe",
        type=int,
        default=0,
        help="Optional: probe SEC for this many candidate ignored tickers to see which now return shares (default: 0).",
    )
    args = ap.parse_args()

    if not IGNORE_FILE.exists():
        raise FileNotFoundError(f"Missing: {IGNORE_FILE}")
    if not HIST_SHARES.exists():
        raise FileNotFoundError(f"Missing: {HIST_SHARES}")

    ignore = json.loads(IGNORE_FILE.read_text(encoding="utf-8"))
    ignored_symbols = sorted([str(s).upper() for s in ignore.keys()])

    df_titles = _load_sec_ticker_titles()
    df_titles["symbol"] = df_titles["symbol"].astype(str).str.upper()

    # Join titles (many ignored symbols might not be in SEC map)
    df = pd.DataFrame({"symbol": ignored_symbols})
    df = df.merge(df_titles, how="left", left_on="symbol", right_on="symbol")
    df["title"] = df["title"].fillna("")

    classified = []
    for row in df.itertuples(index=False):
        cat, reason = _categorise(row.symbol, row.title)
        classified.append({
            "symbol": row.symbol,
            "title": row.title,
            "category": cat,
            "reason": reason,
            "in_sec_ticker_map": bool(row.title),
        })

    df_cls = pd.DataFrame(classified)

    # Category counts (and keep a consistent order including the user-requested buckets)
    base_counts = (
        df_cls.groupby("category", as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    desired_order = [
        "Operating Co/Common",
        "ETF",
        "ETN",
        "Preferred/Depositary",
        "Unit",
        "Warrant",
        "Right",
        "Fund/Trust",
        "Debt/Note",
    ]
    df_counts = (
        base_counts.set_index("category")
        .reindex(desired_order, fill_value=0)
        .reset_index()
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )
    total = int(df_counts["count"].sum())
    df_counts["pct"] = (df_counts["count"] / total * 100.0).round(2)

    # Which ignored symbols actually have shares already? (Expected to be near-zero by design.)
    df_sh = pd.read_parquet(HIST_SHARES)
    df_sh["symbol"] = df_sh["symbol"].astype(str).str.upper()
    df_sh["date"] = pd.to_datetime(df_sh["date"], errors="coerce")

    ignored_set = set(ignored_symbols)
    df_sh_ignored = df_sh[df_sh["symbol"].isin(ignored_set)].copy()

    if df_sh_ignored.empty:
        df_recovered = pd.DataFrame(columns=["symbol", "records", "latest_date", "latest_shares"])
    else:
        g = df_sh_ignored.sort_values(["symbol", "date"]).groupby("symbol")
        df_recovered = g.agg(
            records=("shares_outstanding", "count"),
            latest_date=("date", "max"),
            latest_shares=("shares_outstanding", "last"),
        ).reset_index()
        df_recovered = df_recovered.sort_values(["latest_date", "records"], ascending=[False, False])

    # Write assets
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    cat_png = ASSETS_DIR / "missing_shares_categories.png"
    rec_csv = ASSETS_DIR / "recovered_shares_sample.csv"

    _plot_category_counts(df_counts, cat_png)
    # Save a small sample CSV (top 50)
    df_recovered.head(50).to_csv(rec_csv, index=False)

    # Optional: probe SEC for a subset of ignored tickers that look like operating companies.
    df_probe_hits = pd.DataFrame(columns=["symbol", "rows", "latest_date", "latest_shares"])
    probe_csv = ASSETS_DIR / "probe_hits.csv"
    if int(args.probe) > 0:
        client = SecSharesClient()
        sec_map = client.load_or_fetch_ticker_cik_map(force_refresh=False)

        # Candidates: ignored, in SEC map, and our heuristic says "Operating Co/Common".
        candidates = df_cls[
            (df_cls["category"] == "Operating Co/Common")
            & (df_cls["symbol"].isin(sec_map.keys()))
        ]["symbol"].tolist()

        # Spread selection across the list deterministically.
        n = min(int(args.probe), len(candidates))
        if n > 0:
            step = max(1, len(candidates) // n)
            sample = [candidates[i] for i in range(0, len(candidates), step)][:n]

            rows = []
            for s in sample:
                df_series = client.get_shares_series(s, force_refresh=True)
                if df_series.empty:
                    continue
                df_series = df_series.sort_values("date")
                latest_date = pd.to_datetime(df_series["date"]).max()
                latest_shares = int(df_series.iloc[-1]["shares_outstanding"])
                rows.append({"symbol": s, "rows": len(df_series), "latest_date": latest_date, "latest_shares": latest_shares})

            if rows:
                df_probe_hits = pd.DataFrame(rows).sort_values(["latest_date", "rows"], ascending=[False, False])
                df_probe_hits.to_csv(probe_csv, index=False)
            else:
                df_probe_hits = pd.DataFrame(columns=["symbol", "rows", "latest_date", "latest_shares"])

    # Markdown report
    out_md = BACKTEST_REPORTS / "missing_shares_analysis.md"

    lines = []
    lines.append("# Missing Shares Ignore List — Analysis\n")
    lines.append(f"Total ignored tickers: **{len(ignored_symbols):,}**\n")
    lines.append(f"Tickers with SEC title metadata: **{int(df_cls['in_sec_ticker_map'].sum()):,}**\n")
    lines.append("\n")

    lines.append("## Breakdown (Heuristic)\n")
    lines.append("This is a best-effort classification using SEC ticker titles + ticker suffix rules.\n")
    lines.append("\n")
    lines.append("| Category | Count | % |")
    lines.append("|---|---:|---:|")
    for r in df_counts.itertuples(index=False):
        lines.append(f"| {r.category} | {int(r.count):,} | {float(r.pct):.2f}% |")
    lines.append("\n")
    lines.append(f"![Instrument breakdown](assets/{cat_png.name})\n")

    lines.append("## Recovered: Ignored Tickers That Already Have Shares Data\n")
    lines.append(
        "These are tickers present in `missing_shares_ignore.json` **but** also present in `data/raw/historical_shares.parquet`.\n"
    )
    lines.append("\n")
    lines.append(f"Recovered symbols: **{df_recovered['symbol'].nunique():,}**\n")
    lines.append("\n")

    if df_recovered.empty:
        lines.append("No recovered symbols found.\n")
    else:
        lines.append("Top 20 (most recent):\n")
        lines.append("\n")
        top = df_recovered.head(20).copy()
        top["latest_date"] = pd.to_datetime(top["latest_date"]).dt.strftime("%Y-%m-%d")
        lines.append("| Symbol | Records | Latest date | Latest shares |")
        lines.append("|---|---:|---:|---:|")
        for r in top.itertuples(index=False):
            lines.append(f"| {r.symbol} | {int(r.records):,} | {r.latest_date} | {int(r.latest_shares):,} |")
        lines.append("\n")
        lines.append(f"CSV sample: `assets/{rec_csv.name}`\n")

    if int(args.probe) > 0:
        lines.append("\n")
        lines.append("## Probe: Re-check a Sample Against SEC (Force Refresh)\n")
        lines.append(
            "This does *live* SEC Company Facts lookups for a sample of ignored tickers that look like operating companies, "
            "to catch cases where shares data has become available since we last ignored them.\n"
        )
        lines.append("\n")
        lines.append(f"Probe sample size: **{int(args.probe):,}**\n")
        lines.append(f"Hits (now returning shares): **{int(df_probe_hits.shape[0]):,}**\n")
        lines.append("\n")

        if df_probe_hits.empty:
            lines.append("No hits found in this probe run.\n")
        else:
            lines.append("Hits table:\n")
            lines.append("\n")
            tmp = df_probe_hits.copy()
            tmp["latest_date"] = pd.to_datetime(tmp["latest_date"]).dt.strftime("%Y-%m-%d")
            lines.append("| Symbol | Rows | Latest date | Latest shares |")
            lines.append("|---|---:|---:|---:|")
            for r in tmp.head(50).itertuples(index=False):
                lines.append(f"| {r.symbol} | {int(r.rows):,} | {r.latest_date} | {int(r.latest_shares):,} |")
            lines.append("\n")
            lines.append(f"CSV: `assets/{probe_csv.name}`\n")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote report: {out_md}")


if __name__ == "__main__":
    main()
