import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # <-- IMPORTA QUESTO
import threading
import time
import logging

from main import run_mark, run_vittoria, run_finn, run_sara
from agents.db_handler import DBHandler

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

app = FastAPI(
    title="Mitragliere A.I. Trading API",
    description="Backend API per monitorare e controllare il bot Mitragliere.",
    version="2.1.0"
)

# --- BLOCCO DI CODICE FONDAMENTALE (dal tuo piano originale!) ---
# Aggiungi il middleware per il CORS. Questo dice al server di accettare
# richieste che arrivano da altri domini (come la tua dashboard).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permette a qualsiasi dominio di fare richieste
    allow_credentials=True,
    allow_methods=["*"],  # Permette tutti i metodi (GET, POST, ecc.)
    allow_headers=["*"],  # Permette tutti gli header
)
# --------------------------------------------------------------------

@app.get("/")
def root():
    return {"status": "✅ Mitragliere A.I. backend running"}

@app.get("/proposals")
def get_proposals():
    """Recupera le proposte di trade salvate nel database."""
    try:
        db = DBHandler()
        # Usiamo il metodo che abbiamo già per leggere i segnali
        signals_df = db.get_all_signals_as_df()
        
        if not signals_df.empty:
            # Converti il DataFrame in una lista di dizionari per la risposta JSON
            proposals = signals_df.to_dict('records')
            return {"proposals": proposals}
        else:
            return {"proposals": []}
            
    except Exception as e:
        logging.error(f"Errore nel recuperare le proposte dall'API: {e}", exc_info=True)
        # In caso di errore, restituisci un array vuoto per non rompere la dashboard
        return {"proposals": []}


def run_bot_threads():
    tasks = {
        "MarkAnalyst": {"target": run_mark, "daemon": True},
    }
    for name, task in tasks.items():
        thread = threading.Thread(target=task["target"], name=name, daemon=task["daemon"])
        thread.start()
        logging.info(f"🚀 Thread per l'agente '{name}' avviato.")
    logging.info("✅ Tutti gli agenti sono stati avviati in background.")

run_bot_threads()

if __name__ == "__main__":
    uvicorn.run("app_mobile_api:app", host="0.0.0.0", port=8000, reload=True)
