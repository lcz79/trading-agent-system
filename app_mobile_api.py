import uvicorn
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import threading
import time
import logging

# Importa le funzioni e i servizi necessari
from main import run_mark
from agents.db_handler import DBHandler
from core.exchange_router import ExchangeRouter
from agents.sara_trader import SaraTrader

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

# --- CREAZIONE DEI SERVIZI "SINGLETON" ---
# Creiamo una sola istanza di questi oggetti all'avvio dell'app.
exchange_router = ExchangeRouter()
db_handler = DBHandler()
sara_trader = SaraTrader()
# -----------------------------------------

app = FastAPI(
    title="Mitragliere A.I. Trading API",
    description="Backend API per monitorare e controllare il bot.",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# --- FUNZIONE DI "DEPENDENCY INJECTION" ---
# Questa funzione fornisce la nostra istanza UNICA di DBHandler agli endpoint.
def get_db():
    return db_handler
# -----------------------------------------

@app.get("/")
def root():
    return {"status": "✅ Mitragliere A.I. backend running"}

@app.get("/proposals")
def get_proposals(db: DBHandler = Depends(get_db)): # <-- L'API riceve il DB da qui
    """Recupera le proposte di trade usando l'istanza condivisa del DB."""
    try:
        signals_df = db.get_all_signals_as_df() # <-- Ora questa chiamata funzionerà
        if not signals_df.empty:
            return {"proposals": signals_df.to_dict('records')}
        else:
            return {"proposals": []}
    except Exception as e:
        logging.error(f"Errore API in /proposals: {e}", exc_info=True)
        return {"proposals": []}

def run_bot_threads():
    """Avvia gli agenti passando loro le istanze condivise dei servizi."""
    # Passiamo gli oggetti che abbiamo già creato
    mark_args = (exchange_router, db_handler, sara_trader)
    
    thread = threading.Thread(target=run_mark, args=mark_args, name="MarkAnalyst", daemon=True)
    thread.start()
    logging.info("🚀 Thread per l'agente 'MarkAnalyst' avviato con servizi condivisi.")

run_bot_threads()

if __name__ == "__main__":
    uvicorn.run("app_mobile_api:app", host="0.0.0.0", port=8000, reload=True)
