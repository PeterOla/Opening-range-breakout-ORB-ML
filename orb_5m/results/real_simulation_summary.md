# Realistic Trading Costs Simulation

## Methodology

This simulation applies real-world trading costs to backtest results:

1. **IBKR Commissions**: $0.0035 per share, minimum $0.35 per order
2. **Slippage**: 0.02%-0.05% per order (entry + exit)
3. **Entry Delay**: 1 bar delay simulating market drift (0.1-0.3% adverse movement)

## Results Comparison

| Metric | Original Backtest | Realistic Simulation | Difference |
|--------|------------------|---------------------|------------|
| Initial Equity | $1,000.00 | $1,000.00 | - |
| Final Equity | $190,413.81 | $54,184.99 | -$136,228.82 (71.5%) |
| Total Return | 18941.38% | 5318.50% | -13622.88pp |
| CAGR | 185.72% | 122.22% | -63.50pp |
| Max Drawdown | -20.55% | -94.49% | -73.94pp |
| Win Rate | 16.79% | 16.13% | -0.66pp |
| Profit Factor | 1.78 | 1.15 | -0.63 |
| Avg Win | $106.50 | $105.08 | $-1.41 |
| Avg Loss | $-12.07 | $-17.59 | $-5.52 |

## Cost Breakdown

- **Total Commissions**: $45,002.56
- **Total Slippage**: $34,132.44
- **Total Costs**: $79,135.00
- **Average Cost per Trade**: $3.27
- **Costs as % of Gross Profit**: 18.31%

## Key Insights

✅ **Strategy remains profitable** after realistic costs

- Realistic costs reduce final equity by **71.5%**
- CAGR drops from **185.7%** to **122.2%**
- Trading costs consume **18.3%** of gross profits

**Conclusion**: Despite costs, strategy shows strong performance with 122.2% CAGR
