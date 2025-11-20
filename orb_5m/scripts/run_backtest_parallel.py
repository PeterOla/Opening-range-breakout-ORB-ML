"""Run complete ORB backtest with multiprocessing (parallel years)"""
import sys
import pandas as pd
from pathlib import Path
from multiprocessing import Pool

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.portfolio_orb import run_portfolio_orb, load_universe, compute_portfolio_metrics

# Configuration
SYMBOL_FILE = Path(__file__).parent.parent / "config" / "us_stocks_active.txt"
YEARS = [2021, 2022, 2023, 2024, 2025]
TOP_N = 20
INITIAL_EQUITY = 1_000.0  # Base equity for backtest
RISK_PER_TRADE = 0.01
COMMISSION = 0.0035
RVOL_THRESHOLD = 1.0
ATR_STOP_PCT = 0.10

symbols = load_universe(SYMBOL_FILE)
print(f"Loaded {len(symbols)} symbols from {SYMBOL_FILE}")


def run_year(year):
    """Run one year backtest (for parallel execution)"""
    print(f"\n[{year}] Starting backtest with ${INITIAL_EQUITY:,.0f}...")
    
    output_dir = Path(__file__).parent.parent / "results" / f"results_{year}_top{TOP_N}"
    output_dir.mkdir(exist_ok=True, parents=True)
    
    trades, daily_pnl = run_portfolio_orb(
        symbols=symbols,
        start_date=f"{year}-01-01",
        end_date=f"{year}-12-31",
        top_n=TOP_N,
        initial_equity=INITIAL_EQUITY,
        risk_per_trade_frac=RISK_PER_TRADE,
        commission_per_share=COMMISSION,
        rvol_threshold=RVOL_THRESHOLD,
        atr_stop_pct=ATR_STOP_PCT,
        output_dir=output_dir,
    )
    
    # Save results
    trades.to_csv(output_dir / "portfolio_trades.csv", index=False)
    daily_pnl.to_csv(output_dir / "portfolio_daily_pnl.csv", index=False)
    
    # Compute metrics
    metrics = compute_portfolio_metrics(trades, daily_pnl, initial_equity=INITIAL_EQUITY)
    final_equity = float(daily_pnl["equity"].iloc[-1]) if not daily_pnl.empty else INITIAL_EQUITY
    total_return = (final_equity / INITIAL_EQUITY) - 1.0
    
    # Write summary
    with open(output_dir / "summary.txt", "w") as f:
        f.write(f"=== {year} Portfolio Summary ===\n\n")
        f.write(f"Initial equity: ${INITIAL_EQUITY:,.2f}\n")
        f.write(f"Final equity: ${final_equity:,.2f}\n")
        f.write(f"Total return: {total_return:.2%}\n")
        f.write(f"Number of trades: {len(trades)}\n")
        f.write(f"Win rate: {metrics.get('hit_rate', 0.0):.2%}\n")
        f.write(f"Profit factor: {metrics.get('profit_factor', 0.0):.2f}\n")
        f.write(f"Max drawdown: {metrics.get('max_drawdown', 0.0):.2%}\n")
        f.write(f"CAGR: {metrics.get('cagr', 0.0):.2%}\n")
    
    print(f"[{year}] Complete: {len(trades)} trades, ${final_equity:,.2f} (+{total_return:.1%})")
    return year, trades, daily_pnl


# ============================================================================
# Run all years in PARALLEL
# ============================================================================
print("\n" + "="*80)
print(f"RUNNING {len(YEARS)} YEARS IN PARALLEL (BASE EQUITY: ${INITIAL_EQUITY:,.0f})")
print("="*80)

if __name__ == "__main__":
    # Run years in parallel
    with Pool(processes=len(YEARS)) as pool:
        results = pool.map(run_year, YEARS)
    
    print("\n" + "="*80)
    print("COMBINING RESULTS")
    print("="*80)
    
    # Combine all years
    all_trades = []
    all_daily_pnl = []
    
    for year, trades, daily_pnl in sorted(results, key=lambda x: x[0]):
        all_trades.append(trades)
        all_daily_pnl.append(daily_pnl)
        print(f"  {year}: {len(trades):,} trades")
    
    combined_trades = pd.concat(all_trades, ignore_index=True)
    
    # Recalculate combined daily P&L and equity from scratch
    # (each year's daily_pnl has equity starting from $1k, so we can't just concat)
    combined_daily = (
        combined_trades
        .groupby("date")["net_pnl"]
        .sum()
        .reset_index()
        .sort_values("date")
    )
    
    # Build proper equity curve from INITIAL_EQUITY
    eq = INITIAL_EQUITY
    equities = []
    for _, r in combined_daily.iterrows():
        eq += r["net_pnl"]
        equities.append(eq)
    combined_daily["equity"] = equities
    
    # Save combined results
    combined_dir = Path(__file__).parent.parent / "results" / "results_combined_top20"
    combined_dir.mkdir(exist_ok=True, parents=True)
    
    combined_trades.to_csv(combined_dir / "all_trades.csv", index=False)
    combined_daily.to_csv(combined_dir / "all_daily_pnl.csv", index=False)
    
    # Combined metrics
    total_pnl = combined_trades['net_pnl'].sum()
    final_equity = INITIAL_EQUITY + total_pnl
    total_return = total_pnl / INITIAL_EQUITY
    
    # Compute combined metrics
    metrics = compute_portfolio_metrics(combined_trades, combined_daily, initial_equity=INITIAL_EQUITY)
    
    with open(combined_dir / "summary.txt", "w") as f:
        f.write("=== Combined Portfolio Summary (2021-2025) ===\n\n")
        f.write(f"Period: 2021-01-01 to 2025-12-31\n")
        f.write(f"Initial equity: ${INITIAL_EQUITY:,.2f}\n")
        f.write(f"Final equity: ${final_equity:,.2f}\n")
        f.write(f"Total return: {total_return:.2%}\n")
        f.write(f"Total trades: {len(combined_trades):,}\n")
        f.write(f"Win rate: {metrics.get('hit_rate', 0.0):.2%}\n")
        f.write(f"Profit factor: {metrics.get('profit_factor', 0.0):.2f}\n")
        f.write(f"Max drawdown: {metrics.get('max_drawdown', 0.0):.2%}\n")
        f.write(f"CAGR: {metrics.get('cagr', 0.0):.2%}\n")
    
    print("\n" + "="*80)
    print("BACKTEST COMPLETE")
    print("="*80)
    print(f"Total trades: {len(combined_trades):,}")
    print(f"Total P&L: ${total_pnl:,.2f}")
    print(f"Final equity: ${final_equity:,.2f} (+{total_return:.1%})")
    print(f"\nResults saved to results_YYYY_top20/ and results_combined_top20/")
