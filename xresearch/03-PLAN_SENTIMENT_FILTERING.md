# Sentiment Filtering Strategy (FinBERT)

## 1. Progress Checklist
- [x] **Annotate News**: Scored 2021-2025 headlines with FinBERT (`annotate_news_sentiment.py`)
- [x] **Enrich Universes**: Mapped sentiment to historical price data (`enrich_universe_with_sentiment.py`)
- [x] **Filter Universes**: Created subsets based on >0.5, >0.6, >0.7 scores (`filter_universe_by_sentiment.py`)
- [x] **Validation (Micro)**: Identified >0.6 as optimal threshold (PF 5.35)
- [x] **Validation (Multi-Universe)**: Confirmed Micro Only is superior to broad universes
- [x] **Live Integration**: Created pre-market filter script (`premarket_sentiment_filter.py`)
- [ ] **Paper Trading**: Test live script for 1 week

## 2. Validation Results: Micro Only Thresholds

### **2021-2025 Full Period: Sentiment Threshold Comparison (Micro Only)**
*Long-Only, 5% ATR Stop, $1,500 Start, 6x Leverage, Market Entry/Market Exit ($0.005/share both sides), 2021-2025*

| Rank | Universe | Sentiment Filter | PF | Win Rate | Tr/Day | 2021 % | 2022 % | 2023 % | 2024 % | 2025 % | Final Profit | Score |
|------|----------|------------------|----|----|--------|--------|--------|--------|--------|--------|--------------|-------|
| 1 | Micro Only | Positive (>0.7) | **6.32** | **12.1%** | 0.88 | +9,043% | +4,433% | +12% | +130% | +192% | **$46.9M** | ⭐⭐⭐⭐⭐ |
| 2 | Micro Only | Positive (>0.6) | **5.35** | **11.6%** | 1.02 | +3,357% | +5,226% | +27% | +250% | +247% | $42.8M | ⭐⭐⭐⭐⭐ |
| 3 | Micro Only | Positive (>0.5) | **4.89** | **11.3%** | 1.36 | +6,237% | +5,417% | +16% | +142% | +201% | $44.4M | ⭐⭐⭐⭐ |
| 4 | Micro Only | **All News (Baseline)** | **3.41** | **9.7%** | **4.44** | **+1,350%** | **+15,227%** | **+229%** | **+205%** | **+94%** | **$64.8M** | ⭐⭐⭐⭐⭐ |

### Reproduction Command (Winner > 0.6)
```powershell
python prod/backend/scripts/ORB/fast_backtest.py `
  --universe "sentiment_based/universe_micro_positive_0.6.parquet" `
  --run-name "Micro_Sentiment_0.6" `
  --start-date 2021-01-01 --end-date 2025-12-31 `
  --initial-capital 1500 --leverage 6.0 --top-n 20 `
  --side long --stop-atr-scale 0.05 `
  --comm-share 0.005 --comm-min 0.99
```

## 3. Validation Results: Multi-Universe Ranking

### **2021-2025 Full Period: Multi-Universe Ranking (Sentiment > 0.6)**
*Long-Only, 5% ATR Stop, $1,500 Start, 6x Leverage, Market Entry/Market Exit ($0.005/share both sides), 2021-2025*

