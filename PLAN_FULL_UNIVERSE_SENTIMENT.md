# Plan: Full Universe Sentiment Scanning (Research)

## 1. Hypothesis
Scanning the entire universe (2,744 Micro-caps) for positive sentiment *before* looking at technicals might identify high-quality setups that haven't hit the radar yet (Pre-momentum/Pre-Gap).

## 2. Deviation from Baseline
- **Baseline (Validated)**: Technical Candidates (Gap/RVOL) -> Sentiment Filter.
- **Proposed (Experimental)**: Full Universe -> Sentiment Filter -> Technical Check.

## 3. Risks
- **Volume/Liquidity**: High sentiment stocks might lack the liquidity required for size.
- **Noise**: Might pick up "pump" news on dead stocks.
- **API Load**: Requires 50x more API calls (2744 vs 50).

## 4. Backtest Strategy
1.  Run the standard ORB backtest.
2.  BUT, use a universe constructed *only* from Sentiment > 0.6 (ignoring technical history).
3.  Compare PF and Drawdown against the Baseline.

## 5. Progress Tracking

- [x] **Data Collection**: Done. Fetched 40,709 news items for 2021 (Full Year).
- [x] **Sentiment Scoring**: Done.
- [x] **Universe Construction**: Done. `research_2021_sentiment/` created.
- [x] **Universe Enrichment**: Done. Generated thresholds 0.60, 0.70, 0.80, 0.90, 0.95.
- [x] **Backtest Execution**: Run `fast_backtest.py` on all 5 variations.
- [x] **Comparison**: Findings documented in Section 7.

## 6. Comparison Table (Expected Output)

| Metric | Baseline (Technical First) | Experimental (Sentiment First) | Delta |
| :--- | :--- | :--- | :--- |
| **Total Trades** | *e.g., 450* | TBD | |
| **Win Rate** | *e.g., 41%* | TBD | |
| **Profit Factor** | *e.g., 1.95* | TBD | |
| **Avg PnL per Trade** | *e.g., $120* | TBD | |
| **Max Drawdown** | *e.g., -15%* | TBD | |
| **Sharpe Ratio** | *e.g., 1.2* | TBD | |

## 7. Findings - Top 20 Concentration (Jan 13, 2026)

**Experiment:** Batch Backtest 2021 (Full Year).
**Parameters**: Starting Equity \$1,500, Leverage 6.0x, Top-20, Compounding, Market Entry/Exit, Comm $0.005/share (min $0.99).

| Rank | Universe | Sentiment Filter | PF | Win Rate | Tr/Day | Max DD | Final Profit | Score |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | Research 2021 | **> 0.90** | **10.04** | **17.2%** | **4.1** | **-17.5%** | **$54.1M** | **S** |
| 2 | Research 2021 | > 0.80 | 7.73 | 15.5% | 6.8 | -23.1% | $32.0M | A |
| 3 | Research 2021 | > 0.70 | 7.11 | 14.9% | 8.5 | -14.0% | $16.7M | B |
| 4 | Research 2021 | > 0.60 | 6.71 | 15.0% | 9.4 | -18.3% | $15.8M | B- |
| 5 | Research 2021 | > 0.95 | 24.38 | 17.1% | 0.5 | -47.8% | $6.4M | C+ |

### Observations
1. **The "Sweet Spot" is 0.90**: This threshold filters out enough noise to achieve a double-digit Profit Factor (10.04) while retaining enough trade frequency (4 trades/day) to allow aggressive compounding.
2. **Diminishing Returns at 0.95**: While the Profit Factor jumps to an incredible 24.38, the trade frequency drops to ~1 trade every 2 days. This lack of opportunity cost (money sitting idle) results in significantly lower total profit ($6.4M vs $54.1M) despite the higher quality setups.
3. **Baseline Improvement**: Even the lowest threshold (> 0.60) generated substantial returns, validating the hypothesis that pre-filtering by sentiment is a viable strategy for micro-cap ORB.

## 8. Findings - Top 5 Concentration (Jan 13, 2026)

**Experiment:** Batch Backtest 2021, but **Top-5** instead of Top-20.
**Hypothesis:** Concentrating capital into the top 5 highest RVOL setups might improve compounding or filter out lower quality trades.
**Parameters:** Same as above (Top-5 selected by RVOL Rank).

| Rank | Universe | Sentiment Filter | PF | Win Rate | Tr/Day | Max DD | Final Profit | Delta (vs Top 20) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | Research 2021 | **> 0.90** | **10.03** | **17.6%** | **3.5** | **-16.2%** | **$50.7M** | **-6%** |
| 2 | Research 2021 | > 0.80 | 8.70 | 15.5% | 4.4 | -35.7% | $16.4M | -49% |
| 3 | Research 2021 | > 0.70 | 10.46 | 15.3% | 4.7 | -42.0% | $12.0M | -28% |
| 4 | Research 2021 | > 0.60 | 10.52 | 15.0% | 4.7 | -43.3% | $8.9M | -44% |
| 5 | Research 2021 | > 0.95 | 24.38 | 17.1% | 0.5 | -47.8% | $6.4M | 0% |

