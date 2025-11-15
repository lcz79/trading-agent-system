# agents/02_news_sentiment/server.py

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Importiamo la logica principale
from main import run_full_news_analysis

app = FastAPI(
    title="News Sentiment Agent",
    description="Un agente che recupera notizie crypto da NewsAPI.org e ne analizza il sentiment.",
    version="1.1.0",  # Abbiamo aggiornato la versione!
)

# Aggiorniamo il modello di input per usare una chiave API generica
class NewsInput(BaseModel):
    news_api_key: str

@app.post("/analyze_news/")
async def get_sentiment(input_data: NewsInput):
    """
    Esegue l'analisi del sentiment sulle ultime notizie crypto.
    Richiede una chiave API valida per NewsAPI.org.
    """
    if not input_data.news_api_key or input_data.news_api_key == "YOUR_NEWSAPI_KEY":
        raise HTTPException(status_code=400, detail="Chiave API di NewsAPI.org non fornita o non valida.")

    # Passiamo la chiave corretta alla nostra funzione aggiornata
    analysis_result = run_full_news_analysis(api_key=input_data.news_api_key)
    
    return analysis_result

@app.get("/")
def health_check():
    return {"status": "News Sentiment Agent is running"}