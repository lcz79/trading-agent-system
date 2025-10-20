import json, logging, threading, time

from core.exchange_router import ExchangeRouter
from core.scheduler import Scheduler
from agents.mark_analyst import MarkAnalyst
from agents.vittoria_news import VittoriaNews
from agents.finn_fundamental import FinnFundamental
from agents.sara_strategist import SaraStrategist
from agents.webby_executor import WebbyExecutor

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(threadName)s] %(message)s', datefmt='%H:%M:%S')

def run_mark(cfg):
    logging.info("[MARK] Inizializzazione connessione exchange...")
    router = ExchangeRouter()
    time.sleep(10)
    exchange = router.get("bybit")
    if exchange and exchange.markets:
        logging.info(f"[MARK] Connessione a BYBIT stabilita. Trovati {len(exchange.markets)} mercati.")
        MarkAnalyst(exchange, cfg["assets"], cfg["timeframe"], cfg["indicators"], cfg["filters"], cfg["logic"]).run()
    else:
        logging.error("[MARK] Impossibile avviare: exchange 'bybit' non trovato o mercati non caricati.")

def run_vittoria(cfg): VittoriaNews(cfg["news"]["feeds"], cfg["news"]["max_items_per_feed"]).run()
def run_finn(): FinnFundamental().run()

def run_sara(cfg):
    """ Funzione di avvio per l'agente Sara. """
    # --- CORREZIONE DEFINITIVA ---
    # La funzione corretta da chiamare è 'run_once'
    SaraStrategist(cfg["assets"]).run_once()

# NOTA: api_server.py ha una sua logica di avvio e non usa il blocco if __name__ == "__main__" qui sotto.
# Questo blocco serve solo se si lancia 'main.py' direttamente.
if __name__ == "__main__":
    logging.info("AVVIO IN MODALITÀ STANDALONE (SENZA API)...")
    cfg = json.load(open("config/agents_config.json","r"))
    sched = Scheduler()
    tasks = {
        "Mark": {"func": run_mark, "interval": 300, "args": (cfg,)},
        "Vittoria": {"func": run_vittoria, "interval": 900, "args": (cfg,)},
        "Finn": {"func": run_finn, "interval": 3600, "args": ()},
        "Sara": {"func": run_sara, "interval": 60, "args": (cfg,)},
        "Webby": {"func": WebbyExecutor().run_once, "interval": 60, "args": ()}
    }
    for name, task in tasks.items():
        thread = threading.Thread(target=sched.run_every, args=(task["interval"], task["func"], *task["args"]), name=name, daemon=True)
        thread.start()
    logging.info("Tutti gli agenti avviati. Sistema operativo. Premi Ctrl+C per uscire.")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stop richiesto. Terminazione...")