### Observations (Top 5 vs Top 20)
1. **Profit Factor Improvement (Lower Thresholds)**: For thresholds 0.60 and 0.70, reducing to Top 5 significantly **boosted** the Profit Factor (from ~6.7 to ~10.5). This suggests the "tail" of the Top-20 (ranks 6-20) contained many lower-quality trades that dragged down performance.
2. **Total Profit Decline**: Despite higher efficiency per trade, the **Total Profit dropped** across the board (except for 0.95 which had no change). This is purely a function of **Opportunity Cost**; with $1,500 starting equity, limiting to 5 trades often left buying power unused on active days.
3. **0.90 Stability**: The optimal threshold (0.90) remained remarkably stable, with the Profit Factor holding at 10.0 and Win Rate increasing slightly to 17.6%. The slight profit drop (-6%) indicates that ranks 6-20 provided some value, but the core performance comes from the top tier.
4. **0.95 Validity**: The 0.95 threshold had fewer than 5 trades per day anyway, so the Top-5 constraint had zero impact.

## 9. Deep Dive: Top 20 vs Top 5 (Threshold > 0.90) (Jan 14, 2026)

Detailed comparison of the optimal threshold (0.90). Data source: `daily_performance.parquet` & `simulated_trades.parquet`.

### A. General Stats
| Metric | Top 20 | Top 5 | Insight |
| :--- | :--- | :--- | :--- |
| **Total Profit** | $54,114,647 | $50,669,346 | Top 20 wins by 6% (Volume game). |
| **Avg Win** | $392,834 | $446,683 | Top 5 trades are 13% larger on average. |
| **Avg Loss** | $-8,159 | $-9,497 | Top 5 losses are slightly larger due to concentration. |
| **Max Consec. Losing Trades** | **20** | **14** | **Top 5 is psychologically easier** (shorter losing streaks). |
| **Max Consec. Losing Days** | **9** | **9** | Identical. Expect nearly 2 weeks of red days occasionally. |

### B. Monthly Returns (2021)
| Month | Top 20 PnL | Top 5 PnL | Note |
| :--- | :--- | :--- | :--- |
| **Jan** | $41 | $-276 | Flat start. |
| **Feb** | $5,371 | $3,492 | Slow build. |
| **Mar** | $75,706 | $40,930 | |
| **Apr** | $104,688 | $71,252 | First 6-figure month (Top 20). |
| **May** | $544,672 | $377,294 | Momentum builds. |
| **Jun** | $468,981 | $440,972 | |
| **Jul** | $4.7M | $4.2M | First multi-million month. |
| **Aug** | $424,092 | $346,995 | Pullback/Consolidation. |
| **Sep** | $4.4M | $3.9M | |
| **Oct** | $5.7M | $5.8M | Top 5 actually outperformed in Oct. |
| **Nov** | **$28.9M** | **$26.9M** | **The "God Month"**: 50% of yearly profit came in Nov. |
| **Dec** | $8.6M | $8.4M | Strong finish. |

### C. Day of Week Performance
| Day | Top 20 (Total) | Top 5 (Total) | Note |
| :--- | :--- | :--- | :--- |
| **Monday** | $11.8M | $11.3M | Strong start. |
| **Tuesday** | **$22.0M** | **$20.2M** | **Best Day**: Tuesday is the moneymaker. |
| **Wednesday** | $14.3M | $14.0M | Solid. |
| **Thursday** | $0.98M | $0.25M | **Weakest Link**: Avoid Thursdays? |
| **Friday** | $4.8M | $4.8M | Decent. |

### D. Decision Matrix
- **Choose Top 20 if**: You want maximum absolute profit ($54M) and can tolerate longer losing streaks (20 in a row).
- **Choose Top 5 if**: You prefer psychological safety (shorter streaks: 14) and higher efficiency per trade, accepting a small convenient profit cut (-6%).
- **Warning**: **Thursday** performs significantly worse than other days ($20k/day avg vs $468k/day for Tuesday). Consider sizing down or skipping.

## 10. Provenance & Reproducibility

### A. Universe Generation (The "Micro" List)
- **Script**: `prod/backend/scripts/data/generate_micro_universe_all.py`
- **Output**: `data/backtest/orb/universe/universe_micro_full.parquet` (2,744 symbols)
- **Criteria**: 
  - **Shares Outstanding < 50,000,000 (50M)**
  - Source: `data/raw/historical_shares.parquet` (Historical Alpaca data)

### B. News Fetching
- **Script**: `prod/backend/scripts/research/fetch_full_universe_news.py`
- **Output**: `data/research/news/news_micro_full_1y.parquet`
- **Logic**: 
  - Scans all 2,744 symbols for news in 2021.
  - Uses "Time-Walking" pagination (iterating backwards) to bypass Alpaca limit of 100 pages.

