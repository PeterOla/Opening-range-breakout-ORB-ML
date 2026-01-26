# Scenario: Entry Cutoff at 15:30 ET

## Hypothesis
Canceling pending orders if not triggered by **15:30 ET** (30 mins before close) will filter out "trap" breakouts that occur too late in the day to follow through, potentially improving Win Rate and Profit Factor.

## Configuration
- **Run Name**: `limit_entry_1530`
- **Cutoff Time**: 15:30 ET
- **Base Strategy**: 5% ATR Stop, $1500 Initial, Compounding

## Results vs Baseline (2021)

| Metric | Baseline (No Cutoff) | Cutoff 15:30 | Delta |
| :--- | :--- | :--- | :--- |
| **Final Equity** | $1,226,430 | $1,203,369 | **-1.9%** |
| **Total Trades** | 706 | 698 | -8 trades |
| **Win Rate** | 12.8% | 12.6% | -0.2pp |
| **Profit Factor** | 1.69 | 1.70 | **+0.01** |

## Analysis
1.  **Impact is Minimal**: Only 8 trades were filtered out by the 15:30 cutoff over the entire year.
2.  **Profit Factor Improved**: The slight rise in PF (1.70 vs 1.69) suggests the filtered trades were, on net, losing or sub-par trades.
3.  **Equity Decreased**: Despite better efficiency per trade, missing those 8 trades reduced total compounding volume slightly, resulting in marginally lower final equity.

## Conclusion
Implementing a **15:30 ET Entry Cutoff** is neutral-to-positive for efficiency (Profit Factor) but neutral-to-negative for absolute total return. Given the negligible difference, it is a safe "hygiene" rule to avoid holding pending orders into the close, but not a major performance driver.