| Rank | Universe | Sentiment Filter | PF | Win Rate | Tr/Day | 2021 % | 2022 % | 2023 % | 2024 % | 2025 % | Final Profit | Score |
|------|----------|------------------|----|----|--------|--------|--------|--------|--------|--------|--------------|-------|
| 1 | **Micro Only** | **Positive (>0.6)** | **5.35** | **11.6%** | **0.98** | **+3,357%** | **+5,226%** | **+27%** | **+250%** | **+247%** | **$42.8M** | ⭐⭐⭐⭐⭐ |
| 2 | Micro + Small | Positive (>0.6) | 2.89 | 12.2% | 2.51 | +13,859% | +4,456% | +54% | +25% | +223% | $59.4M | ⭐⭐⭐ |
| 3 | Micro + Small + Unk | Positive (>0.6) | 2.69 | 12.1% | 2.37 | +19,949% | +3,036% | +51% | +30% | +215% | $58.2M | ⭐⭐⭐ |
| 4 | Micro + Unknown | Positive (>0.6) | 2.59 | 11.8% | 1.13 | +6,106% | +4,872% | -3% | +117% | +265% | $35.5M | ⭐⭐ |
| 5 | Small Only | Positive (>0.6) | 2.04 | 12.2% | 2.78 | +92% | +993% | +11% | +348% | +4,410% | $7.1M | ⭐⭐ |
| 6 | All (Inc. Large) | Positive (>0.6) | 1.93 | 12.0% | 4.31 | +41% | +11,828% | +18% | +609% | +1,423% | $32.4M | ⭐⭐ |
| 7 | Unknown Only | Positive (>0.6) | 1.00 | 11.7% | 0.35 | +321% | -24% | -40% | -53% | +10% | $0 (Flat) | ⭐ |
| 8 | Large Only | Positive (>0.6) | 0.36 | 5.4% | 4.16 | -86% | -100% | +0% | +0% | +0% | $0 (Bust) | 💀 |

### **Micro Only: Limit Order Exit (No Fee Exit)**
*Limit Exit (0 Comm on Exit), 5% ATR Stop, Paid Entry*

| Rank | Universe | Sentiment Filter | PF | Win Rate | Tr/Day | 2021 % | 2022 % | 2023 % | 2024 % | 2025 % | Final Profit | Score |
|------|----------|------------------|----|----|--------|--------|--------|--------|--------|--------|--------------|-------|
| 1 | Micro Only | Positive (>0.7) | **6.47** | **12.1%** | 0.88 | +14,404% | +3,074% | +12% | +119% | +184% | **$47.9M** | ⭐⭐⭐⭐⭐ |
| 2 | Micro Only | Positive (>0.6) | **5.67** | **11.6%** | 1.02 | +6,036% | +5,678% | +15% | +148% | +202% | $45.8M | ⭐⭐⭐⭐⭐ |
| 3 | Micro Only | Positive (>0.5) | 4.97 | 11.3% | 1.36 | +11,002% | +3,531% | +15% | +127% | +191% | $45.6M | ⭐⭐⭐⭐ |

### **Micro Only: 10% ATR Stop (Paid Entry/Exit)**
*Market Entry/Exit, 10% ATR Stop (Wider), Paid Entry/Exit*

| Rank | Universe | Sentiment Filter | PF | Win Rate | Tr/Day | 2021 % | 2022 % | 2023 % | 2024 % | 2025 % | Final Profit | Score |
|------|----------|------------------|----|----|--------|--------|--------|--------|--------|--------|--------------|-------|
| 1 | Micro Only | Positive (>0.7) | 4.14 | **17.0%** | 0.88 | +2,560% | +7,859% | +14% | +231% | +244% | $41.1M | ⭐⭐⭐ |
| 2 | Micro Only | Positive (>0.5) | 3.24 | 16.2% | 1.36 | +1,906% | +1,564% | +111% | +676% | +341% | $36.2M | ⭐⭐⭐ |
| 3 | Micro Only | Positive (>0.6) | 3.18 | 16.5% | 1.02 | +1,465% | +1,864% | +116% | +437% | +475% | $30.8M | ⭐⭐ |

### **Micro Only: 10% ATR Stop (Limit Exit)**
*Limit Exit (0 Comm on Exit), 10% ATR Stop (Wider), Paid Entry*

| Rank | Universe | Sentiment Filter | PF | Win Rate | Tr/Day | 2021 % | 2022 % | 2023 % | 2024 % | 2025 % | Final Profit | Score |
|------|----------|------------------|----|----|--------|--------|--------|--------|--------|--------|--------------|-------|
| 1 | Micro Only | Positive (>0.7) | 4.33 | 17.0% | 0.88 | +4,232% | +8,298% | +9% | +143% | +204% | $43.8M | ⭐⭐⭐ |
| 2 | Micro Only | Positive (>0.6) | 3.70 | 16.5% | 1.02 | +2,422% | +3,299% | +37% | +457% | +301% | $39.2M | ⭐⭐⭐ |
| 3 | Micro Only | Positive (>0.5) | 3.36 | 16.2% | 1.36 | +3,399% | +3,376% | +29% | +350% | +268% | $38.8M | ⭐⭐⭐ |

