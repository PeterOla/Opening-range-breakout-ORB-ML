import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
import numpy as np
from pathlib import Path
import sys
import argparse
from datetime import datetime

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ml_orb_5m.src.data.lstm_dataset import ORBSequenceDataset
from ml_orb_5m.src.models.lstm_model import ORBLSTM

def calculate_metrics(outputs, targets, threshold=0.5):
    # Apply sigmoid to logits
    probs = torch.sigmoid(outputs)
    preds = (probs > threshold).float()
    
    # Convert to numpy
    preds_np = preds.cpu().numpy()
    targets_np = targets.cpu().numpy()
    
    tp = np.sum((preds_np == 1) & (targets_np == 1))
    fp = np.sum((preds_np == 1) & (targets_np == 0))
    fn = np.sum((preds_np == 0) & (targets_np == 1))
    tn = np.sum((preds_np == 0) & (targets_np == 0))
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / (tp + tn + fp + fn)
    
    return accuracy, precision, recall, f1

def train_model(
    trades_file: str,
    epochs: int = 50,
    batch_size: int = 32,
    learning_rate: float = 0.001,
    split_ratio: float = 0.8
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
    if torch.cuda.is_available():
        print(f"GPU Detected: {torch.cuda.get_device_name(0)}")
        pin_memory = True
        num_workers = 4 # Parallel data loading
    else:
        print("WARNING: No GPU detected. Training will proceed on CPU (slower).")
        pin_memory = False
        num_workers = 0

    # Logging Setup
    dataset_name = Path(trades_file).parent.name  # e.g., "results_combined_top20"
    log_dir = PROJECT_ROOT / "ml_orb_5m" / "results" / "lstm_training_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_csv = log_dir / f"training_log_{dataset_name}_{timestamp}.csv"
    summary_file_md = log_dir / f"summary_{dataset_name}_{timestamp}.md"
    
    print(f"Logging results to: {log_dir}")
    
    with open(log_file_csv, "w") as f:
        f.write("epoch,train_loss,train_acc,train_prec,train_rec,val_loss,val_acc,val_prec,val_rec\n")

    # 1. Prepare Data
    print("Preparing Dataset...")
    full_dataset = ORBSequenceDataset(trades_file)
    
    if len(full_dataset) == 0:
        print("Dataset is empty. Exiting.")
        return

    # Proper Chronological Split: Train 70% / Val 15% / Test 15%
    # This prevents overlap and allows proper calibration testing
    train_size = int(len(full_dataset) * 0.70)
    val_size = int(len(full_dataset) * 0.15)
    test_size = len(full_dataset) - train_size - val_size
    
    train_dataset = torch.utils.data.Subset(full_dataset, range(0, train_size))
    val_dataset = torch.utils.data.Subset(full_dataset, range(train_size, train_size + val_size))
    test_dataset = torch.utils.data.Subset(full_dataset, range(train_size + val_size, len(full_dataset)))
    
    # Standard DataLoader (Shuffle training data for SGD, but NO WeightedRandomSampler)
    # Added pin_memory and num_workers for speed
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, pin_memory=pin_memory, num_workers=num_workers)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, pin_memory=pin_memory, num_workers=num_workers)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False, pin_memory=pin_memory, num_workers=num_workers)
    
    print(f"Train: {len(train_dataset)}, Val: {len(val_dataset)}, Test: {len(test_dataset)} samples")

    # 2. Initialize Model
    # Updated architecture: 128 hidden units, 3 layers for better capacity
    model = ORBLSTM(input_dim=10, hidden_dim=128, num_layers=3, output_dim=1).to(device)
    
    # Calculate Class Weights for Loss Function
    train_labels = [y.item() for _, y in train_dataset]
    num_pos = sum(train_labels)
    num_neg = len(train_labels) - num_pos
    
    # Weight for positive class to balance the loss
    pos_weight_val = num_neg / num_pos if num_pos > 0 else 1.0
    pos_weight_tensor = torch.tensor([pos_weight_val]).to(device)
    
    print(f"Class Imbalance: {num_pos} Wins / {num_neg} Losses")
    print(f"Using BCEWithLogitsLoss with pos_weight: {pos_weight_val:.2f}")
    
    # Use BCEWithLogitsLoss (combines Sigmoid + BCELoss)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight_tensor)
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)

    # 3. Training Loop
    best_precision = 0.0  # Track Precision instead of Accuracy
    
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        
        all_train_preds = []
        all_train_targets = []
        
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device).float().unsqueeze(1)
            
            optimizer.zero_grad()
            outputs = model(X_batch)
            loss = criterion(outputs, y_batch)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item()
            
            # Store for metrics
            all_train_preds.append(outputs.detach())
            all_train_targets.append(y_batch.detach())
            
        # Calculate Train Metrics
        train_outputs = torch.cat(all_train_preds)
        train_targets = torch.cat(all_train_targets)
        train_acc, train_prec, train_rec, train_f1 = calculate_metrics(train_outputs, train_targets)
        
        # Validation
        model.eval()
        val_loss = 0.0
        all_val_preds = []
        all_val_targets = []
        
        with torch.no_grad():
            for X_batch, y_batch in val_loader:
                X_batch, y_batch = X_batch.to(device), y_batch.to(device).float().unsqueeze(1)
                outputs = model(X_batch)
                loss = criterion(outputs, y_batch)
                val_loss += loss.item()
                
                all_val_preds.append(outputs)
                all_val_targets.append(y_batch)
        
        # Calculate Val Metrics
        val_outputs = torch.cat(all_val_preds)
        val_targets = torch.cat(all_val_targets)
        val_acc, val_prec, val_rec, val_f1 = calculate_metrics(val_outputs, val_targets)
        
        # Log to CSV
        with open(log_file_csv, "a") as f:
            f.write(f"{epoch+1},{train_loss/len(train_loader):.4f},{train_acc:.4f},{train_prec:.4f},{train_rec:.4f},"
                    f"{val_loss/len(test_loader):.4f},{val_acc:.4f},{val_prec:.4f},{val_rec:.4f}\n")
        
        print(f"Epoch {epoch+1}/{epochs} | Loss: {train_loss/len(train_loader):.4f} | "
              f"Val Prec: {val_prec:.4f} | Val Rec: {val_rec:.4f} | Val Acc: {val_acc:.4f}")
        
        # Save best model based on Precision (since we care about win rate of picks)
        if val_prec > best_precision:
            best_precision = val_prec
            save_path = PROJECT_ROOT / "ml_orb_5m" / "models" / "saved_models" / f"lstm_{dataset_name}_best.pth"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), save_path)
            
    print(f"Training Complete. Best Val Precision: {best_precision:.4f}")
    print(f"Model saved to {save_path}")
    
    # Write Summary MD
    with open(summary_file_md, "w") as f:
        f.write(f"# LSTM Training Summary: {dataset_name}\n")
        f.write(f"- **Date**: {timestamp}\n")
        f.write(f"- **Trades File**: `{trades_file}`\n")
        f.write(f"- **Epochs**: {epochs}\n")
        f.write(f"- **Best Validation Precision**: {best_precision:.4f}\n")
        f.write(f"- **Model Saved To**: `{save_path}`\n")
        f.write("\n## Training Log\n")
        f.write("See CSV file for detailed epoch logs.\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("trades_file", type=str, help="Path to trades CSV")
    parser.add_argument("--epochs", type=int, default=20)
    args = parser.parse_args()
    
    train_model(args.trades_file, epochs=args.epochs)
