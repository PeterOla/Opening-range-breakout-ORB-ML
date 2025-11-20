import pandas as pd
from pathlib import Path
from typing import List, Tuple, Dict

from src.strategy_orb import run_orb_single_symbol


def load_universe(path: Path) -> List[str]:
    with open(path, "r") as f:
        symbols = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return symbols


def run_portfolio_orb(
    symbols: List[str],
    start_date: str,
    end_date: str,
    top_n: int = 5,
    initial_equity: float = 100_000.0,
    risk_per_trade_frac: float = 0.01,
    commission_per_share: float = 0.0035,
    rvol_threshold: float = 1.0,
    atr_stop_pct: float = 0.10,
    output_dir: Path | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Simple multi-stock ORB portfolio backtest on a small universe.

    For each day in [start_date, end_date]:
      - Compute daily features and ORB trades per symbol.
      - Filter to symbols with or_rvol >= rvol_threshold.
      - Take top_n by or_rvol and keep their trades.

    NOTE: This is a simple prototype:
      - Uses the same initial_equity/risk_per_trade_frac per symbol run.
      - Does not strictly enforce a global leverage cap yet.
      - Supports checkpointing via progress.csv and per-symbol trade caching.
    """
    all_trades: List[pd.DataFrame] = []

    # --- Checkpointing: load existing progress and cached trades ---
    progress_path = None
    trades_cache_dir = None
    processed_symbols = set()
    
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        progress_path = output_dir / "progress.csv"
        trades_cache_dir = output_dir / "trades_cache"
        trades_cache_dir.mkdir(exist_ok=True)
        
        # Load progress file
        if progress_path.exists():
            try:
                df_prog = pd.read_csv(progress_path)
                if "symbol" in df_prog.columns:
                    processed_symbols = set(df_prog["symbol"].astype(str))
            except Exception as e:  # pragma: no cover - defensive; should be rare
                print(f"[WARN] Could not read existing progress file {progress_path}: {e}")
        
        # Load cached trades from previous run
        print(f"[INFO] Loading cached trades from {trades_cache_dir}...")
        cache_files = list(trades_cache_dir.glob("*.parquet"))
        if cache_files:
            print(f"[INFO] Found {len(cache_files)} cached trade files.")
            for cache_file in cache_files:
                try:
                    cached_trades = pd.read_parquet(cache_file)
                    if not cached_trades.empty:
                        all_trades.append(cached_trades)
                except Exception as e:
                    print(f"[WARN] Could not load {cache_file}: {e}")
        else:
            print(f"[INFO] No cached trades found (fresh start).")

    total_symbols = len(symbols)
    for idx, sym in enumerate(symbols, start=1):
        if sym in processed_symbols:
            print(f"[INFO] Skipping {sym} ({idx}/{total_symbols}): already processed (checkpoint).")
            continue

        print(f"[INFO] Running ORB for symbol {sym} ({idx}/{total_symbols})...")
        status = "ok"
        try:
            trades, _ = run_orb_single_symbol(
                symbol=sym,
                start_date=start_date,
                end_date=end_date,
                rvol_threshold=rvol_threshold,
                atr_stop_pct=atr_stop_pct,
                initial_equity=initial_equity,
                risk_per_trade_frac=risk_per_trade_frac,
                commission_per_share=commission_per_share,
            )
        except FileNotFoundError as e:
            print(f"[WARN] Skipping {sym}: {e}")
            trades = pd.DataFrame()
            status = "missing_data"

        if trades.empty and status == "ok":
            print(f"[INFO] No trades for {sym} in period {start_date} to {end_date}.")
        elif not trades.empty:
            print(f"[INFO] Completed {sym}: {len(trades)} trades.")
            all_trades.append(trades)
            
            # Cache trades immediately to disk
            if trades_cache_dir is not None:
                cache_file = trades_cache_dir / f"{sym}.parquet"
                try:
                    trades.to_parquet(cache_file, index=False)
                except Exception as e:
                    print(f"[WARN] Could not cache trades for {sym}: {e}")

        # Update progress file after handling this symbol
        if progress_path is not None:
            row = {
                "symbol": sym,
                "idx": idx,
                "status": status,
                "trades_count": int(len(trades)),
            }
            df_row = pd.DataFrame([row])
            if progress_path.exists():
                df_row.to_csv(progress_path, mode="a", header=False, index=False)
            else:
                df_row.to_csv(progress_path, index=False)

    if not all_trades:
        return pd.DataFrame(), pd.DataFrame()

    trades_df = pd.concat(all_trades, ignore_index=True)

    # Rank by RVOL per day and keep top_n
    if "or_rvol_14" in trades_df.columns:
        trades_df["rvol_rank"] = trades_df.groupby("date")["or_rvol_14"].rank(ascending=False, method="first")
        trades_df = trades_df[trades_df["rvol_rank"] <= top_n].copy()

    # Aggregate net PnL per day across all symbols
    if trades_df.empty:
        return trades_df, pd.DataFrame(columns=["date", "net_pnl", "equity"])

    daily_pnl = (
        trades_df
        .groupby("date")["net_pnl"]
        .sum()
        .reset_index()
        .sort_values("date")
    )

    # Build portfolio equity curve from initial_equity
    eq = initial_equity
    equities = []
    for _, r in daily_pnl.iterrows():
        eq += r["net_pnl"]
        equities.append(eq)
    daily_pnl["equity"] = equities

    # Clean up cache directory after successful completion
    if trades_cache_dir is not None and trades_cache_dir.exists():
        print(f"[INFO] Cleaning up trade cache directory...")
        try:
            import shutil
            shutil.rmtree(trades_cache_dir)
            print(f"[INFO] Trade cache removed (trades saved to portfolio_trades.csv).")
        except Exception as e:
            print(f"[WARN] Could not remove cache directory: {e}")

    return trades_df, daily_pnl


def compute_portfolio_metrics(
    trades: pd.DataFrame,
    daily_pnl: pd.DataFrame,
    initial_equity: float,
) -> Dict[str, float]:
    """Compute basic portfolio metrics.

    - cagr: annualized return based on start/end equity and period length.
    - max_drawdown: maximum peak-to-trough equity drop (in %).
    - profit_factor: gross_profit / gross_loss.
    - max_daily_risk: max total notional risk allocated in a single day (approx).
    - hit_rate: fraction of winning trades.
    """
    metrics: Dict[str, float] = {}

    if daily_pnl.empty:
        return metrics

    # CAGR-ish
    start_eq = initial_equity
    end_eq = float(daily_pnl["equity"].iloc[-1])
    start_date = pd.to_datetime(daily_pnl["date"].iloc[0])
    end_date = pd.to_datetime(daily_pnl["date"].iloc[-1])
    years = (end_date - start_date).days / 365.0 if (end_date > start_date) else 0.0

    if years > 0 and start_eq > 0:
        cagr = (end_eq / start_eq) ** (1.0 / years) - 1.0
    else:
        cagr = float("nan")
    metrics["cagr"] = cagr

    # Max drawdown (percentage)
    equity_series = daily_pnl["equity"].astype(float)
    roll_max = equity_series.cummax()
    drawdown = (equity_series - roll_max) / roll_max
    max_dd = drawdown.min()  # negative number
    metrics["max_drawdown"] = max_dd

    # Profit factor
    if not trades.empty and "net_pnl" in trades.columns:
        wins = trades["net_pnl"] > 0
        gross_profit = trades.loc[wins, "net_pnl"].sum()
        gross_loss = -trades.loc[~wins, "net_pnl"].sum()
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = float("inf") if gross_profit > 0 else float("nan")
    else:
        profit_factor = float("nan")
    metrics["profit_factor"] = profit_factor

    # Max daily risk (approx): sum of per-trade risk in a day
    # We approximate per-trade risk as |entry_price - stop_level| * shares
    # We do not currently store stop_level; approximate using atr_stop_pct * atr.
    if not trades.empty and "atr_14" in trades.columns and "shares" in trades.columns:
        # We don't have stop_level stored; approximate per-trade risk using atr_14 and default 10% stop.
        approx_risk_series = trades["atr_14"].abs() * trades["shares"].abs() * 0.10
        approx_risk_series.name = "approx_risk"
        temp = trades.copy()
        temp["approx_risk"] = approx_risk_series
        daily_risk = temp.groupby("date")["approx_risk"].sum()
        max_daily_risk = daily_risk.max()
    else:
        max_daily_risk = float("nan")
    metrics["max_daily_risk"] = float(max_daily_risk) if pd.notna(max_daily_risk) else float("nan")

    # Hit rate
    if not trades.empty and "net_pnl" in trades.columns:
        wins = (trades["net_pnl"] > 0).sum()
        total = len(trades)
        hit_rate = wins / total if total > 0 else float("nan")
    else:
        hit_rate = float("nan")
    metrics["hit_rate"] = hit_rate

    # Kelly-style fractions (per-trade risk as % of equity)
    # Approximate avg win / avg loss from net_pnl distribution.
    if not trades.empty and "net_pnl" in trades.columns:
        win_pnls = trades.loc[trades["net_pnl"] > 0, "net_pnl"]
        loss_pnls = trades.loc[trades["net_pnl"] < 0, "net_pnl"]
        if not win_pnls.empty and not loss_pnls.empty:
            avg_win = win_pnls.mean()
            avg_loss = -loss_pnls.mean()
            p = win_pnls.size / (win_pnls.size + loss_pnls.size)
            R = avg_win / avg_loss if avg_loss > 0 else float("nan")
            if R > 0:
                kelly_f = p - (1 - p) / R
            else:
                kelly_f = float("nan")
        else:
            kelly_f = float("nan")
    else:
        kelly_f = float("nan")

    # Express as percentages (0-100). Safe ~ 50% Kelly, danger ~ 200% Kelly.
    metrics["kelly_fraction_pct"] = kelly_f * 100 if pd.notna(kelly_f) else float("nan")
    metrics["safe_fraction_pct"] = (kelly_f * 0.5 * 100) if pd.notna(kelly_f) else float("nan")
    metrics["danger_fraction_pct"] = (kelly_f * 2.0 * 100) if pd.notna(kelly_f) else float("nan")

    return metrics


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run ORB portfolio backtest on a universe and save CSV results.")
    parser.add_argument("--universe", type=str, default="config/us_stocks_active.txt")
    parser.add_argument("--start", type=str, default="2021-01-04")
    parser.add_argument("--end", type=str, default="2021-12-31")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--initial-equity", type=float, default=100_000.0)
    parser.add_argument("--risk-per-trade-frac", type=float, default=0.01)
    parser.add_argument("--commission-per-share", type=float, default=0.0035)
    parser.add_argument("--rvol-threshold", type=float, default=1.0)
    parser.add_argument("--atr-stop-pct", type=float, default=0.10)
    parser.add_argument("--output-dir", type=str, default="results")

    args = parser.parse_args()

    universe_path = Path(args.universe)
    symbols = load_universe(universe_path)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trades, daily_pnl = run_portfolio_orb(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        top_n=args.top_n,
        initial_equity=args.initial_equity,
        risk_per_trade_frac=args.risk_per_trade_frac,
        commission_per_share=args.commission_per_share,
        rvol_threshold=args.rvol_threshold,
        atr_stop_pct=args.atr_stop_pct,
        output_dir=output_dir,
    )

    # ---- Save base CSVs ----
    if not trades.empty:
        trades.to_csv(output_dir / "portfolio_trades.csv", index=False)
    if not daily_pnl.empty:
        daily_pnl.to_csv(output_dir / "portfolio_daily_pnl.csv", index=False)

    # ---- Per-stock stats ----
    per_stock_rows = []
    if not trades.empty:
        for sym, df_sym in trades.groupby("symbol"):
            sym_trades = df_sym
            wins = sym_trades["net_pnl"] > 0
            gross_profit = sym_trades.loc[wins, "net_pnl"].sum()
            gross_loss = -sym_trades.loc[~wins, "net_pnl"].sum()
            total_trades = len(sym_trades)
            hit_rate = wins.sum() / total_trades if total_trades > 0 else float("nan")
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else float("nan"))
            net_pnl = sym_trades["net_pnl"].sum()

            per_stock_rows.append({
                "symbol": sym,
                "trades": total_trades,
                "net_pnl": net_pnl,
                "gross_profit": gross_profit,
                "gross_loss": -gross_loss,
                "hit_rate": hit_rate,
                "profit_factor": profit_factor,
            })

    per_stock_df = pd.DataFrame(per_stock_rows)
    if not per_stock_df.empty:
        per_stock_df.to_csv(output_dir / "portfolio_per_stock_stats.csv", index=False)

    # ---- Per-year stats (overall and per stock) ----
    per_year_rows = []
    if not trades.empty:
        trades_year = trades.copy()
        trades_year["year"] = pd.to_datetime(trades_year["date"]).dt.year

        for (year, sym), df_ys in trades_year.groupby(["year", "symbol"]):
            wins = df_ys["net_pnl"] > 0
            gross_profit = df_ys.loc[wins, "net_pnl"].sum()
            gross_loss = -df_ys.loc[~wins, "net_pnl"].sum()
            total_trades = len(df_ys)
            hit_rate = wins.sum() / total_trades if total_trades > 0 else float("nan")
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else float("nan"))
            net_pnl = df_ys["net_pnl"].sum()

            per_year_rows.append({
                "year": year,
                "symbol": sym,
                "trades": total_trades,
                "net_pnl": net_pnl,
                "gross_profit": gross_profit,
                "gross_loss": -gross_loss,
                "hit_rate": hit_rate,
                "profit_factor": profit_factor,
            })

    per_year_df = pd.DataFrame(per_year_rows)
    if not per_year_df.empty:
        per_year_df.to_csv(output_dir / "portfolio_per_year_per_stock_stats.csv", index=False)

    # Overall per-year based on daily equity, plus Kelly-style fractions per year
    per_year_overall_rows = []
    if not daily_pnl.empty:
        dp = daily_pnl.copy()
        dp["year"] = pd.to_datetime(dp["date"]).dt.year

        # If we have trades, pre-compute per-year Kelly-style metrics using the
        # same logic as compute_portfolio_metrics but per year.
        trades_year = None
        if not trades.empty and "date" in trades.columns:
            trades_year = trades.copy()
            trades_year["year"] = pd.to_datetime(trades_year["date"]).dt.year

        for year, df_y in dp.groupby("year"):
            start_eq = df_y["equity"].iloc[0]
            end_eq = df_y["equity"].iloc[-1]
            ret = (end_eq / start_eq - 1.0) if start_eq > 0 else float("nan")

            kelly_fraction_pct = float("nan")
            safe_fraction_pct = float("nan")
            danger_fraction_pct = float("nan")

            if trades_year is not None:
                subset = trades_year[trades_year["year"] == year]
                if not subset.empty and "net_pnl" in subset.columns:
                    win_pnls = subset.loc[subset["net_pnl"] > 0, "net_pnl"]
                    loss_pnls = subset.loc[subset["net_pnl"] < 0, "net_pnl"]
                    if not win_pnls.empty and not loss_pnls.empty:
                        avg_win = win_pnls.mean()
                        avg_loss = -loss_pnls.mean()
                        p = win_pnls.size / (win_pnls.size + loss_pnls.size)
                        R = avg_win / avg_loss if avg_loss > 0 else float("nan")
                        if R > 0:
                            kelly_f = p - (1 - p) / R
                        else:
                            kelly_f = float("nan")
                    else:
                        kelly_f = float("nan")

                    if pd.notna(kelly_f):
                        kelly_fraction_pct = kelly_f * 100
                        safe_fraction_pct = kelly_f * 0.5 * 100
                        danger_fraction_pct = kelly_f * 2.0 * 100

            per_year_overall_rows.append({
                "year": year,
                "start_equity": start_eq,
                "end_equity": end_eq,
                "return": ret,
                "kelly_fraction_pct": kelly_fraction_pct,
                "safe_fraction_pct": safe_fraction_pct,
                "danger_fraction_pct": danger_fraction_pct,
            })

    per_year_overall_df = pd.DataFrame(per_year_overall_rows)
    if not per_year_overall_df.empty:
        per_year_overall_df.to_csv(output_dir / "portfolio_per_year_overall_stats.csv", index=False)

    # Metrics (overall)
    metrics = compute_portfolio_metrics(trades, daily_pnl, initial_equity=args.initial_equity)
    print("\nPortfolio metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    # Write a simple text summary
    summary_path = output_dir / "summary.txt"
    with open(summary_path, "w") as f:
        f.write("ORB Portfolio Backtest Summary\n")
        f.write("=" * 40 + "\n\n")
        f.write(f"Universe file: {args.universe}\n")
        f.write(f"Start date: {args.start}\n")
        f.write(f"End date: {args.end}\n")
        f.write(f"Top N per day: {args.top_n}\n")
        f.write(f"Initial equity: {args.initial_equity}\n")
        f.write(f"Risk per trade frac: {args.risk_per_trade_frac}\n")
        f.write(f"Commission per share: {args.commission_per_share}\n")
        f.write(f"RVOL threshold: {args.rvol_threshold}\n")
        f.write(f"ATR stop pct: {args.atr_stop_pct}\n")
        f.write("\nKey metrics:\n")
        for k, v in metrics.items():
            f.write(f"  {k}: {v}\n")

        f.write("\nOutput files:\n")
        f.write(f"  Trades: {output_dir / 'portfolio_trades.csv'}\n")
        f.write(f"  Daily PnL: {output_dir / 'portfolio_daily_pnl.csv'}\n")
        f.write(f"  Per-stock stats: {output_dir / 'portfolio_per_stock_stats.csv'}\n")
        f.write(f"  Per-year per-stock stats: {output_dir / 'portfolio_per_year_per_stock_stats.csv'}\n")
        f.write(f"  Per-year overall stats: {output_dir / 'portfolio_per_year_overall_stats.csv'}\n")

