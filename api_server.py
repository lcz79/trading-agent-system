# ===========================================================
# api_server.py — Mitragliere A.I. Mobile API (Bybit Live)
# ===========================================================

import os
import threading
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from dotenv import load_dotenv

# --- Carica variabili d'ambiente (.env) ---
load_dotenv()
API_KEY = os.getenv("API_KEY")
LIVE_MODE = True
DEFAULT_EXCHANGE = "bybit"

# --- Import core system ---
from core.memory_hub import read_agent, publish
from core.scheduler import Scheduler
from main import run_mark, run_vittoria, run_finn, run_sara
from agents.webby_executor import WebbyExecutor

# ===========================================================
# 1️⃣  FASTAPI CONFIG
# ===========================================================
app = FastAPI(
    title="Mitragliere A.I. Trading API",
    description="Backend API per controllo remoto e app mobile del sistema Mitragliere A.I.",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===========================================================
# 2️⃣  SICUREZZA BASE (API Key Middleware)
# ===========================================================
@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    # Salta il controllo per l'endpoint radice ("/")
    if request.url.path == '/':
        return await call_next(request)
        
    key = request.headers.get("x-api-key")
    if not key or key != API_KEY:
        return JSONResponse(status_code=403, content={"error": "Accesso non autorizzato"})
    return await call_next(request)

# ===========================================================
# 3️⃣  ENDPOINTS PUBBLICI
# ===========================================================

@app.get("/")
def root():
    return {"status": "✅ Mitragliere A.I. API attiva", "mode": "LIVE", "exchange": DEFAULT_EXCHANGE}

@app.get("/status")
def get_status():
    try:
        return {
            "MARK": read_agent("MARK").get("last_update", "N/A"),
            "SARA": read_agent("SARA").get("last_update", "N/A"),
            "WEBBY": read_agent("WEBBY").get("last_update", "N/A"),
            "FINN": read_agent("FINN").get("last_update", "N/A"),
            "VITTORIA": read_agent("VITTORIA").get("last_update", "N/A"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/proposals")
def get_trade_proposals():
    data = read_agent("WEBBY")
    proposals = data.get("proposals", {}).get("trades", []) # Corretto per la nuova struttura
    return {"count": len(proposals), "trades": proposals}

@app.post("/execute/{symbol}")
def execute_trade(symbol: str):
    proposals_data = read_agent("WEBBY").get("proposals", {})
    proposals = proposals_data.get("trades", [])
    trade_to_execute = next((p for p in proposals if p.get("symbol") == symbol), None)
    
    if not trade_to_execute:
        raise HTTPException(status_code=404, detail=f"Nessuna proposta trovata per {symbol}")

    if not LIVE_MODE:
        return {"status": "Simulazione esecuzione (LIVE_MODE=False)", "trade": trade_to_execute}

    publish("COMMAND", "execute", {**trade_to_execute, "exchange": DEFAULT_EXCHANGE})
    return {"status": "✅ Ordine inviato a Bybit", "trade": trade_to_execute}

# ===========================================================
# 4️⃣  AVVIO DEGLI AGENTI IN THREAD SEPARATI
# ===========================================================
def run_bot_threads():
    cfg = json.load(open("config/agents_config.json", "r"))
    sched = Scheduler()

    def run_webby_independent():
        WebbyExecutor().run_once()

    agents = {
        "Mark": {"func": run_mark, "interval": 300, "args": (cfg,)},
        "Vittoria": {"func": run_vittoria, "interval": 900, "args": (cfg,)},
        "Finn": {"func": run_finn, "interval": 3600, "args": ()},
        "Sara": {"func": run_sara, "interval": 60, "args": (cfg,)},
        "Webby": {"func": run_webby_independent, "interval": 60, "args": ()},
    }

    for name, task in agents.items():
        thread = threading.Thread(
            target=sched.run_every,
            args=(task["interval"], task["func"], *task["args"]),
            name=name,
            daemon=True
        )
        thread.start()
    print("✅ Tutti gli agenti A.I. avviati in background.")

# ===========================================================
# 5️⃣  ENTRY POINT
# ===========================================================
if __name__ == "__main__":
    run_bot_threads()
    uvicorn.run(app, host="0.0.0.0", port=8000)
