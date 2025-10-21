import logging
from core.exchange_router import ExchangeRouter
from agents.db_handler import DBHandler
from agents.sara_trader import SaraTrader
from agents.mark_analyst import MarkAnalyst

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

# Modificato per passare i servizi come argomenti
def run_mark(exchange_router, db_handler, sara_trader):
    """Funzione target per il thread di MarkAnalyst, riceve i servizi."""
    try:
        # Crea l'istanza di MarkAnalyst passando i servizi necessari
        mark = MarkAnalyst(exchange_router=exchange_router, sara=sara_trader, db=db_handler)
        logging.info("🚀 Avvio dell'agente MarkAnalyst v6...")
        mark.start()
    except Exception as e:
        logging.critical(f"‼️ Errore fatale nel thread di MarkAnalyst: {e}", exc_info=True)

# Placeholder per gli altri agenti
def run_vittoria(): pass
def run_finn(): pass
def run_sara(): pass
