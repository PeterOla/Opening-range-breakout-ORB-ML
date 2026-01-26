# ORB Backtest Pipeline

This directory contains the complete backtesting pipeline for the Opening Range Breakout (ORB) strategy, including data ingestion, sentiment scoring, universe enrichment, and fast simulation.

## Directory Structure

```
backtest/
├── fast_backtest.py       # Main Simulation Engine (Fast Vectorized Backtester)
├── pipeline/              # Data Pipeline Scripts
│   ├── fetch_news.py      # 1. Fetch historical news from Alpaca
│   ├── score_news.py      # 2. Score news using FinBERT
│   ├── enrich_universe.py # 3. Generate actionable universe with price data
│   └── utils/
│       └── annotate_news_sentiment.py # Sentiment Model Helper
└── data/                  # Local Data Storage
    ├── news/              # Raw and Scored News Parquet files
    └── universe/          # Enriched Universe Parquet files
```

## Usage Workflow

### 1. Data Pipeline (Rebuild Universe)
If starting from scratch:

```bash
# 1. Fetch News
python pipeline/fetch_news.py

# 2. Score Sentiment
python pipeline/score_news.py

# 3. Enrich Universe (Create actionable candidates)
python pipeline/enrich_universe.py --mode rolling_24h
```

### 2. Run Backtest
Run the simulation on the generated universe:

```bash
python fast_backtest.py \
    --universe research_2021_sentiment_ROLLING24H/universe_sentiment_0.9.parquet \
    --run-name verify_2021 \
    --initial-capital 1500 \
    --stop-atr-scale 0.05 \
    --leverage 6.0
```

## Configuration
- **Initial Capital**: Default $1500
- **Universe**: Defaults to `data/universe` directory
- **Outputs**: Results are saved to `data/runs/`
