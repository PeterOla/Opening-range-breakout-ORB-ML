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

def evaluate_model_predictions(trades_file: str, model_path: str):
    print(f"--- EVALUATING MODEL: {Path(model_path).name} ---")
    
    # 1. Load Data (Same as training)
    print("Loading Dataset...")
    dataset = ORBSequenceDataset(trades_file)
    
    # Use the LAST 20% (Test Set) to be fair
    split_idx = int(len(dataset) * 0.8)
    test_dataset = torch.utils.data.Subset(dataset, range(split_idx, len(dataset)))
    loader = DataLoader(test_dataset, batch_size=32, shuffle=False)
    
    print(f"Test Set Size: {len(test_dataset)} samples")
    
    # 2. Load Model
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # Updated to match training architecture: 128 hidden, 3 layers
    model = ORBLSTM(input_dim=10, hidden_dim=128, num_layers=3, output_dim=1).to(device)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    
    # 3. Predict
    all_preds = []
    all_labels = []
    
    print("Running Inference...")
    with torch.no_grad():
        for X_batch, y_batch in loader:
            X_batch = X_batch.to(device)
            outputs = model(X_batch)
            # Apply Sigmoid because model outputs logits now
            probs = torch.sigmoid(outputs)
            preds = (probs > 0.5).float().cpu().numpy()
            all_preds.extend(preds)
            all_labels.extend(y_batch.numpy())
            
    # 4. Analyze
    all_preds = np.array(all_preds).flatten()
    all_labels = np.array(all_labels).flatten()
    
    total = len(all_preds)
    predicted_wins = np.sum(all_preds == 1)
    actual_wins = np.sum(all_labels == 1)
    
    print("\n--- RESULTS ---")
    print(f"Total Trades in Test Set: {total}")
    print(f"Actual Winning Trades:    {actual_wins} ({actual_wins/total:.1%})")
    print(f"Predicted Winning Trades: {predicted_wins} ({predicted_wins/total:.1%})")
    
    if predicted_wins == 0:
        print("\n[WARNING] The model is predicting 'LOSS' for everything.")
        print("This means it has collapsed to the majority class (Safe Bet).")
        print("It is NOT learning useful patterns yet.")
    else:
        # Precision (If model says Win, is it a Win?)
        true_positives = np.sum((all_preds == 1) & (all_labels == 1))
        precision = true_positives / predicted_wins if predicted_wins > 0 else 0
        print(f"\nPrecision (Win Rate of Model Picks): {precision:.1%}")
        print(f"Baseline Win Rate (Random):          {actual_wins/total:.1%}")

if __name__ == "__main__":
    # Updated to Top 50
    trades_file = PROJECT_ROOT / "orb_5m" / "results" / "results_combined_top50" / "all_trades.csv"
    model_path = PROJECT_ROOT / "ml_orb_5m" / "models" / "saved_models" / "lstm_results_combined_top50_best.pth"
    
    evaluate_model_predictions(str(trades_file), str(model_path))
