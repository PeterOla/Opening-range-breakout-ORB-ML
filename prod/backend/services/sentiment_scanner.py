"""
Sentiment Scanner Service.

Implements the "Sentiment First" hypothesis validated in research (Jan 2026).
Pipeline:
1.  **Define Universe**: Micro-caps (Shares < 50M) from DB.
2.  **Fetch News**: Last 24h headlines for all micro-caps via Alpaca.
3.  **Score Sentiment**: Use FinBERT to identify > 0.90 positive sentiment.
4.  **Filter**: Return only the subset of symbols with high sentiment.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import torch
from transformers import pipeline
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

from core.config import settings
from db.database import SessionLocal
from db.models import Ticker

logger = logging.getLogger(__name__)

# Model Singleton (Heavy to load, so we cache it)
_SENTIMENT_PIPELINE = None

def load_sentiment_model():
    """Load FinBERT pipeline if not already loaded."""
    global _SENTIMENT_PIPELINE
    if _SENTIMENT_PIPELINE is None:
        logger.info("Loading FinBERT model (ProsusAI/finbert)...")
        try:
            # Use GPU if available
            device = 0 if torch.cuda.is_available() else -1
            _SENTIMENT_PIPELINE = pipeline(
                "sentiment-analysis", 
                model="ProsusAI/finbert", 
                device=device
            )
            logger.info(f"FinBERT loaded successfully on device {device}.")
        except Exception as e:
            logger.error(f"Failed to load FinBERT: {e}")
            raise e
    return _SENTIMENT_PIPELINE

def get_micro_cap_universe(limit_shares: int = 50_000_000) -> List[str]:
    """Get list of symbols with shares outstanding < limit. Falls back to parquet."""
    symbols = []
    
    # 1. Try Database
    try:
        db = SessionLocal()
        tickers = db.query(Ticker.symbol).filter(
            Ticker.float.isnot(None),
            Ticker.float > 0,
            Ticker.float < limit_shares
        ).all()
        symbols = [t.symbol for t in tickers]
        db.close()
        
        if symbols:
            logger.info(f"Retrieved {len(symbols)} micro-cap symbols from DB.")
            return symbols
    except Exception as e:
        logger.warning(f"DB Universe fetch failed: {e}")

    # 2. Try Fallback (Backtest Universe)
    try:
        import pandas as pd
        from pathlib import Path
        
        # prod/backend/services/sentiment_scanner.py -> ... -> data
        root = Path(__file__).resolve().parents[3] 
        fallback_path = root / "data" / "backtest" / "orb" / "universe" / "universe_micro_full.parquet"
        
        if fallback_path.exists():
            logger.info(f"Using fallback universe: {fallback_path}")
            df = pd.read_parquet(fallback_path)
            if "symbol" in df.columns:
                return df["symbol"].tolist()
            elif "ticker" in df.columns:
                return df["ticker"].tolist()
    except Exception as e:
        logger.error(f"Fallback universe failed: {e}")

    return []

def fetch_universe_news(symbols: List[str], lookback_hours: int = 24) -> Dict[str, List[str]]:
    """
    Fetch news headlines for the given symbols (Last N hours).
    Returns: {symbol: [headline, headline, ...]}
    """
    if not symbols:
        return {}

    try:
        client = NewsClient(api_key=settings.ALPACA_API_KEY, secret_key=settings.ALPACA_API_SECRET)
    except Exception as e:
        logger.error(f"Failed to init Alpaca NewsClient: {e}")
        return {}
    
    end = datetime.now()
    start = end - timedelta(hours=lookback_hours)
    
    # Alpaca News Request Batching
    # Documentation suggests request by list of symbols works.
    # We will batch to be safe and avoid massive URL lengths or timeouts.
    batch_size = 40 
    symbol_news_map = {}
    
    logger.info(f"Fetching news for {len(symbols)} symbols ({lookback_hours}h lookback)...")
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        try:
            req = NewsRequest(
                symbols=",".join(batch),
                start=start,
                end=end,
                limit=50, # Items per response (per request, heavily filtered by time)
                include_content=False, # We only need headlines
                sort="DESC"
            )
            resp = client.get_news(req)
            
            # Alpaca v2 SDK NewsSet structure: resp.data['news']
            news_items = resp.data.get('news', []) if hasattr(resp, 'data') else []
            
            if news_items:
                for item in news_items:
                    if item.headline:
                        for s in item.symbols:
                            # Only map back to symbols we actually requested (Api can return others mentioned)
                            if s in batch: 
                                if s not in symbol_news_map:
                                    symbol_news_map[s] = []
                                symbol_news_map[s].append(item.headline)
                                
        except Exception as e:
            # Check for 429 or other errors, but continue
            logger.warning(f"News fetch error batch {i}-{i+batch_size}: {e}")
            
    return symbol_news_map

def filter_by_sentiment(symbol_headlines: Dict[str, List[str]], threshold: float = 0.90) -> List[str]:
    """
    Score news and return symbols with at least one headline > threshold positive.
    """
    if not symbol_headlines:
        return []

    pipeline = load_sentiment_model()
    candidates = []
    
    total_headlines = sum(len(h) for h in symbol_headlines.values())
    logger.info(f"Scoring {total_headlines} headlines for {len(symbol_headlines)} symbols...")
    
    # Process
    for sym, headlines in symbol_headlines.items():
        if not headlines:
            continue
            
        # Optimization: Take distinct headlines to avoid duplicate scoring
        unique_headlines = list(set(headlines))
        
        try:
            results = pipeline(unique_headlines)
            # results: [{'label': 'positive', 'score': 0.99}, ...]
            
            is_candidate = False
            for res in results:
                if res['label'].lower() == 'positive' and res['score'] >= threshold:
                    is_candidate = True
                    # Log the winning headline for debugging
                    logger.debug(f"Candidate {sym}: {unique_headlines[results.index(res)]} ({res['score']:.2f})")
                    break
            
            if is_candidate:
                candidates.append(sym)
                
        except Exception as e:
            logger.error(f"Scoring error for {sym}: {e}")
            
    return candidates

async def scan_sentiment_candidates(threshold: float = 0.90) -> List[str]:
    """
    Main Orchestrator.
    Returns list of symbols that pass the Sentiment Filter.
    """
    # 1. Get Universe
    universe = get_micro_cap_universe()
    if not universe:
        logger.warning("Sentiment Scanner: Empty universe.")
        return []
        
    # 2. Fetch News
    news_map = fetch_universe_news(universe)
    if not news_map:
        logger.info("Sentiment Scanner: No news found.")
        return []
        
    # 3. Score & Filter
    candidates = filter_by_sentiment(news_map, threshold=threshold)
    
    logger.info(f"Sentiment Scanner: Found {len(candidates)} candidates > {threshold}")
    return candidates
