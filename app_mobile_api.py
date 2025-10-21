import uvicorn
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import threading
import logging

from main import run_mark
from agents.db_handler import DBHandler
from core.exchange_router import ExchangeRouter
from agents.sara_trader import SaraTrader

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

# --- Servizi Singleton ---
exchange_router = ExchangeRouter()
db_handler = DBHandler()
# Passiamo l'exchange router a Sara in modo che possa eseguire ordini
sara_trader = SaraTrader(exchange_router) 

app = FastAPI(title="Mitragliere A.I. API", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_db(): return db_handler
def get_sara(): return sara_trader

@app.get("/")
def root(): return {"status": "✅ Mitragliere A.I. backend running"}

@app.get("/proposals")
def get_proposals(db: DBHandler = Depends(get_db)):
    try:
        df = db.get_all_signals_as_df()
        return {"proposals": df.to_dict('records') if not df.empty else []}
    except Exception as e:
        logging.error(f"Errore API in /proposals: {e}", exc_info=True)
        return {"proposals": []}

# --- NUOVO ENDPOINT DI ESECUZIONE ---
@app.post("/execute/{trade_id}")
def execute_trade(trade_id: int, db: DBHandler = Depends(get_db), sara: SaraTrader = Depends(get_sara)):
    logging.warning(f"Richiesta di esecuzione ricevuta per il trade ID: {trade_id}")
    
    # 1. Trova il segnale nel database
    signal_data = db.get_signal_by_id(trade_id)
    if not signal_data:
        raise HTTPException(status_code=404, detail=f"Trade ID {trade_id} non trovato.")
    
    # 2. Passa il segnale a Sara per l'esecuzione
    execution_result = sara.execute_order(signal_data)
    
    # 3. Restituisci il risultato alla dashboard
    if execution_result.get("status") == "error":
        raise HTTPException(status_code=500, detail=execution_result.get("message"))
    
    return execution_result

def run_bot_threads():
    mark_args = (exchange_router, db_handler, sara_trader)
    thread = threading.Thread(target=run_mark, args=mark_args, name="MarkAnalyst", daemon=True)
    thread.start()
    logging.info("🚀 Thread per l'agente 'MarkAnalyst' avviato con servizi condivisi.")

run_bot_threads()
