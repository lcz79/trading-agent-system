import logging
from core.exchange_router import ExchangeRouter
from agents.db_handler import DBHandler
from agents.sara_trader import SaraTrader
from agents.mark_analyst import MarkAnalyst

# Inizializzazione del logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

def initialize_core_services():
    """Inizializza e restituisce i servizi condivisi tra gli agenti."""
    logging.info("Inizializzazione dei servizi principali...")
    
    # Il router per le connessioni agli exchange
    exchange_router = ExchangeRouter()
    
    # Il gestore del database
    db_handler = DBHandler()
    
    # Sara, l'agente che riceve le proposte e invia notifiche
    sara_trader = SaraTrader()
    
    logging.info("Servizi principali inizializzati.")
    return exchange_router, db_handler, sara_trader

def run_mark():
    """Funzione target per il thread dell'agente MarkAnalyst."""
    try:
        exchange_router, db_handler, sara_trader = initialize_core_services()
        mark = MarkAnalyst(exchange_router, sara_trader, db_handler)
        logging.info("🚀 Avvio dell'agente MarkAnalyst...")
        mark.start() # Il metodo start() contiene il ciclo while True
    except Exception as e:
        logging.critical(f"‼️ Errore fatale nel thread di MarkAnalyst: {e}", exc_info=True)

# Per ora, definiamo le altre funzioni come placeholder
def run_vittoria():
    logging.info("Agente Vittoria (Portfolio Manager) non ancora implementato. In attesa.")
    pass

def run_finn():
    logging.info("Agente Finn (Risk Manager) non ancora implementato. In attesa.")
    pass

def run_sara():
    # La logica di Sara è principalmente reattiva, quindi il suo thread potrebbe non fare nulla
    logging.info("Agente Sara (Trader/Notifier) è in ascolto...")
    pass