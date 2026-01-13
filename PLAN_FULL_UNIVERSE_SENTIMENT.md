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

- [x] **Data Collection**: Done. `data/research/news/news_micro_full_1y.parquet` (2234 items).
- [ ] **Sentiment Scoring**: Running... `prod/backend/scripts/research/score_full_universe_news.py`.
- [ ] **Universe Enrichment**: Script `prod/backend/scripts/research/enrich_sentiment_universe.py` created.
- [ ] **Backtest Execution**: Run `fast_backtest.py` using the sentiment universe.
- [ ] **Comparison**: Fill out the comparison table below.

## 6. Comparison Table (Expected Output)

| Metric | Baseline (Technical First) | Experimental (Sentiment First) | Delta |
| :--- | :--- | :--- | :--- |
| **Total Trades** | *e.g., 450* | TBD | |
| **Win Rate** | *e.g., 41%* | TBD | |
| **Profit Factor** | *e.g., 1.95* | TBD | |
| **Avg PnL per Trade** | *e.g., $120* | TBD | |
| **Max Drawdown** | *e.g., -15%* | TBD | |
| **Sharpe Ratio** | *e.g., 1.2* | TBD | |

## 7. Status
- **Current State**: On Hold.
- **Active Strategy**: Technical Rank First (Gap) -> Sentiment.
