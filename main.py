import json, os, logging, threading, time

from core.exchange_router import ExchangeRouter
from core.scheduler import Scheduler

from agents.mark_analyst import MarkAnalyst
from agents.vittoria_news import VittoriaNews
from agents.finn_fundamental import FinnFundamental
from agents.sara_strategist import SaraStrategist
from agents.webby_executor import WebbyExecutor

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(threadName)s] %(message)s', datefmt='%H:%M:%S')

def run_mark(cfg):
    """Funzione di avvio per l'agente Mark, ora configurato per Bybit."""
    logging.info("[MARK] Inizializzazione connessione exchange...")
    router = ExchangeRouter()
    time.sleep(10) # Pausa strategica per caricamento mercati
    
    # --- MODIFICA CHIAVE ---
    exchange = router.get("bybit") # Usa Bybit invece di Binance
    # -------------------------

    if exchange and exchange.markets:
        logging.info(f"[MARK] Connessione a BYBIT stabilita. Trovati {len(exchange.markets)} mercati.")
        MarkAnalyst(exchange, cfg["assets"], cfg["timeframe"], cfg["indicators"], cfg["filters"], cfg["logic"]).run()
    else:
        logging.error("[MARK] Impossibile avviare: exchange 'bybit' non trovato o mercati non caricati.")

def run_vittoria(cfg): VittoriaNews(cfg["news"]["feeds"], cfg["news"]["max_items_per_feed"]).run()
def run_finn(): FinnFundamental().run()
def run_sara(cfg): SaraStrategist(cfg["assets"]).run()
def run_webby(): WebbyExecutor().run_once() # Webby crea le sue risorse internamente

if __name__ == "__main__":
    logging.info("MITRAGLIERE A.I. COLLECTIVE v3 - Avvio sistema...")
    
    cfg = json.load(open("config/agents_config.json","r"))
    sched = Scheduler()
    
    tasks = {
        "Mark": {"func": run_mark, "interval": 300, "args": (cfg,)},
        "Vittoria": {"func": run_vittoria, "interval": 900, "args": (cfg,)},
        "Finn": {"func": run_finn, "interval": 3600, "args": ()},
        "Sara": {"func": run_sara, "interval": 60, "args": (cfg,)},
        "Webby": {"func": run_webby, "interval": 60, "args": ()}
    }

    for name, task in tasks.items():
        thread = threading.Thread(target=sched.run_every, args=(task["interval"], task["func"], *task["args"]), name=name, daemon=True)
        thread.start()
    
    logging.info("Tutti gli agenti avviati. Sistema operativo. Premi Ctrl+C per uscire.")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt: 
        logging.info("Stop richiesto. Terminazione...")
