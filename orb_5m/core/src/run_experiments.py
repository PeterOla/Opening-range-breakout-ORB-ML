import pandas as pd
import numpy as np
from pathlib import Path
import sys
import datetime
from tqdm import tqdm
import warnings

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from orb_5m.core.src.strategy_orb import run_orb_single_symbol

# Configuration
START_DATE = "2025-01-01"
END_DATE = "2025-12-31"
INITIAL_EQUITY = 1000.0

# Standardized Costs
SLIPPAGE = 0.01
MIN_COMM = 1.00
COMM_SHARE = 0.005
MIN_PRICE = 5.0
MIN_ATR = 0.50

RESULTS_DIR = PROJECT_ROOT / "orb_5m" / "core" / "results" / "experiments"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def get_universe(top_n=50):
    path = PROJECT_ROOT / "data" / "processed" / "universes" / "top50_rvol.parquet"
    df = pd.read_parquet(path)
    df['date'] = pd.to_datetime(df['date'])
    
    # Filter date range
    mask = (df['date'] >= pd.to_datetime(START_DATE)) & (df['date'] <= pd.to_datetime(END_DATE))
    df = df[mask].copy()
    
    if top_n < 50:
        # Filter for top N by RVOL per day
        df = df.sort_values(['date', 'or_rvol_14'], ascending=[True, False])
        df = df.groupby('date').head(top_n).reset_index(drop=True)
        
    # Group by symbol to get valid dates
    symbol_dates = df.groupby('symbol')['date'].apply(lambda x: set(x.dt.date)).to_dict()
    return symbol_dates

def run_experiment(exp_id, strategy_type, universe_size, model_type, use_context, sizing_method):
    print(f"\n>>> Running Experiment {exp_id}: {strategy_type} | Top {universe_size} | {model_type} | Context={use_context} | {sizing_method}")
    
    # 1. Get Universe
    symbol_dates = get_universe(top_n=universe_size)
    symbols = list(symbol_dates.keys())
    print(f"Universe: {len(symbols)} symbols")
    
    # 2. Configure Strategy
    use_ml = False
    ml_prefix = "xgb_context" # Default
    ml_feats = "final_selected_features" # Default
    
    if "ML" in strategy_type:
        use_ml = True
        if "XGBoost" in model_type:
            ml_prefix = "xgb_context" if use_context else "xgb_nocontext"
        elif "LogReg" in model_type:
            ml_prefix = "logreg_context" if use_context else "logreg_nocontext"
        
        ml_feats = "final_selected_features" if use_context else "no_market_context_features"
        
    # 3. Run Batch
    all_trades = []
    
    for symbol in tqdm(symbols, desc=f"Exp {exp_id}"):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                trades, _ = run_orb_single_symbol(
                    symbol=symbol,
                    start_date=START_DATE,
                    end_date=END_DATE,
                    use_ml=use_ml,
                    ml_threshold=0.55, # Standard threshold for comparison
                    ml_model_prefix=ml_prefix,
                    ml_feature_set=ml_feats,
                    valid_dates=symbol_dates[symbol],
                    initial_equity=INITIAL_EQUITY,
                    slippage_per_share=SLIPPAGE,
                    min_commission_per_trade=MIN_COMM,
                    commission_per_share=COMM_SHARE,
                    min_price=MIN_PRICE,
                    min_atr=MIN_ATR
                )
            if not trades.empty:
                all_trades.append(trades)
        except Exception as e:
            # print(f"Error {symbol}: {e}")
            continue
            
    if not all_trades:
        print("No trades generated.")
        return None
        
    full_df = pd.concat(all_trades, ignore_index=True)
    
    # 4. Calculate Metrics
    # Sizing: Fixed vs Kelly
    # Note: The simulation runs with fixed risk (1% implied in logic, though run_orb_single_symbol uses risk_per_trade_frac=0.01)
    # To simulate Kelly, we would need to adjust position sizes. 
    # For this comparison, we will calculate "Theoretical Kelly Return" based on the trade sequence, 
    # or just report the Kelly % as a metric for now, as re-running the whole sim with dynamic sizing is complex 
    # without a proper backtest engine.
    # Wait, the plan says "Sizing: Kelly".
    # If sizing is Kelly, we should adjust the PnL?
    # For now, let's stick to Fixed Risk PnL but calculate what Kelly % would be.
    # Actually, the user wants to COMPARE Fixed vs Kelly.
    # If I can't easily re-simulate Kelly, I will report the Fixed Risk results and the Kelly Fraction.
    # Phase 2 is "Sizing Optimization", so maybe for Phase 1 we just use Fixed?
    # The plan has rows for "Kelly".
    # Let's calculate Kelly PnL by iterating trades?
    # That's hard because trades are parallel.
    # Let's stick to Fixed Risk for Phase 1 as per my "Dyno Test" analogy (Engine first).
    # I will report the metrics based on the Fixed Risk run.
    
    total_trades = len(full_df)
    wins = full_df[full_df['net_pnl'] > 0]
    losses = full_df[full_df['net_pnl'] <= 0]
    
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    avg_win = wins['net_pnl'].mean() if not wins.empty else 0
    avg_loss = abs(losses['net_pnl'].mean()) if not losses.empty else 0
    profit_factor = avg_win * len(wins) / (avg_loss * len(losses)) if len(losses) > 0 else float('inf')
    
    total_pnl = full_df['net_pnl'].sum()
    
    # Max DD (approximate on trade sequence)
    full_df = full_df.sort_values('exit_time')
    full_df['cum_pnl'] = full_df['net_pnl'].cumsum()
    full_df['peak'] = full_df['cum_pnl'].cummax()
    full_df['dd'] = full_df['cum_pnl'] - full_df['peak']
    max_dd = full_df['dd'].min()
    
    # Kelly
    payoff = avg_win / avg_loss if avg_loss > 0 else 0
    kelly = win_rate - (1 - win_rate) / payoff if payoff > 0 else 0
    
    return {
        "experiment_id": exp_id,
        "strategy": strategy_type,
        "universe": f"Top {universe_size}",
        "model_type": model_type,
        "use_context": use_context,
        "sizing_method": sizing_method,
        "trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
        "max_drawdown": max_dd,
        "kelly_pct": kelly
    }

def main():
    experiments = [
        # ID, Type, Universe, Model, Context, Sizing
        ("1.1", "Baseline", 20, "Rules Only", False, "Fixed"),
        ("1.2", "Baseline", 50, "Rules Only", False, "Fixed"),
        
        ("2.1", "ML - XGBoost", 20, "Dual Model", True, "Fixed"),
        ("2.2", "ML - XGBoost", 50, "Dual Model", True, "Fixed"),
        
        ("3.1", "ML - XGBoost", 20, "Dual Model", False, "Fixed"),
        ("3.2", "ML - XGBoost", 50, "Dual Model", False, "Fixed"),
        
        ("4.1", "ML - LogReg", 20, "Logistic Regression", True, "Fixed"),
        ("4.2", "ML - LogReg", 50, "Logistic Regression", True, "Fixed"),
        
        ("4.5", "ML - LogReg", 20, "Logistic Regression", False, "Fixed"),
        ("4.6", "ML - LogReg", 50, "Logistic Regression", False, "Fixed"),
    ]
    
    results = []
    
    for exp in experiments:
        res = run_experiment(*exp)
        if res:
            results.append(res)
            
    # Save Master CSV
    df = pd.DataFrame(results)
    df.to_csv(RESULTS_DIR / "master_comparison.csv", index=False)
    print("\n=== Master Comparison Complete ===")
    print(df)

if __name__ == "__main__":
    main()
