import uvicorn
from fastapi import FastAPI
import threading
import time
import logging

# Importa le funzioni di avvio degli agenti da main.py
from main import run_mark, run_vittoria, run_finn, run_sara

# Inizializzazione del logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s')

app = FastAPI(
    title="Mitragliere A.I. Trading API",
    description="Backend API per monitorare e controllare il bot Mitragliere.",
    version="2.0.0"
)

# Endpoint di base per verificare che il server sia attivo
@app.get("/")
def root():
    return {"status": "✅ Mitragliere A.I. backend running"}

# Endpoint per leggere le proposte di trade dal database
@app.get("/proposals")
def get_proposals():
    from agents.db_handler import DBHandler # Importa solo quando serve
    db = DBHandler()
    # Questa è una query di esempio, da adattare al tuo db_handler
    # Per ora, restituiamo un placeholder
    return {"proposals": "Endpoint in costruzione. I dati verranno letti dal DB."}


# Funzione per avviare gli agenti in background
def run_bot_threads():
    """Crea e avvia i thread per ogni agente del bot."""
    # Definiamo i task per ogni agente
    tasks = {
        "MarkAnalyst": {"target": run_mark, "daemon": True},
        # Aggiungi qui gli altri agenti quando saranno pronti
        # "Vittoria": {"target": run_vittoria, "daemon": True},
        # "Finn": {"target": run_finn, "daemon": True},
    }

    for name, task in tasks.items():
        thread = threading.Thread(
            target=task["target"],
            name=name,
            daemon=task["daemon"]
        )
        thread.start()
        logging.info(f"🚀 Thread per l'agente '{name}' avviato.")
    
    logging.info("✅ Tutti gli agenti sono stati avviati in background.")


# Avvia i thread degli agenti all'avvio dell'applicazione
run_bot_threads()


if __name__ == "__main__":
    # Questo blocco viene eseguito solo se avvii il file direttamente con "python app_mobile_api.py"
    # Render userà invece il comando uvicorn, ma è utile per i test locali.
    logging.info("Avvio del server Uvicorn per test locali...")
    uvicorn.run("app_mobile_api:app", host="0.0.0.0", port=8000, reload=True)