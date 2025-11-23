import os
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

API_KEY = os.getenv("COINGECKO_API_KEY")
BASE_URL = "https://api.coingecko.com/api/v3"

# Mappa aggiornata con TUTTE le coin
SYMBOL_TO_ID = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "BNBUSDT": "binancecoin",
    "SOLUSDT": "solana",
    "XRPUSDT": "ripple",
    "ADAUSDT": "cardano",
    "DOGEUSDT": "dogecoin",
    "AVAXUSDT": "avalanche-2",
    "LINKUSDT": "chainlink",
    "MATICUSDT": "matic-network",
    "LTCUSDT": "litecoin",    
    "DOTUSDT": "polkadot"     
}

app = FastAPI(title="CoinGecko Market Analyzer")
class MarketDataResponse(BaseModel): summary: str

@app.get("/health")
def health_check():
    return {"status": "ok" if API_KEY else "error", "detail": "COINGECKO_API_KEY missing" if not API_KEY else "API Key loaded"}

@app.get("/analyze_market_data/{symbol}", response_model=MarketDataResponse)
async def analyze_market_data(symbol: str):
    coin_id = SYMBOL_TO_ID.get(symbol.upper())
    
    # Fallback intelligente: se non trova la mappa, prova a cercare lo slug minuscolo (es. PEPEUSDT -> pepe)
    if not coin_id: 
        # Tenta di indovinare rimuovendo USDT
        coin_id = symbol.upper().replace("USDT", "").lower()
    
    url = f"{BASE_URL}/coins/{coin_id}"
    params = {"localization":"false", "tickers":"false", "market_data":"true", "community_data":"true", "developer_data":"false", "sparkline":"false"}
    headers = {"x-cg-demo-api-key": API_KEY}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=10.0)
            # Se fallisce (404), restituiamo un dato neutro invece di rompere tutto
            if response.status_code == 404:
                return MarketDataResponse(summary="Sentiment Data: Neutral (Source Not Found)")
            response.raise_for_status()
        
        data = response.json()
        market_data = data.get("market_data") or {}
        price_change_24h = market_data.get("price_change_percentage_24h", 0.0) or 0.0
        sentiment_up = data.get("sentiment_votes_up_percentage", 50.0) or 50.0 # Default 50%

        summary = (
            f"CoinGecko Market Data for {symbol}:\n"
            f"- 24h Price Change: {price_change_24h:.2f}%\n"
            f"- Community Sentiment: {sentiment_up:.2f}% positive votes."
        )
        return MarketDataResponse(summary=summary)

    except Exception as e:
        print(f"CoinGecko Error for {symbol}: {e}")
        # In caso di errore API, restituisci comunque qualcosa per non bloccare l'Orchestrator
        return MarketDataResponse(summary="Sentiment Data: Unavailable (API Error)")
