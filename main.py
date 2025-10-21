import logging
from core.exchange_router import ExchangeRouter
from agents.db_handler import DBHandler
from agents.sara_trader import SaraTrader
from agents.mark_analyst import MarkAnalyst

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

def initialize_core_services():
    """Crea una singola istanza dei servizi principali per condividerli."""
    logging.info("Creazione delle istanze dei servizi principali (Singleton)...")
    exchange_router = ExchangeRouter()
    db_handler = DBHandler()
    sara_trader = SaraTrader()
    return exchange_router, db_handler, sara_trader

def run_mark(exchange_router, db_handler, sara_trader):
    """Funzione target per il thread di MarkAnalyst, riceve i servizi."""
    try:
        mark = MarkAnalyst(exchange_router, sara_trader, db_handler)
        logging.info("🚀 Avvio dell'agente MarkAnalyst...")
        mark.start()
    except Exception as e:
        logging.critical(f"‼️ Errore fatale nel thread di MarkAnalyst: {e}", exc_info=True)

# Placeholder per gli altri agenti
def run_vittoria(): pass
def run_finn(): pass
def run_sara(): pass
