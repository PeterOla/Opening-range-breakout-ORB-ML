"""
Run independent optimization experiments to reduce drawdown.
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path
import warnings

# Suppress pandas copysettings warnings if any
warnings.filterwarnings('ignore')

# Add backend root to path so we can import scripts
sys.path.insert(0, ".")

from scripts.ORB.fast_backtest import run_strategy, INITIAL_CAPITAL
from scripts.ORB.analyse_run import write_run_summary_md

# Paths
DATA_DIR = Path(__file__).resolve().parents[4] / "data"
UNIVERSE_PATH = DATA_DIR / "backtest" / "orb" / "universe" / "universe_micro_small.parquet"
REGIME_FILE = DATA_DIR / "spy_regime.parquet"
OUTPUT_ROOT = DATA_DIR / "backtest" / "orb" / "runs"

def calculate_max_drawdown(equity_df):
    if 'equity' not in equity_df.columns:
        return 0.0
    equity = equity_df['equity']
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    return drawdown.min() * 100

def print_table(results):
    # Simple table printer
    headers = ["Experiment", "Profit ($)", "Return (%)", "Max DD (%)", "Final Equity"]
    print(f"{headers[0]:<20} | {headers[1]:<15} | {headers[2]:<12} | {headers[3]:<12} | {headers[4]:<15}")
    print("-" * 80)
    for r in results:
        print(f"{r['Experiment']:<20} | {r['Profit ($)']:<15} | {r['Return (%)']:<12} | {r['Max DD (%)']:<12} | {r['Final Equity']:<15}")

def run_experiments():
    # Define experiments
    # Name -> params dict
    experiments = {
        "ZeroComm_Audit_Top5_ATR0.05": {
            "top_n": 5, 
            "initial_capital": 1500.0, 
            "leverage": 6.0,
            "max_share_cap": None, 
            "stop_atr_scale": 0.05, 
            "risk_per_trade": 0.10,
            "comm_share": 0.0,
            "comm_min": 0.0,
            "description": "AUDIT: Top 5, 0.05 ATR, Zero Fees (The Winner)"
        },
        "ZeroComm_Audit_Top5_ATR0.10": {
            "top_n": 5, 
            "initial_capital": 1500.0, 
            "leverage": 6.0,
            "max_share_cap": None, 
            "stop_atr_scale": 0.10, 
            "risk_per_trade": 0.10,
            "comm_share": 0.0,
            "comm_min": 0.0,
            "description": "AUDIT: Top 5, 0.10 ATR, Zero Fees (The Logic Check)"
        }
    }

    results = []

    print(f"Using Universe: {UNIVERSE_PATH}")
    if not UNIVERSE_PATH.exists():
        print(f"Error: Universe file not found: {UNIVERSE_PATH}")
        return

    for name, params in experiments.items():
        print(f"\n{'='*60}")
        print(f"Running Experiment: {name}")
        print(f"Description: {params.get('description')}")
        print(f"Params: {params}")
        print(f"{'='*60}\n")
        
        run_name = f"opt_{name}"
        
        # Run Strategy
        run_strategy(
            universe_path=UNIVERSE_PATH,
            min_atr=0.5,
            min_volume=100_000, 
            side_filter="long",
            run_name=run_name,
            compound=True,
            verbose=False,
            # Experiment params
            top_n=params.get("top_n"),
            initial_capital=params.get("initial_capital"),
            leverage=params.get("leverage"),
            stop_atr_scale=params.get("stop_atr_scale"),
            max_share_cap=params.get("max_share_cap"),
            risk_per_trade=params.get("risk_per_trade"),
            comm_share=params.get("comm_share", 0.005),
            comm_min=params.get("comm_min", 0.99),
            
            # Constants for now
            regime_file=None,
            dow_filter=None,
            risk_scale=1.0, 
            spread_pct=0.001,
            free_exits=True, 
        )
        
        # Analyze Results
        # fast_backtest.py adds 'compound' or 'fixed' subdir
        run_dir = OUTPUT_ROOT / "compound" / run_name
        equity_path = run_dir / "equity_curve.parquet"
        
        # Generate Markdown Summary
        print(f"Generating summary for {run_name} in {run_dir}")
        try:
            write_run_summary_md(run_dir)
        except Exception as e:
            print(f"Error generating summary: {e}")

        if equity_path.exists():
            df_eq = pd.read_parquet(equity_path)
            
            init_cap = params.get("initial_capital")
            final_equity = df_eq['equity'].iloc[-1]
            profit = final_equity - init_cap
            total_ret = (profit / init_cap) * 100
            max_dd = calculate_max_drawdown(df_eq)
            
            results.append({
                "Experiment": name,
                "Profit ($)": f"${profit:,.0f}",
                "Return (%)": f"{total_ret:,.0f}%",
                "Max DD (%)": f"{max_dd:.2f}%",
                "Final Equity": f"${final_equity:,.0f}"
            })
        else:
             results.append({"Experiment": name, "Profit ($)": "Error", "Return (%)": "0%", "Max DD (%)": "0%", "Final Equity": "0"})

    print("\n\n" + "="*80)
    print("OPTIMIZATION RESULTS SUMMARY")
    print("="*80)
    print_table(results)

if __name__ == "__main__":
    run_experiments()
