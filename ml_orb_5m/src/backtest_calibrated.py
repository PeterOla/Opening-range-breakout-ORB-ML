"""
Backtest using calibrated LSTM probabilities with percentile-based filtering.

Tests:
- Baseline (no filter)
- Top 1% predictions
- Top 10% predictions

Uses calibrated probabilities from production pipeline.
"""

import torch
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import pickle
from scipy.special import expit

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ml_orb_5m.src.models.lstm_model import ORBLSTM
from ml_orb_5m.src.data.lstm_dataset import ORBSequenceDataset

def load_calibration_model(calibration_path: Path):
    """Load the saved calibration model."""
    with open(calibration_path, 'rb') as f:
        cal_data = pickle.load(f)
    return cal_data['model'], cal_data['method']

def simulate_strategy(
    trades_df: pd.DataFrame,
    strategy_name: str,
    position_size_pct: float = 0.02,
    initial_capital: float = 1000.0,
    prob_col: str = None,
    percentile_threshold: float = None
) -> dict:
    """
    Simulate trading strategy with optional probability-based filtering.
    
    Args:
        trades_df: DataFrame with trades and probabilities
        strategy_name: Name for logging
        position_size_pct: Position size as fraction of equity (0.02 = 2%)
        initial_capital: Starting capital
        prob_col: Column name for probabilities (None = no filter)
        percentile_threshold: If set, only trade top X percentile (e.g., 99 for top 1%)
    """
    # Sort by time
    trades_df = trades_df.sort_values("entry_time").reset_index(drop=True)
    
    # Out-of-sample: Use last 20% of data (test set)
    split_idx = int(len(trades_df) * 0.8)
    oos_df = trades_df.iloc[split_idx:].copy()
    
    print(f"\n{strategy_name}:")
    print(f"  Out-of-sample period: {oos_df['entry_time'].min()} to {oos_df['entry_time'].max()}")
    print(f"  Total opportunities: {len(oos_df)}")
    
    # Apply percentile filter if specified
    if prob_col and percentile_threshold is not None:
        # Calculate threshold on out-of-sample data only (to prevent look-ahead)
        valid_probs = oos_df[prob_col].dropna()
        if len(valid_probs) > 0:
            threshold_value = np.percentile(valid_probs, percentile_threshold)
            print(f"  Percentile threshold ({percentile_threshold}%): {threshold_value:.4f}")
            
            # Mark trades to take
            oos_df['take_trade'] = (oos_df[prob_col] >= threshold_value) & (~oos_df[prob_col].isna())
        else:
            oos_df['take_trade'] = False
    elif prob_col:
        # Use probability column but no percentile filter (all with valid prob)
        oos_df['take_trade'] = ~oos_df[prob_col].isna()
    else:
        # Baseline: take all trades
        oos_df['take_trade'] = True
    
    # Simulation
    equity = initial_capital
    equity_curve = []
    trade_log = []
    
    trades_taken = 0
    wins = 0
    total_commissions = 0
    
    for idx, row in oos_df.iterrows():
        if not row['take_trade']:
            continue
        
        # Position sizing
        position_value = equity * position_size_pct
        entry_price = row["entry_price"]
        
        if entry_price <= 0:
            continue
        
        shares = int(position_value / entry_price)
        if shares < 1:
            continue
        
        # Calculate PnL
        pnl_per_share = row["pnl_per_share"]
        
        # Alpaca commission: Scale from original trade
        original_shares = row["shares"]
        original_commission = row["commissions"]
        
        if original_shares > 0:
            comm_per_share = original_commission / original_shares
        else:
            comm_per_share = 0.005  # Fallback
        
        gross_pnl = shares * pnl_per_share
        commission = shares * comm_per_share
        net_pnl = gross_pnl - commission
        
        equity += net_pnl
        total_commissions += commission
        
        trades_taken += 1
        if net_pnl > 0:
            wins += 1
        
        # Log trade
        trade_log.append({
            "date": row["entry_time"],
            "symbol": row["symbol"],
            "direction": row["direction"],
            "shares": shares,
            "entry_price": entry_price,
            "exit_price": row["exit_price"],
            "pnl_per_share": pnl_per_share,
            "gross_pnl": gross_pnl,
            "commission": commission,
            "net_pnl": net_pnl,
            "equity": equity,
            "prob": row.get(prob_col, np.nan) if prob_col else np.nan
        })
    
    print(f"  Trades taken: {trades_taken}")
    
    # Calculate metrics
    if trades_taken == 0:
        return {
            "Strategy": strategy_name,
            "Final Equity": initial_capital,
            "Total Return": 0.0,
            "Sharpe": 0.0,
            "Max Drawdown": 0.0,
            "Win Rate": 0.0,
            "Trades": 0,
            "Total Commissions": 0.0,
            "Avg PnL per Trade": 0.0,
            "daily_equity": pd.DataFrame(),
            "trade_log": pd.DataFrame()
        }
    
    total_return = (equity - initial_capital) / initial_capital
    win_rate = wins / trades_taken
    
    # Build daily equity curve
    trade_df_log = pd.DataFrame(trade_log)
    trade_df_log["date"] = pd.to_datetime(trade_df_log["date"]).dt.date
    
    # Group by date and take last equity of day
    daily_equity = trade_df_log.groupby("date").agg({
        "equity": "last",
        "net_pnl": "sum"
    }).reset_index()
    
    # Fill missing dates
    date_range = pd.date_range(
        start=daily_equity["date"].min(),
        end=daily_equity["date"].max(),
        freq="D"
    )
    daily_equity = daily_equity.set_index("date").reindex(date_range).reset_index()
    daily_equity.columns = ["date", "equity", "daily_pnl"]
    daily_equity["equity"] = daily_equity["equity"].fillna(method="ffill").fillna(initial_capital)
    daily_equity["daily_pnl"] = daily_equity["daily_pnl"].fillna(0)
    
    # Calculate returns
    daily_equity["return"] = daily_equity["equity"].pct_change()
    returns = daily_equity["return"].dropna()
    
    # Sharpe ratio (annualized, assuming 252 trading days)
    if len(returns) > 1 and returns.std() > 0:
        sharpe = returns.mean() / returns.std() * np.sqrt(252)
    else:
        sharpe = 0.0
    
    # Max Drawdown
    daily_equity["peak"] = daily_equity["equity"].cummax()
    daily_equity["drawdown"] = (daily_equity["equity"] - daily_equity["peak"]) / daily_equity["peak"]
    max_dd = daily_equity["drawdown"].min()
    
    # Average PnL per trade
    avg_pnl = trade_df_log["net_pnl"].mean()
    
    print(f"  Final equity: ${equity:,.2f}")
    print(f"  Total return: {total_return:.2%}")
    print(f"  Win rate: {win_rate:.2%}")
    print(f"  Sharpe: {sharpe:.2f}")
    print(f"  Max DD: {max_dd:.2%}")
    print(f"  Avg PnL/trade: ${avg_pnl:.2f}")
    
    return {
        "Strategy": strategy_name,
        "Final Equity": equity,
        "Total Return": total_return,
        "Sharpe": sharpe,
        "Max Drawdown": max_dd,
        "Win Rate": win_rate,
        "Trades": trades_taken,
        "Total Commissions": total_commissions,
        "Avg PnL per Trade": avg_pnl,
        "daily_equity": daily_equity,
        "trade_log": trade_df_log
    }

