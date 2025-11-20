import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# --- MODELLI DI DATI ---
class CryptoSymbol(BaseModel):
    symbol: str

# --- CONFIGURAZIONE ---
app = FastAPI()
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

# Mappa per tradurre il simbolo di trading nell'ID di CoinGecko
SYMBOL_TO_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "BNB": "binancecoin",
}

# --- CONTROLLO ALL'AVVIO ---
if not COINGECKO_API_KEY:
    raise RuntimeError("La variabile d'ambiente COINGECKO_API_KEY non è stata impostata!")

# --- ENDPOINT DELL'AGENTE ---
@app.post("/analyze")
async def analyze_sentiment(crypto: CryptoSymbol):
    try:
        # 1. Pulisci il simbolo (es. "BTCUSDT" -> "BTC")
        base_symbol = crypto.symbol.replace("USDT", "")

        # 2. Trova l'ID di CoinGecko corrispondente
        coin_id = SYMBOL_TO_ID_MAP.get(base_symbol)
        if not coin_id:
            raise HTTPException(
                status_code=404,
                detail=f"Simbolo '{base_symbol}' non mappato a un ID CoinGecko."
            )

        # 3. Prepara e èsegui la chiamata all'API di CoinGecko
        coingecko_api_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
        headers = {
            'Accepts': 'application/json',
            'x_cg_pro_api_key': COINGECKO_API_KEY
        }

        response = requests.get(coingecko_api_url, headers=headers)
        response.raise_for_status()  # Solleva un errore per status HTTP 4xx/5xx

        # 4. Restituisci i dati ottenuti
        return response.json()

    except requests.exceptions.HTTPError as http_err:
        # Errore specifico dalla chiamata a CoinGecko
        raise HTTPException(
            status_code=500,
            detail=f"Errore interno nell'agente CoinGecko: {http_err}"
        )
    except Exception as e:
        # Qualsiasi altro errore imprevisto
        raise HTTPException(
            status_code=500,
            detail=f"Errore generico nell'agente CoinGecko: {e}"
        )
