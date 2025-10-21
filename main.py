import logging
import threading
import time

from core.exchange_router import ExchangeRouter
from agents.db_handler import DBHandler
from agents.mark_analyst import MarkAnalyst
from agents.sara_trader_pro import SaraTrader

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

def run_mark(exchange_router, db_handler, sara_trader):
    """Funzione target per il thread di MarkAnalyst."""
    try:
        logging.info("🚀 Avvio del thread per l'agente MarkAnalyst v8.0...")
        mark = MarkAnalyst(exchange_router=exchange_router, sara=sara_trader, db=db_handler)
        mark.start()
    except Exception as e:
        logging.critical(f"‼️ Errore fatale nel thread di MarkAnalyst: {e}", exc_info=True)

def trailing_loop(sara: SaraTrader):
    """Loop separato per la gestione delle posizioni (es. trailing stop)."""
    logging.info("🔩 Avvio del loop per il Trailing Stop...")
    while True:
        try:
            sara.manage_positions()
        except Exception as e:
            logging.error(f"Errore critico nel trailing_loop: {e}", exc_info=True)
        time.sleep(60)

def run_bot_threads(exchange_router, db_handler, sara_trader):
    """Avvia tutti i thread degli agenti per il bot LIVE."""
    
    mark_thread = threading.Thread(target=run_mark, args=(exchange_router, db_handler, sara_trader), name="MarkAnalyst", daemon=True)
    mark_thread.start()
    logging.info("🚀 Thread per 'MarkAnalyst' avviato.")

    sara_thread = threading.Thread(target=trailing_loop, args=(sara_trader,), name="SaraPositionManager", daemon=True)
    sara_thread.start()
    logging.info("🚀 Thread per 'SaraPositionManager' avviato.")

# Questa parte non è più necessaria nel bot live, ma la lasciamo per compatibilità
# con l'API FastAPI che si aspetta che i thread partano da qui.
# In un'architettura futura, anche questo potrebbe essere refattorizzato.