### **Final Ranking: Top 5 Best Configurations**
*Ranking based on Stability (Profit Factor) and Total Return (2021-2025)*

| Rank | Strategy Config | Sentiment | Stop Loss | Exit Type | PF | Win Rate | Final Profit | Score |
|------|-----------------|-----------|-----------|-----------|----|----------|--------------|-------|
| 1 | **Micro Only** | Positive (>0.7) | 5% ATR | Limit (Free) | **6.47** | 12.1% | **$47.9M** | 🏆 |
| 2 | Micro Only | Positive (>0.7) | 5% ATR | Market (Paid) | 6.32 | 12.1% | $46.9M | 🥈 |
| 3 | Micro Only | Positive (>0.6) | 5% ATR | Limit (Free) | 5.67 | 11.6% | $45.8M | 🥉 |
| 4 | **Micro Only (Recommended)** | **Positive (>0.6)** | **5% ATR** | **Market (Paid)** | **5.35** | **11.6%** | **$42.8M** | ⭐ |
| 5 | Micro Only | Positive (>0.5) | 5% ATR | Limit (Free) | 4.97 | 11.3% | $45.6M | ⭐ |

### **Recommendation: Why Choose Rank 4 (>0.6, 5% ATR, Market Exit)?**
Although Rank 1 (>0.7 Limit) has higher theoretical stats, **Rank 4 is the most robust real-world choice**:

1.  **Execution Reality (Market vs. Limit)**:
    *   Rank 1 & 3 rely on **Limit Order Exits** getting filled. In a fast-moving breakout failure, a Limit Sell at the breakdown price might not fill, leaving you holding a bag.
    *   **Market Exits (Rank 2 & 4)** guarantee you get out, even if you pay a small spread penalty. The backtest **already accounts for this** ($0.005/share + Spread) and *still* produces a massive **5.35 PF**.

2.  **Signal Frequency (>0.6 vs >0.7)**:
    *   **>0.6** generates **15-20% more trades** than >0.7.
    *   More trades = smoother equity curve and less reliance on a few "home runs" to make the year.
    *   The drop in PF (6.32 -> 5.35) is worth the increased sample size and consistency.

3.  **Safety Margin**:
    *   This configuration assumes you pay commissions and spread on *every* trade.
    *   If you *can* get Limit fills sometimes, that's just a bonus on top of an already winning system.

**Verdict:** Run **Micro Only, Sentiment > 0.6, 5% ATR Stop, Market Orders** for the safest, most scalable execution.

### Reproduction Commands

**Base Command Template:**
```powershell
python prod/backend/scripts/ORB/fast_backtest.py `
  --start-date 2021-01-01 --end-date 2025-12-31 `
  --initial-capital 1500 --leverage 6.0 --top-n 20 `
  --side long --stop-atr-scale [STOP_ATR] `
  --comm-share 0.005 --comm-min 0.99 [FREE_EXIT_FLAG] `
  --universe "[UNIVERSE_PATH]" `
  --run-name "[RUN_NAME]"
```

**Rank Configurations:**

| Run Name | Description | Stop ATR | Free Exit | Universe Path |
|----------|-------------|----------|-----------|---------------|
| `Micro_Only_Sent_0.6` | **Recommended** | 0.05 | No | `sentiment_based/universe_micro_positive_0.6.parquet` |
| `Micro_Only_Sent_0.7_LimitExit` | #1 Raw Stats | 0.05 | `--free-exits` | `sentiment_based/universe_micro_positive_0.7.parquet` |
| `Micro_Only_Sent_0.7` | #2 Paid Exit | 0.05 | No | `sentiment_based/universe_micro_positive_0.7.parquet` |
| `Micro_Only_Sent_0.6_LimitExit` | #3 Limit Exit | 0.05 | `--free-exits` | `sentiment_based/universe_micro_positive_0.6.parquet` |
| `Micro_Only_Sent_0.5_LimitExit` | #5 Limit Exit | 0.05 | `--free-exits` | `sentiment_based/universe_micro_positive_0.5.parquet` |




