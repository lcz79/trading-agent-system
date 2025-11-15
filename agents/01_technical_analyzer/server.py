# agents/01_technical_analyzer/server.py (VERSIONE CORRETTA E DI DEBUG)

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import ccxt
import pandas as pd

# Importa la funzione CORRETTA dal tuo file main.py
from main import analyze as perform_technical_analysis

app = FastAPI()

# Modelli Pydantic per la validazione dell'input
class IndicatorConfig(BaseModel):
    name: str
    params: dict = {}

class AnalysisInput(BaseModel):
    symbol: str
    interval: str
    indicator_configs: list[IndicatorConfig] # Anche se non usiamo questo direttamente, lo teniamo per la validazione

# Endpoint principale
@app.post("/analyze/")
async def analyze_endpoint(request: Request):
    """
    Endpoint che riceve una richiesta da n8n, scarica i dati di mercato
    e li passa alla funzione di analisi tecnica.
    """
    body = None
    try:
        # ======== BLOCCO DI DEBUG: STAMPIAMO IL CORPO DELLA RICHIESTA =========
        body = await request.json()
        print("="*50)
        print("CORPO DELLA RICHIESTA RICEVUTO DA N8N:")
        print(body)
        print("="*50)
        # =====================================================================

        # Ora validiamo manualmente i dati ricevuti usando il nostro modello Pydantic
        input_data = AnalysisInput(**body)

        # 1. Creare il "ponte": scaricare i dati con CCXT
        print(f"Download dati per {input_data.symbol} con intervallo {input_data.interval}...")
        exchange = ccxt.binance()
        ohlcv = exchange.fetch_ohlcv(input_data.symbol, input_data.interval, limit=100)
        
        # 2. Convertire i dati in un DataFrame di Pandas
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        # 3. Chiamare la funzione di analisi dal file main.py
        print("Esecuzione dell'analisi tecnica...")
        analysis_result = perform_technical_analysis(df)
        print("Analisi completata.")
        
        return analysis_result

    except Exception as e:
        # Se c'è un errore, lo stampiamo per capire meglio
        print(f"ERRORE DURANTE L'ELABORAZIONE: {e}")
        # Restituiamo comunque l'errore 422 se fallisce la validazione, altrimenti 500
        status_code = 422 if isinstance(e, ValueError) or "validation" in str(e).lower() else 500
        raise HTTPException(status_code=status_code, detail=f"Errore: {e}. Dati ricevuti: {body}")
