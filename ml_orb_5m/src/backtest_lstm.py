import torch
import pandas as pd
import numpy as np
from pathlib import Path
import sys
from torch.utils.data import DataLoader

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ml_orb_5m.src.models.lstm_model import ORBLSTM
from ml_orb_5m.src.data.lstm_dataset import ORBSequenceDataset

def run_backtest(trades_file: str, model_path: str, output_file: str):
    print(f"--- RUNNING BACKTEST: {Path(model_path).name} ---")
    
    # 1. Load Data & Model
    print("Loading Dataset (this will rebuild cache with indices if needed)...")
    dataset = ORBSequenceDataset(trades_file)
    
    # Check if indices are available
    if not hasattr(dataset, 'indices') or not dataset.indices:
        print("Error: Dataset does not contain original indices. Please delete the cache and re-run.")
        return

    print(f"Loaded {len(dataset)} samples.")
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = ORBLSTM(input_dim=10, hidden_dim=128, num_layers=3, output_dim=1).to(device)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    
    # 2. Run Inference on ALL samples
    loader = DataLoader(dataset, batch_size=1024, shuffle=False) # Large batch for speed
    all_probs = []
    
    print("Running Inference...")
    with torch.no_grad():
        for X_batch, _ in loader:
            X_batch = X_batch.to(device)
            outputs = model(X_batch)
            probs = torch.sigmoid(outputs).cpu().numpy().flatten()
            all_probs.extend(probs)
            
    # 3. Map Predictions back to DataFrame
    print("Mapping predictions to trades...")
    df = pd.read_csv(trades_file)
    
    # Initialize probability column with NaN
    df["lstm_prob"] = np.nan
    
    # Map using stored indices
    # dataset.indices contains the original index in the CSV for each sample
    # all_probs contains the probability for each sample
    
    # Create a mapping series
    prob_series = pd.Series(all_probs, index=dataset.indices)
    df["lstm_prob"] = prob_series
    
    # Drop rows where we couldn't generate a prediction (e.g. missing history)
    # Actually, for backtest comparison, we should keep them but treat them as "No Trade" or "Baseline"
    # But if we want to compare "Strategy with Filter" vs "Strategy without Filter", 
    # we should only compare on the subset where we COULD make a decision?
    # Or we assume if no prediction, we don't trade?
    # Let's assume if no prediction (NaN), we don't trade in the LSTM strategy.
    
    # 4. Simulation Logic
    def simulate_equity(trade_df, risk_pct=0.02, initial_equity=1000.0, filter_col=None, filter_threshold=0.5):
        # --- OUT OF SAMPLE FILTER ---
        # We must only trade on the Test Set (last 20% by time)
        # The dataset was sorted by time during creation, so we can find the split date
        # Or simpler: just take the last 20% of the dataframe after sorting by time
        
        trade_df = trade_df.sort_values("entry_time").reset_index(drop=True)
        split_idx = int(len(trade_df) * 0.8)
        
        # Slice to keep only Out-Of-Sample data
        oos_df = trade_df.iloc[split_idx:].copy()
        
        print(f"    Simulating on {len(oos_df)} Out-of-Sample trades (starting {oos_df['entry_time'].iloc[0]})")
        
        equity = initial_equity
        equity_curve = []
        trade_log = []
        
        trades_taken = 0
        wins = 0
        
        for _, row in oos_df.iterrows():
            # Filter Logic
            if filter_col:
                prob = row[filter_col]
                if pd.isna(prob) or prob < filter_threshold:
                    continue
            
            # Sizing Logic
            # Position Size = Equity * Risk% (Assuming Risk% is Position Size for simplicity as per user request "Sizing: 2% and 5%")
            # Usually "2% Risk" means risking 2% of equity (Stop Loss distance). 
            # "2% Sizing" means position value is 2% of equity.
            # Given "2% and 5%", it's likely Position Sizing (Allocation), because 5% Risk per trade is huge.
            # Let's assume Position Sizing = Equity * pct.
            
            position_value = equity * risk_pct
            entry_price = row["entry_price"]
            
            if entry_price <= 0: continue
            
            shares = int(position_value / entry_price)
            if shares < 1: continue
            
            # PnL Calculation
            # We use pnl_per_share from CSV
            pnl_per_share = row["pnl_per_share"]
            
            # Commission (Alpaca) - Use actual from CSV
            # Alpaca charges per share, CSV already has this calculated for original shares
            # We need to scale it to our position size
            original_shares = row["shares"]
            original_commission = row["commissions"]
            
            if original_shares > 0:
                comm_per_share = original_commission / original_shares
            else:
                comm_per_share = 0.005  # Fallback: Alpaca standard rate
            
            gross_pnl = shares * pnl_per_share
            commission = shares * comm_per_share
            net_pnl = gross_pnl - commission
            
            equity += net_pnl
            
            trades_taken += 1
            if net_pnl > 0:
                wins += 1
            
            # Log each trade
            trade_log.append({
                "date": row["entry_time"],
                "symbol": row["symbol"],
                "direction": row["direction"],
                "shares": shares,
                "entry_price": entry_price,
                "exit_price": row["exit_price"],
                "pnl": net_pnl,
                "equity": equity,
                "prob": row.get(filter_col, np.nan) if filter_col else np.nan
            })
                
        # Metrics
        total_return = (equity - initial_equity) / initial_equity
        win_rate = wins / trades_taken if trades_taken > 0 else 0
        
        # Build Daily Equity Curve from trade log
        if trade_log:
            trade_df_log = pd.DataFrame(trade_log)
            trade_df_log["date"] = pd.to_datetime(trade_df_log["date"]).dt.date
            
            # Group by date and take end-of-day equity
            daily_equity = trade_df_log.groupby("date")["equity"].last().reset_index()
            daily_equity.columns = ["date", "equity"]
            
            # Fill missing dates with forward fill
            date_range = pd.date_range(start=daily_equity["date"].min(), end=daily_equity["date"].max(), freq="D")
            daily_equity = daily_equity.set_index("date").reindex(date_range, method="ffill").reset_index()
            daily_equity.columns = ["date", "equity"]
            
            # Calculate returns and Sharpe
            daily_equity["return"] = daily_equity["equity"].pct_change()
            returns = daily_equity["return"].dropna()
            sharpe = returns.mean() / returns.std() * np.sqrt(252) if len(returns) > 1 and returns.std() > 0 else 0
            
            # Max Drawdown
            daily_equity["peak"] = daily_equity["equity"].cummax()
            daily_equity["drawdown"] = (daily_equity["equity"] - daily_equity["peak"]) / daily_equity["peak"]
            max_dd = daily_equity["drawdown"].min()
        else:
            daily_equity = pd.DataFrame()
            sharpe = 0
            max_dd = 0
            trade_df_log = pd.DataFrame()
        
        return {
            "Final Equity": equity,
            "Total Return": total_return,
            "Sharpe": sharpe,
            "Max Drawdown": max_dd,
            "Win Rate": win_rate,
            "Trades": trades_taken,
            "daily_equity": daily_equity,
            "trade_log": trade_df_log if trade_log else pd.DataFrame()
        }

    # 5. Run Scenarios
    results = []
    
    # Ensure datetime for sorting
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    
    scenarios = [
        ("Baseline_2%", 0.02, None),
        ("Baseline_5%", 0.05, None),
        ("LSTM_v1_2%", 0.02, "lstm_prob"),
        ("LSTM_v1_5%", 0.05, "lstm_prob")
    ]
    
    print("\n--- SIMULATION RESULTS ---")
    for name, size, filter_col in scenarios:
        print(f"Simulating {name}...")
        result_dict = simulate_equity(df, risk_pct=size, filter_col=filter_col)
        
        # Extract analytics for separate files
        daily_equity = result_dict.pop("daily_equity")
        trade_log = result_dict.pop("trade_log")
        
        result_dict["Strategy"] = name
        results.append(result_dict)
        print(f"  Return: {result_dict['Total Return']:.2%}, Sharpe: {result_dict['Sharpe']:.2f}, Trades: {result_dict['Trades']}")
        
        # Save detailed files
        if not daily_equity.empty:
            # Ensure canonical backtest output folder exists
            output_folder = PROJECT_ROOT / "ml_orb_5m" / "results" / "backtest"
            output_folder.mkdir(parents=True, exist_ok=True)
            equity_file = output_folder / f"equity_curve_{name}.csv"
            daily_equity.to_csv(equity_file, index=False)
            print(f"  Saved equity curve to {equity_file.name}")
        
        if not trade_log.empty:
            trades_file_out = output_folder / f"trade_log_{name}.csv"
            trade_log.to_csv(trades_file_out, index=False)
            print(f"  Saved trade log to {trades_file_out.name}")

    # 6. Save Results
    results_df = pd.DataFrame(results)
    # Reorder columns
    cols = ["Strategy", "Total Return", "Sharpe", "Max Drawdown", "Win Rate", "Trades", "Final Equity"]
    results_df = results_df[cols]
    
    results_df.to_csv(output_file, index=False)
    print(f"\nSaved comparison to {output_file}")
    
    # Print formatted table
    print("\n" + "="*100)
    print("BACKTEST SUMMARY (Out-of-Sample: Last 20% of Data)")
    print("="*100)
    print(f"{'Strategy':<20} {'Return':<12} {'Sharpe':<10} {'Max DD':<12} {'Win Rate':<12} {'Trades':<10} {'Final $':<12}")
    print("-"*100)
    for _, row in results_df.iterrows():
        print(f"{row['Strategy']:<20} {row['Total Return']:>10.2%}  {row['Sharpe']:>8.2f}  {row['Max Drawdown']:>10.2%}  {row['Win Rate']:>10.2%}  {row['Trades']:>8.0f}  ${row['Final Equity']:>10,.2f}")
    print("="*100)

if __name__ == "__main__":
    trades_file = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top50" / "all_trades.csv"
    model_path = PROJECT_ROOT / "ml_orb_5m" / "models" / "saved_models" / "lstm_results_combined_top50_best.pth"
    output_file = PROJECT_ROOT / "ml_orb_5m" / "results" / "backtest" / "master_comparison_lstm.csv"
    # Ensure output folder exists
    (PROJECT_ROOT / "ml_orb_5m" / "results" / "backtest").mkdir(parents=True, exist_ok=True)
    
    run_backtest(str(trades_file), str(model_path), str(output_file))
