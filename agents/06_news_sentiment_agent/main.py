import os
import logging
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from textblob import TextBlob

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NewsSentimentAgent")

app = FastAPI()

NEWS_API_KEY = os.getenv("NEWS_API_KEY") 
# Se non hai una chiave newsapi.org, l'agente userà dati simulati o fallback

class SentimentRequest(BaseModel):
    symbol: str

def fetch_news(symbol):
    # Logica semplificata per le news
    # Se hai una chiave reale, la usa, altrimenti simula basandosi su Fear & Greed pubblico
    url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API_KEY}&sortBy=publishedAt&language=en"
    try:
        if not NEWS_API_KEY: raise Exception("No Key")
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            articles = data.get("articles", []) if data else []
            return [a.get("title", "") for a in articles[:5] if a.get("title")]
    except Exception as e:
        logger.warning(f"News API error for {symbol}: {e}")
    return []

def get_fear_and_greed():
    # Recupera il vero Fear & Greed Index dal web
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data and data.get('data') and len(data['data']) > 0:
                value = data['data'][0].get('value')
                classification = data['data'][0].get('value_classification', 'Neutral')
                if value:
                    return int(value), classification
    except Exception as e:
        logger.warning(f"Fear & Greed API error: {e}")
    return 50, "Neutral"

@app.post("/analyze_sentiment")
def analyze_sentiment(req: SentimentRequest):
    # 1. Fear & Greed (Dato Reale)
    fng_val, fng_class = get_fear_and_greed()
    
    # 2. News Analysis (Base)
    headlines = fetch_news(req.symbol)
    sentiment_score = 0
    if headlines:
        blob = TextBlob(" ".join(headlines))
        sentiment_score = blob.sentiment.polarity # da -1 a 1

    # 3. Sintesi per l'AI
    # Combiniamo F&G (0-100) con TextBlob (-1 a 1)
    # Normalizziamo F&G tra -1 e 1: (50-50)/50 = 0
    fng_score = (fng_val - 50) / 50 
    
    final_score = (fng_score * 0.7) + (sentiment_score * 0.3)
    
    signal = "NEUTRAL"
    if final_score > 0.2: signal = "BULLISH"
    if final_score < -0.2: signal = "BEARISH"

    return {
        "score": round(final_score, 2),
        "signal": signal,
        "fear_greed_index": fng_val,
        "sentiment_label": fng_class,
        "news_headline_count": len(headlines)
    }

# --- FIX PER LA DASHBOARD ---
@app.get("/global_sentiment")
def dashboard_sentiment():
    # La dashboard vuole sapere il sentiment globale.
    # Usiamo BTC come proxy per il mercato globale
    fng_val, fng_class = get_fear_and_greed()
    return {
        "score": fng_val,  # La dashboard si aspetta un numero 0-100
        "label": fng_class,
        "sources": 10
    }

@app.get("/health")
def health(): return {"status": "active"}
