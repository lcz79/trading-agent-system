import os
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

API_KEY = os.getenv("COINGECKO_API_KEY")
BASE_URL = "https://api.coingecko.com/api/v3"
SYMBOL_TO_ID = {"BTCUSDT":"bitcoin", "ETHUSDT":"ethereum", "BNBUSDT":"binancecoin", "SOLUSDT":"solana", "XRPUSDT":"ripple", "ADAUSDT":"cardano", "DOGEUSDT":"dogecoin", "AVAXUSDT":"avalanche-2", "LINKUSDT":"chainlink", "MATICUSDT":"matic-network"}

app = FastAPI(title="CoinGecko Market Analyzer")
class MarketDataResponse(BaseModel): summary: str

@app.get("/health")
def health_check():
    return {"status": "ok" if API_KEY else "error", "detail": "COINGECKO_API_KEY missing" if not API_KEY else "API Key loaded"}

@app.get("/analyze_market_data/{symbol}", response_model=MarketDataResponse)
async def analyze_market_data(symbol: str):
    coin_id = SYMBOL_TO_ID.get(symbol.upper())
    if not coin_id: raise HTTPException(status_code=404, detail=f"Symbol {symbol} not mapped.")
    
    url = f"{BASE_URL}/coins/{coin_id}"
    params = {"localization":"false", "tickers":"false", "market_data":"true", "community_data":"true", "developer_data":"false", "sparkline":"false"}
    headers = {"x-cg-demo-api-key": API_KEY}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
        data = response.json()

        # --- CODICE PIU' ROBUSTO ---
        market_data = data.get("market_data") or {}
        price_change_24h = market_data.get("price_change_percentage_24h", 0.0) or 0.0
        total_volume_usd = (market_data.get("total_volume") or {}).get("usd", 0.0) or 0.0
        market_cap_usd = (market_data.get("market_cap") or {}).get("usd", 0.0) or 0.0
        sentiment_up = data.get("sentiment_votes_up_percentage", 0.0) or 0.0

        summary = (
            f"CoinGecko Market Data for {symbol}:\n"
            f"- 24h Price Change: {price_change_24h:.2f}%\n"
            f"- 24h Total Volume: ${int(total_volume_usd):,}\n"
            f"- Market Cap: ${int(market_cap_usd):,}\n"
            f"- Community Sentiment: {sentiment_up:.2f}% positive votes."
        )
        return MarketDataResponse(summary=summary)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"API Error: {e.response.text}")
    except Exception as e:
        # Stampa l'errore per il debug ma restituisci un errore 500 pulito
        print(f"CRITICAL ERROR processing {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error processing data for {symbol}.")
