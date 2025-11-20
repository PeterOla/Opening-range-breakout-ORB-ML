import pandas as pd
import numpy as np

def calculate_temporal_metrics(date_str):
    """
    Calculate temporal features based on the trade date.
    
    Args:
        date_str (str): Date string in 'YYYY-MM-DD' format
        
    Returns:
        dict: Dictionary of temporal features
    """
    try:
        dt = pd.to_datetime(date_str)
        
        features = {
            'day_of_week': dt.dayofweek,  # 0=Monday, 4=Friday
            'month': dt.month,
            'is_month_start': 1 if dt.is_month_start else 0,
            'is_month_end': 1 if dt.is_month_end else 0,
            'is_quarter_start': 1 if dt.is_quarter_start else 0,
            'is_quarter_end': 1 if dt.is_quarter_end else 0,
            'day_of_year': dt.dayofyear
        }
        
        return features
        
    except Exception as e:
        print(f"Error calculating temporal metrics for {date_str}: {e}")
        return {
            'day_of_week': np.nan,
            'month': np.nan,
            'is_month_start': 0,
            'is_month_end': 0,
            'is_quarter_start': 0,
            'is_quarter_end': 0,
            'day_of_year': np.nan
        }

def extract_temporal_features(date_str):
    """
    Wrapper to extract temporal features.
    """
    return calculate_temporal_metrics(date_str)
