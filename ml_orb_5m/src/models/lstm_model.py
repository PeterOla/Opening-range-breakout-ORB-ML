import torch
import torch.nn as nn

class ORBLSTM(nn.Module):
    def __init__(self, input_dim=10, hidden_dim=128, num_layers=3, output_dim=1, dropout=0.3):
        super(ORBLSTM, self).__init__()
        
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        
        # LSTM Layer (Increased capacity)
        # batch_first=True expects input (batch, seq, feature)
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0
        )
        
        # Fully Connected Layers (Deeper network)
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, output_dim)
            # Removed Sigmoid for BCEWithLogitsLoss
        )
        
    def forward(self, x):
        # x shape: (batch, seq_len, input_dim)
        
        # Initialize hidden state with zeros
        h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_dim).to(x.device)
        c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_dim).to(x.device)
        
        # Forward propagate LSTM
        # out shape: (batch, seq_len, hidden_dim)
        out, _ = self.lstm(x, (h0, c0))
        
        # Decode the hidden state of the last time step
        out = out[:, -1, :]
        
        # Pass through FC
        out = self.fc(out)
        return out
