import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import threading
import json
import time

# --- CARICAMENTO DELLE VARIABILI D'AMBIENTE ---
from dotenv import load_dotenv
load_dotenv()
# ---------------------------------------------

from core.memory_hub import read_agent, publish
from core.scheduler import Scheduler
from main import run_mark, run_vittoria, run_finn, run_sara
from agents.webby_executor import WebbyExecutor

# ... (il resto del file rimane identico a prima)

# 1. Inizializzazione dell'App FastAPI
app = FastAPI(
    title="Mitragliere A.I. Trading API",
    description="API per gestire e monitorare il bot di trading.",
    version="1.0.0"
)

# Permette all'app mobile (da qualsiasi origine) di connettersi
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Creazione degli Endpoint API
@app.get("/")
def read_root():
    return {"status": "Mitragliere A.I. Backend is running"}

@app.get("/proposals")
def get_trade_proposals():
    proposals_data = read_agent("WEBBY")
    return proposals_data.get("proposals", {"data": {"trades": []}})

@app.post("/execute/{symbol}")
def execute_trade(symbol: str):
    proposals_data = read_agent("WEBBY").get("proposals", {}).get("data", {})
    proposals = proposals_data.get("trades", [])
    
    trade_to_execute = None
    for p in proposals:
        if p.get("symbol").replace('/', '%2F') == symbol:
            trade_to_execute = p
            break
            
    if not trade_to_execute:
        raise HTTPException(status_code=404, detail=f"Nessuna proposta di trade trovata per {symbol}")

    publish("COMMAND", "execute", trade_to_execute)
    return {"status": "Comando di esecuzione ricevuto", "trade": trade_to_execute}

# 3. Funzione per avviare gli agenti in background
def run_bot_threads():
    cfg = json.load(open("config/agents_config.json","r"))
    sched = Scheduler()
    
    def run_webby_independent():
        WebbyExecutor().run_once()

    tasks = {
        "Mark": {"func": run_mark, "interval": 300, "args": (cfg,)},
        "Vittoria": {"func": run_vittoria, "interval": 900, "args": (cfg,)},
        "Finn": {"func": run_finn, "interval": 3600, "args": ()},
        "Sara": {"func": run_sara, "interval": 60, "args": (cfg,)},
        "Webby": {"func": run_webby_independent, "interval": 60, "args": ()}
    }

    for name, task in tasks.items():
        thread = threading.Thread(target=sched.run_every, args=(task["interval"], task["func"], *task["args"]), name=name, daemon=True)
        thread.start()
    print("Tutti i thread degli agenti sono stati avviati in background.")

# 4. Avvio del sistema
if __name__ == "__main__":
    run_bot_threads()
    uvicorn.run(app, host="0.0.0.0", port=8000)
