"""
Backtest using calibrated LSTM probabilities with percentile-based filtering for Top-20 dataset.
Saves equity CSVs, trade logs and a summary file for blog use.
"""

# This is a modified copy of backtest_calibrated.py that uses Top20 files and outputs to backtest_top20

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
    with open(calibration_path, 'rb') as f:
        cal_data = pickle.load(f)
    return cal_data['model'], cal_data['method']


# Reuse simulate_strategy from backtest_calibrated (kept identical for compatibility)

def simulate_strategy(
    trades_df: pd.DataFrame,
    strategy_name: str,
    position_size_pct: float = 0.02,
    initial_capital: float = 1000.0,
    prob_col: str = None,
    percentile_threshold: float = None
) -> dict:
    # (function body copied from backtest_calibrated.py unchanged)
    trades_df = trades_df.sort_values("entry_time").reset_index(drop=True)
    split_idx = int(len(trades_df) * 0.8)
    oos_df = trades_df.iloc[split_idx:].copy()

    if prob_col and percentile_threshold is not None:
        valid_probs = oos_df[prob_col].dropna()
        if len(valid_probs) > 0:
            threshold_value = np.percentile(valid_probs, percentile_threshold)
            oos_df['take_trade'] = (oos_df[prob_col] >= threshold_value) & (~oos_df[prob_col].isna())
        else:
            oos_df['take_trade'] = False
    elif prob_col:
        oos_df['take_trade'] = ~oos_df[prob_col].isna()
    else:
        oos_df['take_trade'] = True

    equity = initial_capital
    equity_curve = []
    trade_log = []
    trades_taken = 0
    wins = 0
    total_commissions = 0

    for idx, row in oos_df.iterrows():
        if not row['take_trade']:
            continue
        position_value = equity * position_size_pct
        entry_price = row["entry_price"]
        if entry_price <= 0:
            continue
        shares = int(position_value / entry_price)
        if shares < 1:
            continue
        pnl_per_share = row["pnl_per_share"]
        original_shares = row["shares"]
        original_commission = row["commissions"]
        if original_shares > 0:
            comm_per_share = original_commission / original_shares
        else:
            comm_per_share = 0.005
        gross_pnl = shares * pnl_per_share
        commission = shares * comm_per_share
        net_pnl = gross_pnl - commission
        equity += net_pnl
        total_commissions += commission
        trades_taken += 1
        if net_pnl > 0:
            wins += 1
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

    trade_df_log = pd.DataFrame(trade_log)
    trade_df_log["date"] = pd.to_datetime(trade_df_log["date"]).dt.date
    daily_equity = trade_df_log.groupby("date").agg({
        "equity": "last",
        "net_pnl": "sum"
    }).reset_index()
    date_range = pd.date_range(start=daily_equity["date"].min(), end=daily_equity["date"].max(), freq="D")
    daily_equity = daily_equity.set_index("date").reindex(date_range).reset_index()
    daily_equity.columns = ["date", "equity", "daily_pnl"]
    daily_equity["equity"] = daily_equity["equity"].fillna(method="ffill").fillna(initial_capital)
    daily_equity["daily_pnl"] = daily_equity["daily_pnl"].fillna(0)
    daily_equity["return"] = daily_equity["equity"].pct_change()
    returns = daily_equity["return"].dropna()
    if len(returns) > 1 and returns.std() > 0:
        sharpe = returns.mean() / returns.std() * np.sqrt(252)
    else:
        sharpe = 0.0
    daily_equity["peak"] = daily_equity["equity"].cummax()
    daily_equity["drawdown"] = (daily_equity["equity"] - daily_equity["peak"]) / daily_equity["peak"]
    max_dd = daily_equity["drawdown"].min()
    avg_pnl = trade_df_log["net_pnl"].mean()

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
    print("Running Top-20 calibrated LSTM backtest")
    trades_file = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top20" / "all_trades.csv"
    # Use the Top50-trained LSTM (10-feature) to apply to Top20 dataset for consistent input dim
    model_file = PROJECT_ROOT / "ml_orb_5m" / "models" / "saved_models" / "lstm_results_combined_top50_best.pth"
    calibration_file = PROJECT_ROOT / "ml_orb_5m" / "results" / "calibration" / "calibration_model_isotonic_kfold.pkl"
    output_dir = PROJECT_ROOT / "ml_orb_5m" / "results" / "backtest_top20"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("1. Loading dataset...")
    dataset = ORBSequenceDataset(
        trades_file_path=str(trades_file),
        sequence_length=12,
        target_col="net_pnl",
        profit_threshold=0.0
    )

    print(f"Dataset size: {len(dataset)}")

    print("2. Loading trained model (auto-detecting checkpoint architecture)...")
    # Try to load checkpoint and infer architecture
    ckpt = torch.load(model_file, map_location='cpu')
    # Infer input_dim, hidden_dim and num_layers from checkpoint weights
    lstm_keys = [k for k in ckpt.keys() if k.startswith('lstm.weight_ih_')]
    inferred_num_layers = len(lstm_keys)
    inferred_input_dim = ckpt['lstm.weight_ih_l0'].shape[1]
    inferred_hidden_dim = ckpt['lstm.weight_hh_l0'].shape[1]

    # Infer FC architecture from linear layer shapes in the state_dict
    fc_weights = [k for k in ckpt.keys() if k.startswith('fc') and k.endswith('.weight')]
    # Sort fc keys by numeric index so fc.0, fc.3, etc. are in order
    def fc_index(k):
        return int(k.split('.')[1])
    fc_weights_sorted = sorted(fc_weights, key=fc_index)
    # fc layer order in state_dict is fc.0.weight, fc.3.weight, etc. Let's capture sizes (out, in)
    fc_shapes = [tuple(ckpt[k].shape) for k in fc_weights_sorted]
    # Create a simple LSTM + FC model matching checkpoint's architecture
    import torch.nn as nn

    class LSTMCheckModel(nn.Module):
        def __init__(self, input_dim, hidden_dim, num_layers, fc_shapes):
            super().__init__()
            self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim, num_layers=num_layers, batch_first=True)
            # Build FC based on fc_shapes (list of (out, in))
            fc_layers = []
            # Build a Sequential that mirrors the original layout where each Linear except the last is followed by ReLU and Dropout
            # fc_shapes is list of (out, in) for each Linear.
            for i, (out_dim, in_dim_ck) in enumerate(fc_shapes):
                fc_layers.append(nn.Linear(in_dim_ck, out_dim))
                # if not last linear, add ReLU and Dropout to mirror original pattern
                if i < len(fc_shapes) - 1:
                    fc_layers.append(nn.ReLU())
                    fc_layers.append(nn.Dropout(0.3))
            self.fc = nn.Sequential(*fc_layers)

        def forward(self, x):
            h0 = torch.zeros(inferred_num_layers, x.size(0), inferred_hidden_dim).to(x.device)
            c0 = torch.zeros(inferred_num_layers, x.size(0), inferred_hidden_dim).to(x.device)
            out, _ = self.lstm(x, (h0, c0))
            out = out[:, -1, :]
            out = self.fc(out)
            return out

    model = LSTMCheckModel(inferred_input_dim, inferred_hidden_dim, inferred_num_layers, fc_shapes)
    # Load weights
    model.load_state_dict(ckpt)
    model.eval()

    print("3. Loading calibration model...")
    calibrator, cal_method = load_calibration_model(calibration_file)
    print(f"Calibration method: {cal_method}")

    print("4. Generating predictions...")
    all_logits = []
    with torch.no_grad():
        for i in range(len(dataset)):
            X, y = dataset[i]
            logit = model(X.unsqueeze(0)).item()
            all_logits.append(logit)
    all_logits = np.array(all_logits)
    raw_probs = expit(all_logits)

    if cal_method == 'isotonic_kfold':
        calibrated_probs = calibrator.transform(raw_probs)
    elif cal_method == 'platt':
        calibrated_probs = calibrator.predict_proba(raw_probs.reshape(-1, 1))[:, 1]
    else:
        calibrated_probs = raw_probs

    print("Mapping predictions to trades CSV...")
    trades_df = pd.read_csv(trades_file)
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"], utc=True)
    trades_df["entry_time"] = trades_df["entry_time"].dt.tz_convert("America/New_York")

    prob_series = pd.Series(calibrated_probs, index=dataset.indices)
    trades_df["lstm_prob_calibrated"] = prob_series

    print("Running backtests for Top20 dataset...")
    strategies = [
        ("Baseline_2pct", 0.02, None, None),
        ("Top1pct_2pct", 0.02, "lstm_prob_calibrated", 99.0),
        ("Top10pct_2pct", 0.02, "lstm_prob_calibrated", 90.0),
        ("Baseline_5pct", 0.05, None, None),
        ("Top1pct_5pct", 0.05, "lstm_prob_calibrated", 99.0),
        ("Top10pct_5pct", 0.05, "lstm_prob_calibrated", 90.0),
    ]

    results = []
    for strategy_name, pos_size, prob_col, pct in strategies:
        result = simulate_strategy(trades_df.copy(), strategy_name, position_size_pct=pos_size, initial_capital=1000.0, prob_col=prob_col, percentile_threshold=pct)
        daily_equity = result.pop("daily_equity")
        trade_log = result.pop("trade_log")
        if not daily_equity.empty:
            daily_equity.to_csv(output_dir / f"equity_curve_{strategy_name}.csv", index=False)
        if not trade_log.empty:
            trade_log.to_csv(output_dir / f"trade_log_{strategy_name}.csv", index=False)
        results.append(result)

    results_df = pd.DataFrame(results)
    summary_path = output_dir / "master_comparison_lstm_top20.csv"
    results_df.to_csv(summary_path, index=False)
    print(f"Saved summary to {summary_path}")
    print("Done")


if __name__ == '__main__':
    main()
