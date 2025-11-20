import pandas as pd
from pathlib import Path

from .opening_range import compute_opening_range_for_symbol


def compute_or_rvol_for_symbol(symbol: str, period: int = 14) -> pd.DataFrame:
    """Compute opening-range Relative Volume (RVOL) for a symbol.

    RVOL_t = or_volume_t / mean(or_volume over previous `period` days)

    Returns a DataFrame with at least:
      - date
      - symbol
      - or_volume
      - or_rvol_<period>
    """
    or_df = compute_opening_range_for_symbol(symbol)
    or_df = or_df.sort_values("date").reset_index(drop=True)

    vol = or_df["or_volume"]
    avg_past = vol.rolling(window=period, min_periods=period).mean().shift(1)
    # shift(1): use only *previous* days in the average

    col_name = f"or_rvol_{period}"
    or_df[col_name] = vol / avg_past

    return or_df


if __name__ == "__main__":
    # Tiny manual test on ticker A
    df = compute_or_rvol_for_symbol("A", period=14)
    print(df[["date", "symbol", "or_volume", "or_rvol_14"]].head(25))