### C. Sentiment Scoring
- **Script**: `prod/backend/scripts/research/score_full_universe_news.py`
- **Output**: `data/research/news/news_micro_full_1y_scored.parquet`
- **Model**: `ProsusAI/finbert` (Hugging Face)
- **Logic**:
  - Checks `headline` only (Summaries often noisy).
  - Annotates with `positive_score` (0.00 to 1.00).

### D. Universe Construction (Enrichment)
- **Script**: `prod/backend/scripts/research/enrich_sentiment_universe.py`
- **Output Folder**: `data/backtest/orb/universe/research_2021_sentiment/`
- **Variations Generated**:
  1. `universe_sentiment_0.60.parquet`
  2. `universe_sentiment_0.70.parquet`
  3. `universe_sentiment_0.80.parquet`
  4. `universe_sentiment_0.90.parquet`
  5. `universe_sentiment_0.95.parquet`

## 11. Experiment: Stop Loss Sensitivity (10% vs 5% ATR) (Jan 14, 2026)

**Question**: Does a wider stop (10% ATR) allow enough "breathing room" to catch more winners, or does it just increase losses?
**Context**: Validated on **Top 5**, Sentiment **> 0.90**.

| Metric | Baseline (5% ATR) | Experiment (10% ATR) | Delta |
| :--- | :--- | :--- | :--- |
| **Win Rate** | 17.6% | **22.7%** | +5.1% (More survivors) |
| **Profit Factor** | **10.03** | 8.07 | -19% (Less efficient) |
| **Max Drawdown** | **-16.2%** | -28.3% | +75% Risk (Painful) |
| **Total Profit** | $50.7M | **$63.9M** | +26% |

### Conclusion
1.  **Profit vs Pain**: The 10% stop is strictly **more profitable** (+26% total return), proving that many 5% stops were indeed "wicked out" prematurely.
2.  **Risk Profile**: However, the Max Drawdown nearly **doubles** (-28% vs -16%).
3.  **Recommendation**: Stick to **5% ATR** for the live implementation initially. A -16% drawdown is far easier to manage psychologically than -28%, and $50M vs $64M is less relevant than survival. The 8.0+ Profit Factor at 10% suggests we can widen stops later if we need to scale size up and liquidity becomes an issue.

### A. General Stats (Deep Dive)
| Metric | Top 5 (5% Stop) | Top 5 (10% Stop) | Insight |
| :--- | :--- | :--- | :--- |
| **Total Profit** | $50,669,346 | **$63,862,730** | 10% Stop wins by 26%. |
| **Avg Win** | $446,683 | $447,217 | **Identical winners**. The wider stop didn't capture "bigger moves", it just survived more of them. |
| **Avg Loss** | **$-9,497** | $-16,306 | **Losses nearly doubled**. 2x risk distance = 2x loss size. |
| **Max Consec. Losing Trades** | 14 | 14 | Identical. |
| **Max Consec. Losing Days** | 9 | **4** | **Significant stability**. The wider stop prevented "churn" days where everything stopped out. |

## 12. Experiment: Position Sizing (Equal Dollar vs Risk Based) (Jan 14, 2026)

**Objective**: Test if sizing positions based on risk (Stop Distance) is superior to Equal Dollar Allocation.
**Setup**: Top 5, 10% ATR Stop, Long Only.
**Baseline**: Equal Dollar ($64M Profit, -28% DD).

**Results**:
| Sizing Mode | Risk % | Profit | Max DD | Analysis |
|:---|:---:|---:|---:|:---|
| **Equal Dollar (Live)** | N/A | **+$64.0M** | **-28.3%** | **Best Balance.** High return, manageable drawdown. |
| Risk Based | 5% | +$97.5M | -54.4% | **Too Dangerous.** Drawdown is catastrophic. |
| Risk Based | 2% | +$36.0M | -36.0% | **Inferior.** Lower return AND higher risk than Equal Dollar. |
| Risk Based | 1% | +$2.7M | -24.5% | **Too Slow.** Kills the compounding effect completely. |

### Conclusion
1. **Inefficiency of Risk Sizing**: Risk-based sizing paradoxically penalizes the best setups in this momentum strategy. High volatility (ATR) — which often signals a strong breakout — results in smaller position sizes to "normalize" risk, effectively capping the upside of the biggest winners.
2. **Wide Stops Issue**: With a 10% ATR stop, the stop distance is naturally wide. To strictly adhere to a 1% or 2% risk limit, the position size must be heavily reduced, leaving significant buying power idle.
3. **Equal Dollar Superiority**: allocations of `Equity / 5` allow winners to run with meaningful size regardless of their volatility.
4. **Action**: **Rejected**. The live strategy will remain on **Equal Dollar Allocation**.
