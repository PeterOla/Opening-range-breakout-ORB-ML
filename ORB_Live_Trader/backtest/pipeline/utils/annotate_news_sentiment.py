"""
Annotate News Headlines with Sentiment Scores (Hugging Face FinBERT)
=====================================================================

This script:
1. Uses Hugging Face FinBERT model to score sentiment
2. Assigns Positive/Negative/Neutral labels
3. Saves annotated news with sentiment scores

Model: ProsusAI/finbert (Financial sentiment analysis)
Output: positive_score, negative_score, neutral_score, sentiment label
"""

import pandas as pd
from pathlib import Path
import sys
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from tqdm import tqdm
import warnings

warnings.filterwarnings('ignore')

class SentimentAnnotator:
    """Sentiment analysis using Hugging Face transformers."""
    
    def __init__(self, model_name: str = "ProsusAI/finbert", device: str = None):
        """
        Initialize sentiment model.
        
        Args:
            model_name: Hugging Face model identifier
            device: 'cuda', 'cpu', or None (auto-detect)
        """
        self.model_name = model_name
        
        # Auto-detect device
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device
        
        print(f"\nLoading model: {model_name}")
        print(f"Device: {self.device}")
        
        # Load tokenizer and model
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.to(self.device)
        self.model.eval()
        
        # Get label mapping (FinBERT: 0=positive, 1=negative, 2=neutral)
        self.id2label = self.model.config.id2label
        print(f"Label mapping: {self.id2label}")
        print("✓ Model loaded successfully\n")
    
    def predict_batch(self, headlines: list[str], batch_size: int = 32) -> list[dict]:
        """
        Predict sentiment for batch of headlines.
        
        Args:
            headlines: List of news headlines
            batch_size: Batch size for inference
            
        Returns:
            List of dicts with sentiment scores and labels
        """
        results = []
        
        with torch.no_grad():
            for i in tqdm(range(0, len(headlines), batch_size), desc="Processing batches"):
                batch = headlines[i:i+batch_size]
                
                # Tokenize
                inputs = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors='pt'
                ).to(self.device)
                
                # Predict
                outputs = self.model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
                
                # Extract scores
                for prob in probs.cpu().numpy():
                    # FinBERT: 0=positive, 1=negative, 2=neutral
                    positive_score = float(prob[0])
                    negative_score = float(prob[1])
                    neutral_score = float(prob[2])
                    
                    # Determine dominant sentiment
                    max_idx = prob.argmax()
                    sentiment = self.id2label[max_idx].capitalize()
                    
                    results.append({
                        'positive_score': positive_score,
                        'negative_score': negative_score,
                        'neutral_score': neutral_score,
                        'sentiment': sentiment
                    })
        
        return results
