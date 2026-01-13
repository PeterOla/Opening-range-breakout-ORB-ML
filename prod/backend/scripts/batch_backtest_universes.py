import subprocess
import sys
import pandas as pd
from pathlib import Path
import re

# Configuration
PYTHON_EXE = sys.executable
SCRIPT_PATH = "prod/backend/scripts/ORB/fast_backtest.py"
DATA_DIR = Path("data/backtest/orb/runs/compound")
UNIVERSES = [
    ("universe_micro_small.parquet", "Micro+Small"),
    ("universe_micro_small_unknown.parquet", "Micro+Small+Unknown"),
    ("universe_micro.parquet", "Micro Cap"),
    ("universe_small.parquet", "Small Cap"),
    ("universe_micro_unknown.parquet", "Micro+Unknown"),
]

PARAMS = [
    "--side", "long",
    "--top-n", "10",
    "--initial-capital", "1583.81",
]

def run_backtest(universe_file, label):
    run_name = f"batch_long_top10_{label.lower().replace(' ', '_').replace('+', '_')}"
    print(f"\n{'='*60}")
    print(f"Running Backtest (Top 10): {label} ({universe_file})")
    print(f"{'='*60}")
    
    cmd = [
        PYTHON_EXE, SCRIPT_PATH,
        "--universe", universe_file,
        "--run-name", run_name,
    ] + PARAMS
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("Errors:", result.stderr)
        
    # Extract Final Equity from stdout as fallback
    final_equity = 0.0
    match = re.search(r"Final Equity: \$([\d,]+\.\d{2})", result.stdout)
    if match:
        final_equity = float(match.group(1).replace(",", ""))
        
    return {
        "Universe": label,
        "Run Name": run_name,
        "Final Equity": final_equity,
        "Return Multiple": final_equity / 1583.81
    }

def main():
    results = []
    print("Starting Batch Backtest Sequence...")
    
    for u_file, label in UNIVERSES:
        res = run_backtest(u_file, label)
        results.append(res)
        
    print("\n\n" + "="*80)
    print("BATCH BACKTEST SUMMARY (Long Only, Compounding, Start $1,583.81)")
    print("="*80)
    
    df = pd.DataFrame(results)
    df["Net Profit"] = df["Final Equity"] - 1583.81
    df["CAGR (Approx)"] = df["Return Multiple"] ** (1/5) - 1 # Approx 5 years
    
    # Formatting
    pd.options.display.float_format = '{:,.2f}'.format
    print(df[["Universe", "Final Equity", "Net Profit", "Return Multiple"]].to_string(index=False))
    
    print("\nWinner: " + df.loc[df["Final Equity"].idxmax()]["Universe"])

if __name__ == "__main__":
    main()