def main():
    print("="*100)
    print("CALIBRATED LSTM BACKTEST - TOP 1% vs TOP 10%")
    print("="*100)
    
    # Paths
    trades_file = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top50" / "all_trades.csv"
    model_file = PROJECT_ROOT / "ml_orb_5m" / "models" / "saved_models" / "lstm_results_combined_top50_best.pth"
    calibration_file = PROJECT_ROOT / "ml_orb_5m" / "results" / "calibration" / "calibration_model_isotonic_kfold.pkl"
    output_dir = PROJECT_ROOT / "ml_orb_5m" / "results" / "backtest"
    output_dir.mkdir(exist_ok=True)
    
    # 1. Load dataset
    print("\n1. Loading dataset...")
    dataset = ORBSequenceDataset(
        trades_file_path=str(trades_file),
        sequence_length=12,
        target_col="net_pnl",
        profit_threshold=0.0
    )
    
    if not hasattr(dataset, 'indices') or len(dataset.indices) == 0:
        print("ERROR: Dataset missing indices. Delete cache and rerun.")
        return
    
    print(f"Dataset size: {len(dataset)}")
    
    # 2. Load model
    print("\n2. Loading trained model...")
    model = ORBLSTM(input_dim=10, hidden_dim=128, num_layers=3, dropout=0.3)
    model.load_state_dict(torch.load(model_file, map_location='cpu', weights_only=False))
    model.eval()
    
    # 3. Load calibration
    print("\n3. Loading calibration model...")
    calibrator, cal_method = load_calibration_model(calibration_file)
    print(f"Calibration method: {cal_method}")
    
    # 4. Generate predictions
    print("\n4. Generating predictions for all samples...")
    all_logits = []
    all_labels = []
    
    with torch.no_grad():
        for i in range(len(dataset)):
            X, y = dataset[i]
            logit = model(X.unsqueeze(0)).item()
            all_logits.append(logit)
            all_labels.append(y.item())
    
    all_logits = np.array(all_logits)
    raw_probs = expit(all_logits)
    
    # Apply calibration
    if cal_method == 'isotonic_kfold':
        calibrated_probs = calibrator.transform(raw_probs)
    elif cal_method == 'platt':
        calibrated_probs = calibrator.predict_proba(raw_probs.reshape(-1, 1))[:, 1]
    else:
        calibrated_probs = raw_probs
    
    print(f"Generated {len(calibrated_probs)} predictions")
    
    # 5. Map to CSV
    print("\n5. Mapping predictions to trades CSV...")
    trades_df = pd.read_csv(trades_file)
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"], utc=True)
    trades_df["entry_time"] = trades_df["entry_time"].dt.tz_convert("America/New_York")
    
    # Create mapping series
    prob_series = pd.Series(calibrated_probs, index=dataset.indices)
    trades_df["lstm_prob_calibrated"] = prob_series
    
    print(f"Trades with predictions: {trades_df['lstm_prob_calibrated'].notna().sum()}")
    print(f"Calibrated prob range: [{calibrated_probs.min():.4f}, {calibrated_probs.max():.4f}]")
    
    # 6. Run backtests
    print("\n" + "="*100)
    print("RUNNING BACKTESTS (Out-of-Sample: Last 20%)")
    print("="*100)
    
    strategies = [
        # (name, position_size, prob_col, percentile_threshold)
        ("Baseline_2pct", 0.02, None, None),
        ("Top1pct_2pct", 0.02, "lstm_prob_calibrated", 99.0),
        ("Top10pct_2pct", 0.02, "lstm_prob_calibrated", 90.0),
        ("Baseline_5pct", 0.05, None, None),
        ("Top1pct_5pct", 0.05, "lstm_prob_calibrated", 99.0),
        ("Top10pct_5pct", 0.05, "lstm_prob_calibrated", 90.0),
    ]
    
    results = []
    
    for strategy_name, pos_size, prob_col, pct_thresh in strategies:
        result = simulate_strategy(
            trades_df.copy(),
            strategy_name,
            position_size_pct=pos_size,
            initial_capital=1000.0,
            prob_col=prob_col,
            percentile_threshold=pct_thresh
        )
        
        # Save detailed outputs
        daily_equity = result.pop("daily_equity")
        trade_log = result.pop("trade_log")
        
        if not daily_equity.empty:
            equity_file = output_dir / f"equity_curve_{strategy_name}.csv"
            daily_equity.to_csv(equity_file, index=False)
        
        if not trade_log.empty:
            trades_file_out = output_dir / f"trade_log_{strategy_name}.csv"
            trade_log.to_csv(trades_file_out, index=False)
        
        results.append(result)
    
    # 7. Save comparison
    results_df = pd.DataFrame(results)
    comparison_file = output_dir / "master_comparison_lstm.csv"
    results_df.to_csv(comparison_file, index=False)
    
    print("\n" + "="*100)
    print("FINAL COMPARISON")
    print("="*100)
    print(results_df.to_string(index=False))
    print("="*100)
    print(f"\nResults saved to: {comparison_file}")
    print(f"Detailed logs saved to: {output_dir}")

if __name__ == "__main__":
    main()
