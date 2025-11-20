import joblib
import pandas as pd
import numpy as np
from pathlib import Path
import json
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ml_orb_5m.src.features.price_action import (
    calculate_or_metrics,
    calculate_gap_features,
    detect_candlestick_patterns,
    calculate_momentum_indicators,
    calculate_price_levels
)
from ml_orb_5m.src.features.volume_liquidity import (
    calculate_volume_metrics,
    calculate_liquidity_proxies
)
from ml_orb_5m.src.features.volatility import (
    calculate_volatility_metrics
)
from ml_orb_5m.src.features.temporal import (
    calculate_temporal_metrics
)
from ml_orb_5m.src.features.market_context import (
    calculate_market_context
)

class MLPredictor:
    def __init__(self, models_dir: Path, config_path: Path, model_prefix: str = "xgb_context", feature_set_key: str = "final_selected_features"):
        self.models_dir = models_dir
        self.config_path = config_path
        self.model_prefix = model_prefix
        self.feature_set_key = feature_set_key
        self.artifacts = {}
        self.features = []
        self._load_artifacts()

    def _load_artifacts(self):
        # Load config
        with open(self.config_path, "r") as f:
            config = json.load(f)
        
        # Load features based on key
        if self.feature_set_key in config:
            self.features = config[self.feature_set_key]
        else:
            print(f"Warning: Feature set '{self.feature_set_key}' not found. Falling back to 'final_selected_features'.")
            self.features = config.get("final_selected_features", config.get("all_features"))
            
        # Check if we need market context
        self.uses_market_context = any(f.startswith(('spy', 'qqq', 'vix')) for f in self.features)
        
        # Load Dual Models with prefix
        # e.g. xgb_context_long_model.pkl
        for side in ['long', 'short']:
            base_name = f"{self.model_prefix}_{side}"
            try:
                self.artifacts[side] = {
                    'model': joblib.load(self.models_dir / f"{base_name}_model.pkl"),
                    'imputer': joblib.load(self.models_dir / f"{base_name}_imputer.pkl"),
                    'scaler': joblib.load(self.models_dir / f"{base_name}_scaler.pkl")
                }
            except FileNotFoundError:
                # Fallback for backward compatibility or if prefix is empty
                print(f"Warning: Model {base_name} not found. Trying legacy format {side}_model.pkl")
                self.artifacts[side] = {
                    'model': joblib.load(self.models_dir / f"{side}_model.pkl"),
                    'imputer': joblib.load(self.models_dir / f"{side}_imputer.pkl"),
                    'scaler': joblib.load(self.models_dir / f"{side}_scaler.pkl")
                }
            
    def calculate_features_live(self, symbol: str, date, bars_5m: pd.DataFrame, bars_daily: pd.DataFrame, 
                              spy_df: pd.DataFrame, qqq_df: pd.DataFrame, vix_df: pd.DataFrame) -> pd.Series:
        """
        Calculate features on the fly for a specific symbol and date.
        """
        target_date = pd.to_datetime(date).date()
        
        # Filter data for the specific day
        bars_today = bars_5m[bars_5m['date'] == target_date].copy()
        if bars_today.empty:
            raise ValueError(f"No 5min data for {symbol} on {target_date}")
            
        # Previous day data for gaps
        # Optimization: Use bars_daily if available to get previous close/high/low
        prev_day_close = None
        prev_day_high = None
        prev_day_low = None
        
        if not bars_daily.empty:
             # Filter daily bars before today
             daily_prev = bars_daily[bars_daily['date'] < target_date]
             if not daily_prev.empty:
                 last_day = daily_prev.iloc[-1]
                 prev_day_close = last_day['close']
                 prev_day_high = last_day['high']
                 prev_day_low = last_day['low']
        
        # Fallback to 5m if daily missing (slower)
        if prev_day_close is None:
            bars_prev = bars_5m[bars_5m['date'] < target_date]
            if not bars_prev.empty:
                prev_day_close = bars_prev.iloc[-1]['close']
                # Groupby is expensive, just take max/min of the last day in the prev set if possible
                # But bars_prev is all history. 
                # Let's just take the last day's data from bars_prev
                last_prev_date = bars_prev.iloc[-1]['date']
                last_day_bars = bars_prev[bars_prev['date'] == last_prev_date]
                prev_day_high = last_day_bars['high'].max()
                prev_day_low = last_day_bars['low'].min()

        # Daily history
        bars_daily_prev = bars_daily[bars_daily['date'] < target_date].copy()
        
        # Initialize features
        features = {}
        
        # 1. Price Action
        features.update(calculate_or_metrics(bars_today))
        features.update(calculate_gap_features(bars_today, prev_day_close))
        features.update(detect_candlestick_patterns(bars_today))
        
        or_bars = bars_today[
            (bars_today['timestamp'].dt.time >= pd.to_datetime("09:30").time()) &
            (bars_today['timestamp'].dt.time < pd.to_datetime("09:35").time())
        ].copy()
        features.update(calculate_momentum_indicators(or_bars))
        features.update(calculate_price_levels(bars_today, prev_day_high, prev_day_low))
        
        # 2. Volume & Liquidity
        features.update(calculate_volume_metrics(bars_today, bars_daily_prev))
        features.update(calculate_liquidity_proxies(bars_today))
        
        # 3. Volatility
        features.update(calculate_volatility_metrics(bars_today, bars_daily_prev))
        
        # 4. Market Context
        # Always calculate market context if data is available, even if not used by model
        # This prevents "missing feature" errors if the model expects it but self.uses_market_context is False
        # (which shouldn't happen if config is correct, but safety first)
        if not spy_df.empty and not qqq_df.empty and not vix_df.empty:
             features.update(calculate_market_context(str(target_date), spy_df, qqq_df, vix_df))
        
        # 5. Temporal
        features.update(calculate_temporal_metrics(str(target_date)))
        
        return pd.Series(features)

    def predict(self, row: pd.Series) -> float:
        """
        Predict probability for a single trade row.
        Row must contain all required features + 'side' (long/short).
        """
        # Determine side
        # If 'side' is not in row, try to infer or default to long?
        # The strategy should provide 'direction' (1 or -1)
        
        direction = row.get('direction', 0)
        if direction == 1:
            side = 'long'
        elif direction == -1:
            side = 'short'
        else:
            # Try 'side' string
            side = row.get('side', 'long').lower()
            
        if side not in ['long', 'short']:
            return 0.0
            
        # Extract features
        try:
            # Ensure we have all features
            # Fill missing with NaN (imputer will handle)
            X = row.reindex(self.features).to_frame().T
            
            # Preprocess
            imp = self.artifacts[side]['imputer']
            scl = self.artifacts[side]['scaler']
            mod = self.artifacts[side]['model']
            
            X_imp = imp.transform(X)
            X_scl = scl.transform(X_imp)
            
            # Predict
            prob = mod.predict_proba(X_scl)[:, 1][0]
            return prob
            
        except Exception as e:
            print(f"Prediction Error: {e}")
            return 0.0

    def predict_batch(self, df: pd.DataFrame) -> pd.Series:
        """
        Predict probabilities for a DataFrame of trades.
        """
        probs = pd.Series(0.0, index=df.index)
        
        # Longs
        long_mask = df['direction'] == 1
        if long_mask.any():
            X_long = df.loc[long_mask, self.features]
            imp = self.artifacts['long']['imputer']
            scl = self.artifacts['long']['scaler']
            mod = self.artifacts['long']['model']
            
            X_imp = imp.transform(X_long)
            X_scl = scl.transform(X_imp)
            probs.loc[long_mask] = mod.predict_proba(X_scl)[:, 1]
            
        # Shorts
        short_mask = df['direction'] == -1
        if short_mask.any():
            X_short = df.loc[short_mask, self.features]
            imp = self.artifacts['short']['imputer']
            scl = self.artifacts['short']['scaler']
            mod = self.artifacts['short']['model']
            
            X_imp = imp.transform(X_short)
            X_scl = scl.transform(X_imp)
            probs.loc[short_mask] = mod.predict_proba(X_scl)[:, 1]
            
        return probs
