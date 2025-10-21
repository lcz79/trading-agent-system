import uvicorn
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import threading
import time
import logging
from datetime import datetime, timezone, timedelta

from main import run_mark
from agents.db_handler import DBHandler
from core.exchange_router import ExchangeRouter
from agents.sara_trader_pro import SaraTrader

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

# --- Servizi Singleton ---
exchange_router = ExchangeRouter()
db_handler = DBHandler()
sara_trader = SaraTrader(exchange_router) 

app = FastAPI(title="Mitragliere A.I. PRO API", version="5.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_db(): return db_handler
def get_sara(): return sara_trader

# --- COSTANTE PER LA FRESCHEZZA DEL SEGNALE ---
MAX_SIGNAL_AGE_MINUTES = 10

@app.get("/")
def root(): return {"status": "✅ Mitragliere A.I. PRO backend running"}

@app.get("/proposals")
def get_proposals(db: DBHandler = Depends(get_db)):
    try:
        df = db.get_all_signals_as_df()
        return {"proposals": df.to_dict('records') if not df.empty else []}
    except Exception as e:
        return {"proposals": []}

@app.post("/execute/{trade_id}")
def execute_trade(trade_id: int, db: DBHandler = Depends(get_db), sara: SaraTrader = Depends(get_sara)):
    logging.warning(f"Richiesta di esecuzione ricevuta per il trade ID: {trade_id}")
    signal_data = db.get_signal_by_id(trade_id)
    if not signal_data:
        raise HTTPException(status_code=404, detail=f"Trade ID {trade_id} non trovato.")
    
    # --- FIX: CONTROLLO SULL'ETÀ DEL SEGNALE ---
    signal_timestamp = signal_data.get('timestamp')
    if signal_timestamp:
        # Assicura che il timestamp sia "aware" (con timezone)
        if signal_timestamp.tzinfo is None:
            signal_timestamp = signal_timestamp.replace(tzinfo=timezone.utc)
        
        age = datetime.now(timezone.utc) - signal_timestamp
        if age > timedelta(minutes=MAX_SIGNAL_AGE_MINUTES):
            raise HTTPException(
                status_code=400, # Bad Request
                detail=f"Segnale scaduto. Generato {age.total_seconds() / 60:.0f} minuti fa (limite: {MAX_SIGNAL_AGE_MINUTES} min)."
            )
    # -----------------------------------------

    if 'side' in signal_data and signal_data['side'].upper() == 'BUY':
        signal_data['side'] = 'long'
    elif 'side' in signal_data and signal_data['side'].upper() == 'SELL':
        signal_data['side'] = 'short'

    execution_result = sara.execute_order(signal_data)
    
    if execution_result.get("status") == "error":
        raise HTTPException(status_code=500, detail=execution_result.get("message"))
    
    return execution_result

def trailing_loop(sara: SaraTrader):
    logging.info("🔩 Avvio del loop per il Trailing Stop...")
    while True:
        try:
            sara.manage_positions()
        except Exception as e:
            logging.error(f"Errore critico nel trailing_loop: {e}", exc_info=True)
        time.sleep(60)

def run_bot_threads():
    mark_args = (exchange_router, db_handler, sara_trader)
    mark_thread = threading.Thread(target=run_mark, args=mark_args, name="MarkAnalyst", daemon=True)
    mark_thread.start()
    logging.info("🚀 Thread per 'MarkAnalyst' avviato.")
    sara_thread = threading.Thread(target=trailing_loop, args=(sara_trader,), name="SaraPositionManager", daemon=True)
    sara_thread.start()
    logging.info("🚀 Thread per 'SaraPositionManager' (Trailing Stop) avviato.")

run_bot_threads()
