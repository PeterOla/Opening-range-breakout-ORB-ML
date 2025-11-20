"""Compute alpha and beta vs SPY benchmark."""
import pandas as pd
import numpy as np
from scipy import stats
from pathlib import Path
import yfinance as yf


def compute_alpha_beta(daily_pnl_path: str, output_path: str | None = None):
    """Compute alpha and beta vs SPY.
    
    Args:
        daily_pnl_path: Path to all_daily_pnl.csv
        output_path: Optional path to save results
    """
    # Load strategy returns
    df = pd.read_csv(daily_pnl_path, parse_dates=['date'])
    df = df.sort_values('date').reset_index(drop=True)
    
    # Compute daily returns
    df['equity_pct_return'] = df['equity'].pct_change()
    df = df.dropna(subset=['equity_pct_return'])
    
    # Get SPY data for the same period
    start_date = df['date'].min()
    end_date = df['date'].max()
    
    print(f"Fetching SPY data from {start_date.date()} to {end_date.date()}...")
    spy = yf.download('SPY', start=start_date, end=end_date, progress=False)
    
    if spy.empty:
        print("⚠ Warning: Failed to fetch SPY data")
        return None
    
    # Compute SPY daily returns
    spy = spy.reset_index()
    
    # Handle multi-index columns from yfinance
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    
    # Lowercase column names
    spy.columns = [col.lower() if isinstance(col, str) else col for col in spy.columns]
    
    # Use 'Close' or 'close' depending on yfinance version
    close_col = 'close' if 'close' in spy.columns else 'Close'
    date_col = 'date' if 'date' in spy.columns else 'Date'
    
    spy['spy_return'] = spy[close_col].pct_change()
    spy = spy[[date_col, 'spy_return']].dropna()
    spy.rename(columns={date_col: 'date'}, inplace=True)
    
    # Merge strategy and benchmark returns
    merged = pd.merge(df[['date', 'equity_pct_return']], 
                     spy[['date', 'spy_return']],
                     on='date', how='inner')
    
    if len(merged) < 30:
        print(f"⚠ Warning: Only {len(merged)} overlapping days. Need at least 30 for reliable regression.")
        return None
    
    # Regression: strategy_return = alpha + beta * spy_return
    X = merged['spy_return'].values
    y = merged['equity_pct_return'].values
    
    slope, intercept, r_value, p_value, std_err = stats.linregress(X, y)
    
    # Annualize alpha (daily alpha * 252)
    alpha_annual = intercept * 252
    beta = slope
    r_squared = r_value ** 2
    
    # Print results
    print("\n" + "="*80)
    print("ALPHA & BETA vs SPY")
    print("="*80)
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Overlapping days: {len(merged)}")
    print(f"\nBeta: {beta:.4f}")
    print(f"Alpha (annualized): {alpha_annual:.4f} ({alpha_annual*100:.2f}%)")
    print(f"R²: {r_squared:.4f}")
    print(f"P-value: {p_value:.6f}")
    print("="*80)
    
    # Interpretation
    print("\nInterpretation:")
    if beta < 0.5:
        print(f"  • Beta = {beta:.2f}: Strategy has LOW correlation with SPY (market-neutral)")
    elif beta < 1.0:
        print(f"  • Beta = {beta:.2f}: Strategy has MODERATE correlation with SPY")
    elif beta < 1.5:
        print(f"  • Beta = {beta:.2f}: Strategy moves WITH SPY (market-directional)")
    else:
        print(f"  • Beta = {beta:.2f}: Strategy is HIGHLY sensitive to SPY moves")
    
    if alpha_annual > 0.1:
        print(f"  • Alpha = {alpha_annual*100:.1f}%: Strong outperformance vs SPY (after adjusting for beta)")
    elif alpha_annual > 0:
        print(f"  • Alpha = {alpha_annual*100:.1f}%: Positive outperformance vs SPY")
    else:
        print(f"  • Alpha = {alpha_annual*100:.1f}%: Underperformance vs SPY (after beta adjustment)")
    
    # Save to file if requested
    if output_path:
        results = {
            'period_start': start_date.date().isoformat(),
            'period_end': end_date.date().isoformat(),
            'n_days': len(merged),
            'beta': beta,
            'alpha_annualized': alpha_annual,
            'alpha_pct': alpha_annual * 100,
            'r_squared': r_squared,
            'p_value': p_value,
        }
        
        pd.DataFrame([results]).to_csv(output_path, index=False)
        print(f"\n✓ Alpha/Beta results saved to: {output_path}")
    
    return {
        'beta': beta,
        'alpha_annual': alpha_annual,
        'r_squared': r_squared,
        'n_days': len(merged)
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Compute alpha and beta vs SPY")
    parser.add_argument("--daily-pnl", type=str,
                       default="results_combined_top20/all_daily_pnl.csv",
                       help="Path to all_daily_pnl.csv")
    parser.add_argument("--output", type=str,
                       default="results_combined_top20/alpha_beta_spy.csv",
                       help="Path to save results CSV")
    
    args = parser.parse_args()
    
    compute_alpha_beta(args.daily_pnl, args.output)
