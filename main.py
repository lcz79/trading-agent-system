import logging
from core.exchange_router import ExchangeRouter
from agents.db_handler import DBHandler
# AGGIORNATO L'IMPORT
from agents.sara_trader_pro import SaraTrader
from agents.mark_analyst import MarkAnalyst

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

def run_mark(exchange_router, db_handler, sara_trader):
    """Funzione target per il thread di MarkAnalyst, riceve i servizi."""
    try:
        mark = MarkAnalyst(exchange_router=exchange_router, sara=sara_trader, db=db_handler)
        logging.info("🚀 Avvio dell'agente MarkAnalyst v6...")
        mark.start()
    except Exception as e:
        logging.critical(f"‼️ Errore fatale nel thread di MarkAnalyst: {e}", exc_info=True)

# Placeholder per gli altri agenti
def run_vittoria(): pass
def run_finn(): pass
def run_sara(): pass
