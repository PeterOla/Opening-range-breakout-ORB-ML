import pandas as pd
import numpy as np
from pathlib import Path
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

TRADES_DIR = PROJECT_ROOT / "orb_5m" / "core" / "results" / "experiments" / "trades"
OUTPUT_DIR = PROJECT_ROOT / "orb_5m" / "core" / "results" / "brokers"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Simulation Config
STARTING_CAPITAL = 1000.0
ATR_STOP_PCT = 0.10

# Broker Profiles
BROKERS = {
    "Pro (IBKR)": {
        "comm_share": 0.005,
        "min_comm": 1.00,
        "slippage": 0.01, # per share per side
        "fixed_fee": 0.00
    },
    "Alpaca (Free)": {
        "comm_share": 0.00,
        "min_comm": 0.00,
        "slippage": 0.02, # PFOF / Worse execution than Pro, better than RH?
        "fixed_fee": 0.00
    },
    "Retail (Robinhood)": {
        "comm_share": 0.00,
        "min_comm": 0.00,
        "slippage": 0.03, # Worse execution (payment for order flow)
        "fixed_fee": 0.00
    },
    "Prop Firm": {
        "comm_share": 0.00, # Often raw spread or included
        "min_comm": 0.00,
        "slippage": 0.01, # Good execution
        "fixed_fee": 2.00 # Ticket charge per trade? Or just commissions. Let's assume $2 flat.
    }
}

def simulate_broker(df, broker_name, params, risk_pct):
    equity = STARTING_CAPITAL
    equity_curve = [equity]
    
    comm_share = params['comm_share']
    min_comm = params['min_comm']
    slippage = params['slippage']
    fixed_fee = params['fixed_fee']
    
    # Original data has 0.01 slippage baked into prices?
    # We need to reconstruct "Raw Price" to apply new slippage.
    # CSV: entry_price (with 0.01 slip), exit_price (with 0.01 slip)
    # Raw Entry (Long) = CSV_Entry - 0.01
    # Raw Exit (Long) = CSV_Exit + 0.01
    # New Entry (Long) = Raw_Entry + New_Slip
    # Net Change per share = (New_Slip - 0.01) * 2 (Entry+Exit)
    
    # Delta Slippage Cost per share (vs the CSV baseline of 0.01)
    # If New Slip is 0.03, Delta is 0.02. Total impact 0.04 per share round trip.
    slip_delta = slippage - 0.01
    slip_cost_per_share_round_trip = slip_delta * 2
    
    trades_log = []
    
    for idx, row in df.iterrows():
        # 1. Sizing (Dynamic Risk)
        atr = row['atr_14']
        risk_per_share = atr * ATR_STOP_PCT
        
        risk_dollars = equity * risk_pct
        
        if risk_per_share > 0.001:
            shares = int(risk_dollars / risk_per_share)
        else:
            shares = 0
            
        if shares < 1:
            shares = 0
            
        # 2. Gross PnL (Adjusted for new slippage)
        # Original PnL per share from CSV (includes 0.01 slip)
        orig_pnl_share = row['pnl_per_share']
        
        # Adjust for new slippage
        adj_pnl_share = orig_pnl_share - slip_cost_per_share_round_trip
        gross_pnl = shares * adj_pnl_share
        
        # 3. Commissions
        if shares > 0:
            comm = max(min_comm, comm_share * shares) * 2 # Round trip
            comm += fixed_fee
        else:
            comm = 0
            
        net_pnl = gross_pnl - comm
        equity += net_pnl
        equity_curve.append(equity)
        
        trades_log.append({
            'net_pnl': net_pnl,
            'comm': comm,
            'shares': shares
        })
        
        if equity < 50: # Bust
            break
            
    # Metrics
    final_equity = equity
    total_pnl = final_equity - STARTING_CAPITAL
    
    # DD
    curve = pd.Series(equity_curve)
    peak = curve.cummax()
    dd = curve - peak
    max_dd = dd.min()
    
    # Profit Factor
    wins = sum(t['net_pnl'] for t in trades_log if t['net_pnl'] > 0)
    losses = abs(sum(t['net_pnl'] for t in trades_log if t['net_pnl'] <= 0))
    profit_factor = wins / losses if losses > 0 else 999.0

    return {
        "Broker": broker_name,
        "Final Equity": final_equity,
        "Total PnL": total_pnl,
        "Return %": (total_pnl / STARTING_CAPITAL) * 100,
        "Max DD": max_dd,
        "Profit Factor": profit_factor,
        "Total Comm Paid": sum(t['comm'] for t in trades_log)
    }

def run_comparison():
    # Compare Exp 1.1 (Baseline) vs Exp 4.1 (ML)
    experiments = {
        "Baseline (1.1)": "trades_exp_1.1.csv",
        "ML LogReg (4.1)": "trades_exp_4.1.csv"
    }
    
    # Kelly values from previous analysis
    kelly_map = {
        "Baseline (1.1)": 0.057,
        "ML LogReg (4.1)": 0.118
    }

    sizing_methods = [
        ("Fixed 2%", 0.02),
        ("Kelly", "lookup") 
    ]
    
    all_results = []
    
    for strat_name, filename in experiments.items():
        path = TRADES_DIR / filename
        if not path.exists():
            print(f"Missing {filename}")
            continue
            
        df = pd.read_csv(path)
        df['entry_time'] = pd.to_datetime(df['entry_time'], utc=True)
        df = df.sort_values('entry_time')
        
        print(f"\nSimulating {strat_name} ({len(df)} trades)...")
        
        for sizing_name, sizing_val in sizing_methods:
            if sizing_val == "lookup":
                risk_pct = kelly_map.get(strat_name, 0.02)
                actual_sizing_name = f"Kelly ({risk_pct:.1%})"
            else:
                risk_pct = sizing_val
                actual_sizing_name = sizing_name
                
            for broker_name, params in BROKERS.items():
                res = simulate_broker(df, broker_name, params, risk_pct)
                res['Strategy'] = strat_name
                res['Sizing'] = actual_sizing_name
                all_results.append(res)
            
    # Display
    res_df = pd.DataFrame(all_results)
    res_df = res_df[['Strategy', 'Sizing', 'Broker', 'Final Equity', 'Return %', 'Max DD', 'Profit Factor', 'Total Comm Paid']]
    
    print(f"\n=== Broker Simulation Results (${STARTING_CAPITAL:,.0f} Start) ===")
    print(res_df.to_string(index=False))
    
    res_df.to_csv(OUTPUT_DIR / "master_comparison_broker.csv", index=False)

if __name__ == "__main__":
    run_comparison()
