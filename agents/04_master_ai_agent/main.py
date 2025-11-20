import os
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import json
from typing import Dict, Any, Optional

# Carica la chiave API di OpenAI in modo sicuro
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("La variabile d'ambiente OPENAI_API_KEY non è stata impostata.")

client = OpenAI(api_key=api_key)
app = FastAPI()

# --- v2: Struttura Dati di Input Aggiornata ---
# Ora include informazioni sul capitale
class PortfolioState(BaseModel):
    total_capital_eur: float
    available_capital_eur: float
    max_risk_per_trade_percent: float

class AnalysesPayload(BaseModel):
    symbol: str
    technical_analysis: Dict
    gann_analysis: Dict
    fibonacci_analysis: Dict
    news_sentiment: Dict
    portfolio_state: PortfolioState

# --- v2: Struttura Dati di Output (il piano di trading) ---
class TradingPlan(BaseModel):
    decision: str  # BUY, SELL, or HOLD
    reason: Optional[str] = None
    position_size_eur: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    use_trailing_stop: Optional[bool] = False
    trailing_offset_percent: Optional[float] = None


@app.post("/decide_plan", response_model=TradingPlan)
def decide_trade_plan(payload: AnalysesPayload):
    """
    v2: Riceve analisi e stato del portafoglio, restituisce un piano di trading completo.
    """

    # --- v2: Prompt per GPT-4 Aggiornato con Gestione del Rischio ---
    prompt = f"""
    Sei un Master Trader e Risk Manager AI. Il tuo compito è analizzare i dati forniti e generare un piano di trading completo e dettagliato.

    **Dati di Mercato:**
    - Simbolo: {payload.symbol}
    - Analisi Tecnica: {payload.technical_analysis}
    - Analisi Gann: {payload.gann_analysis}
    - Analisi Fibonacci: {payload.fibonacci_analysis}
    - Sentiment News: {payload.news_sentiment}

    **Dati di Portafoglio:**
    - Capitale Totale: {payload.portfolio_state.total_capital_eur} EUR
    - Capitale Disponibile: {payload.portfolio_state.available_capital_eur} EUR
    - Rischio Massimo per Operazione: {payload.portfolio_state.max_risk_per_trade_percent}% del capitale totale.

    **Compiti:**
    1.  **Decisione:** Decidi `BUY`, `SELL`, o `HOLD` per {payload.symbol}.
    2.  **Ragionamento:** Fornisci una breve frase che giustifichi la tua decisione.
    3.  **Stop Loss (SL):** Se BUY/SELL, definisci un prezzo di Stop Loss preciso. Deve essere un livello logico basato sui supporti/resistenze delle analisi.
    4.  **Position Sizing:** Calcola la dimensione della posizione in EUR. La perdita massima (distanza tra prezzo di entrata e SL) non deve superare il rischio massimo consentito ({payload.portfolio_state.max_risk_per_trade_percent}% del capitale totale).
    5.  **Take Profit (TP):** Definisci un prezzo di Take Profit con un rapporto Rischio/Rendimento di almeno 1:1.5.
    6.  **Trailing Stop:** Indica se un Trailing Stop è appropriato (`true`/`false`) e, se sì, suggerisci una percentuale di offset.

    **Formato Risposta Obbligatorio:**
    Rispondi ESCLUSIVAMENTE con un oggetto JSON valido. Non aggiungere commenti o testo al di fuori del JSON.

    Esempio di risposta BUY:
    {{
      "decision": "BUY",
      "reason": "Forte convergenza rialzista tra analisi tecnica e livelli di Fibonacci, con sentiment positivo.",
      "position_size_eur": 100.0,
      "stop_loss_price": 62500.50,
      "take_profit_price": 68000.00,
      "use_trailing_stop": true,
      "trailing_offset_percent": 1.5
    }}

    Esempio di risposta HOLD:
    {{
      "decision": "HOLD",
      "reason": "Segnali contrastanti tra analisi tecnica e sentiment, mercato laterale senza chiara direzione.",
      "position_size_eur": null,
      "stop_loss_price": null,
      "take_profit_price": null,
      "use_trailing_stop": false,
      "trailing_offset_percent": null
    }}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            response_format={"type": "json_object"},  # Nuova feature per garantire output JSON
            messages=[
                {"role": "system", "content": "Sei un assistente AI specializzato in analisi di trading che risponde solo in formato JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
        )

        # Estraiamo il JSON dalla risposta
        plan_data = json.loads(response.choices[0].message.content)

        # Validiamo i dati ricevuti da OpenAI e creiamo il nostro oggetto di risposta
        if plan_data.get("decision") not in ["BUY", "SELL", "HOLD"]:
            plan_data["decision"] = "HOLD" # Sicurezza

        return TradingPlan(**plan_data)

    except Exception as e:
        # In caso di errore con OpenAI o di JSON malformato, non fare nulla
        return TradingPlan(
            decision="HOLD",
            reason=f"Errore durante l'analisi AI: {str(e)}"
        )

@app.get("/")
def health_check():
    return {"status": "Master AI Agent v2 is running"}
