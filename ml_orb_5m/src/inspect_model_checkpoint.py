import torch
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
model_file = PROJECT_ROOT / 'ml_orb_5m' / 'models' / 'saved_models' / 'lstm_results_combined_top20_best.pth'
print(f"Inspecting: {model_file}")
state_dict = torch.load(model_file, map_location='cpu')
print('\nKeys and shapes:')
for k, v in state_dict.items():
    print(k, v.shape)

# Quick diagnostics for LSTM layer shapes
keys = [k for k in state_dict.keys() if 'lstm.weight_ih' in k]
print('\nLSTM input-hidden shapes:')
for k in keys:
    print(k, state_dict[k].shape)

# FC layers shapes
print('\nFC layers:')
for k in state_dict.keys():
    if 'fc' in k:
        print(k, state_dict[k].shape)
