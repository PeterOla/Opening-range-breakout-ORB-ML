import pandas as pd
import numpy as np
from pathlib import Path
import sys
import glob

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

RESULTS_DIR = PROJECT_ROOT / "orb_5m" / "core" / "results" / "experiments"
TRADES_DIR = RESULTS_DIR / "trades"
OUTPUT_FILE = RESULTS_DIR / "master_comparison_kelly.csv"

# Config
ATR_STOP_PCT = 0.10
INITIAL_EQUITY = 1000.0
MIN_COMM = 1.0
COMM_SHARE = 0.005

def get_kelly_parameters(df):
    """Calculate Kelly % based on realized R-multiples."""
    # Risk per share = |Entry - Stop|
    # Stop is OR High (for Short) or OR Low (for Long)
    df['stop_price'] = np.where(df['direction'] == 1, df['or_low'], df['or_high'])
    df['risk_per_share'] = abs(df['entry_price'] - df['stop_price'])
    
    # Filter invalid risk (e.g. 0)
    valid_trades = df[df['risk_per_share'] > 0.001].copy()
    
    if len(valid_trades) == 0:
        return 0.0, 0.0, 0.0, 0.0

    # Calculate Actual R realized on the trade
    # R = Net PnL / (Risk Per Share * Shares)
    valid_trades['risk_dollars_actual'] = valid_trades['risk_per_share'] * valid_trades['shares']
    valid_trades['R_multiple'] = valid_trades['net_pnl'] / valid_trades['risk_dollars_actual']

    wins = valid_trades[valid_trades['R_multiple'] > 0]
    losses = valid_trades[valid_trades['R_multiple'] <= 0]
    
    if len(losses) == 0:
        return 0.99, 1.0, 0.0, 999.0 # Infinite Kelly, cap at 99%

    win_rate = len(wins) / len(valid_trades)
    avg_win_R = wins['R_multiple'].mean()
    avg_loss_R = abs(losses['R_multiple'].mean())
    
    payoff = avg_win_R / avg_loss_R if avg_loss_R > 0 else 0
    
    # Kelly Formula: K = W - (1-W)/R
    kelly_fraction = win_rate - (1 - win_rate) / payoff if payoff > 0 else 0
    
    return kelly_fraction, win_rate, payoff, avg_loss_R

def run_simulation_for_file(file_path):
    exp_id = file_path.stem.replace("trades_exp_", "")
    print(f"Processing Exp {exp_id}...")
    
    df = pd.read_csv(file_path)
    if df.empty:
        return None
        
    df['entry_time'] = pd.to_datetime(df['entry_time'], utc=True)
    df = df.sort_values('entry_time')
    
    # 1. Calculate Kelly for this specific experiment
    kelly_pct, win_rate, payoff, avg_loss_R = get_kelly_parameters(df)
    
    # Cap Kelly for sanity (e.g. max 25%)? User said "Run Kelly", so we use raw, but maybe cap at 0.50 to prevent instant suicide on error.
    # Let's cap at 0.30 (30%) to be "realistic aggressive".
    # kelly_pct = min(kelly_pct, 0.30) 
    
    if kelly_pct <= 0:
        print(f"  -> Kelly <= 0 ({kelly_pct:.2%}). Skipping simulation.")
        return {
            "experiment_id": exp_id,
            "kelly_pct": kelly_pct,
            "total_pnl": 0,
            "final_equity": INITIAL_EQUITY,
            "max_drawdown": 0,
            "status": "Skipped (No Edge)"
        }

    print(f"  -> Kelly: {kelly_pct:.2%} (WR: {win_rate:.1%}, Payoff: {payoff:.2f})")

    # 2. Simulate
    equity = INITIAL_EQUITY
    equity_curve = [equity]
    busted = False
    
    for idx, row in df.iterrows():
        atr = row['atr_14']
        risk_per_share = atr * ATR_STOP_PCT
        
        # Bet Size
        risk_dollars = equity * kelly_pct
        
        if risk_per_share > 0.001:
            shares = int(risk_dollars / risk_per_share)
        else:
            shares = 0
            
        if shares < 1:
            shares = 0
            
        # PnL
        pnl_per_share = row['pnl_per_share']
        gross_pnl = shares * pnl_per_share
        comm = max(MIN_COMM, COMM_SHARE * shares) * 2
        if shares == 0: comm = 0
            
        net_pnl = gross_pnl - comm
        equity += net_pnl
        equity_curve.append(equity)
        
        if equity < 50: # Bust threshold
            print(f"  -> BUSTED at trade {idx+1}/{len(df)}")
            busted = True
            break
            
    final_equity = equity
    total_pnl = final_equity - INITIAL_EQUITY
    
    # Max DD
    curve = pd.Series(equity_curve)
    peak = curve.cummax()
    dd = curve - peak
    max_dd = dd.min()
    
    return {
        "experiment_id": exp_id,
        "kelly_pct": kelly_pct,
        "win_rate": win_rate,
        "payoff": payoff,
        "total_pnl": total_pnl,
        "final_equity": final_equity,
        "return_pct": (total_pnl / INITIAL_EQUITY),
        "max_drawdown": max_dd,
        "trades_count": len(df),
        "status": "Busted" if busted else "Survived"
    }

def run_kelly_simulation():
    # Find all trade files
    files = list(TRADES_DIR.glob("trades_exp_*.csv"))
    results = []
    
    print(f"Found {len(files)} experiment files.")
    
    for f in files:
        res = run_simulation_for_file(f)
        if res:
            results.append(res)
            
    # Save
    if results:
        res_df = pd.DataFrame(results)
        # Sort by ID
        res_df = res_df.sort_values("experiment_id")
        
        # Reorder columns
        cols = ["experiment_id", "status", "kelly_pct", "return_pct", "final_equity", "total_pnl", "max_drawdown", "win_rate", "payoff", "trades_count"]
        res_df = res_df[cols]
        
        res_df.to_csv(OUTPUT_FILE, index=False)
        print(f"\n=== Kelly Simulation Complete ===")
        print(f"Saved to {OUTPUT_FILE}")
        print(res_df)
    else:
        print("No results generated.")

if __name__ == "__main__":
    run_kelly_simulation()
