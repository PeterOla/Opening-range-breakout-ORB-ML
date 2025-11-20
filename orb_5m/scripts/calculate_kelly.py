"""Calculate Kelly criterion for combined backtest results."""
import pandas as pd
from pathlib import Path

def calculate_kelly(trades_df):
    """Calculate Kelly fraction and related metrics."""
    if trades_df.empty or "net_pnl" not in trades_df.columns:
        return None
    
    # Split winners and losers
    win_pnls = trades_df.loc[trades_df["net_pnl"] > 0, "net_pnl"]
    loss_pnls = trades_df.loc[trades_df["net_pnl"] < 0, "net_pnl"]
    
    if win_pnls.empty or loss_pnls.empty:
        return None
    
    # Calculate metrics
    avg_win = win_pnls.mean()
    avg_loss = -loss_pnls.mean()  # Make positive
    p = len(win_pnls) / len(trades_df)  # Win rate
    R = avg_win / avg_loss if avg_loss > 0 else float("nan")
    
    # Kelly formula: f* = p - (1-p)/R
    if R > 0:
        kelly_f = p - (1 - p) / R
    else:
        kelly_f = float("nan")
    
    # Express as percentages
    kelly_pct = kelly_f * 100 if pd.notna(kelly_f) else float("nan")
    safe_pct = (kelly_f * 0.5 * 100) if pd.notna(kelly_f) else float("nan")  # Half Kelly
    danger_pct = (kelly_f * 2.0 * 100) if pd.notna(kelly_f) else float("nan")  # 2x Kelly
    
    return {
        "win_rate": p,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": R,
        "kelly_fraction": kelly_f,
        "kelly_pct": kelly_pct,
        "safe_pct": safe_pct,
        "danger_pct": danger_pct,
        "current_risk_pct": 1.0,  # We use 1% per trade
        "kelly_multiplier": 1.0 / kelly_f if pd.notna(kelly_f) and kelly_f > 0 else float("nan")
    }


if __name__ == "__main__":
    # Load combined trades
    results_dir = Path(__file__).parent.parent / "results" / "results_combined_top20"
    trades_path = results_dir / "all_trades.csv"
    trades = pd.read_csv(trades_path)
    
    print("=" * 60)
    print("KELLY CRITERION ANALYSIS")
    print("=" * 60)
    
    # Calculate Kelly
    kelly_results = calculate_kelly(trades)
    
    if kelly_results:
        print(f"\nWin Rate: {kelly_results['win_rate']*100:.2f}%")
        print(f"Average Win: ${kelly_results['avg_win']:.2f}")
        print(f"Average Loss: ${kelly_results['avg_loss']:.2f}")
        print(f"Win/Loss Ratio: {kelly_results['win_loss_ratio']:.2f}")
        print(f"\n{'─'*60}")
        print(f"Kelly Fraction: {kelly_results['kelly_fraction']:.4f}")
        print(f"Kelly %: {kelly_results['kelly_pct']:.2f}%")
        print(f"Safe (1/2 Kelly): {kelly_results['safe_pct']:.2f}%")
        print(f"Aggressive (2x Kelly): {kelly_results['danger_pct']:.2f}%")
        print(f"\n{'─'*60}")
        print(f"Current Risk per Trade: {kelly_results['current_risk_pct']:.2f}%")
        print(f"Kelly Multiplier: {kelly_results['kelly_multiplier']:.2f}x Kelly")
        print(f"\n{'─'*60}")
        
        if kelly_results['kelly_pct'] < 0:
            print("⚠️  NEGATIVE KELLY - Strategy has negative expectancy!")
        elif kelly_results['current_risk_pct'] > kelly_results['kelly_pct']:
            print(f"⚠️  OVER-LEVERAGED: Using {kelly_results['kelly_multiplier']:.1f}x Kelly")
            print(f"   Recommended: Reduce risk to {kelly_results['kelly_pct']:.2f}%")
        elif kelly_results['current_risk_pct'] < kelly_results['safe_pct']:
            print(f"✅ CONSERVATIVE: Using {kelly_results['current_risk_pct']/kelly_results['kelly_pct']*100:.0f}% of Kelly")
        else:
            print(f"✅ MODERATE: Between 1/2 Kelly and Full Kelly")
    else:
        print("Unable to calculate Kelly - insufficient data")
    
    print("=" * 60)
