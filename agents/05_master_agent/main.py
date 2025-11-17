from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import openai
import json
import httpx

# --- Modelli Pydantic per i dati in ingresso e in uscita ---

# Dati che ci aspettiamo di ricevere da n8n
class InputData(BaseModel):
    symbol: str
    current_price: float
    technical_analysis: dict
    sentiment_analysis: dict

# Struttura della risposta che ci aspettiamo da OpenAI
class LLMResponse(BaseModel):
    decision: str # "BUY", "SELL", "HOLD"
    reason: str

app = FastAPI()

# --- Configurazione del client OpenAI ---
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("La variabile d'ambiente OPENAI_API_KEY non è stata impostata.")
client = openai.OpenAI(api_key=api_key)

# URL dell'agente successivo nella catena
TRADE_GUARDIAN_URL = "http://trade-guardian:8000/validate_and_size"

# --- System Prompt per l'LLM ---
SYSTEM_PROMPT = """
Sei un esperto trader di criptovalute. Il tuo obiettivo è analizzare i dati forniti per decidere se eseguire un'operazione di trading.
I dati includono:
1.  **Analisi Tecnica**: Contiene indicatori come RSI, MACD, e medie mobili.
2.  **Analisi del Sentiment**: Misura il sentiment generale del mercato basato sulle news.

Analizza attentamente entrambi i set di dati. La tua decisione deve essere basata su una sintesi ragionata di tutte le informazioni.

**REGOLE FONDAMENTALI:**
- Se l'analisi tecnica e il sentiment sono concordi (es. RSI basso e sentiment positivo), puoi considerare un'operazione.
- Se sono discordanti (es. RSI basso ma sentiment molto negativo), la scelta più saggia è non fare nulla (`HOLD`).
- Sii cauto. È meglio perdere un'opportunità che fare un'operazione sbagliata.

DATI FORNITI:
- Simbolo: {symbol}
- Prezzo Corrente: {current_price}
- Analisi Tecnica: {technical_analysis}
- Analisi del Sentiment: {sentiment_analysis}

La tua risposta DEVE essere un oggetto JSON valido con la seguente struttura:
{{
  "decision": "Una tra 'BUY', 'SELL', o 'HOLD'",
  "reason": "Una breve spiegazione (massimo 50 parole) del perché hai preso questa decisione, basandoti sui dati."
}}
"""

@app.post("/decide")
async def decide_trade(data: InputData):
    print(f"--- MASTER AGENT: Ricevuti dati per {data.symbol} ---")

    # 1. Costruisci il prompt per l'LLM
    prompt = SYSTEM_PROMPT.format(
        symbol=data.symbol,
        current_price=data.current_price,
        technical_analysis=json.dumps(data.technical_analysis, indent=2),
        sentiment_analysis=json.dumps(data.sentiment_analysis, indent=2)
    )

    try:
        # 2. Chiama l'API di OpenAI per ottenere una decisione
        print(">>> Interrogando l'LLM per una decisione di trading...")
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2, # Bassa temperatura per decisioni più consistenti
            max_tokens=150
        )
        llm_output_text = response.choices[0].message.content
        print(f"<<< Risposta ricevuta dall'LLM: {llm_output_text}")

        # 3. Valida e processa la risposta dell'LLM
        llm_response = LLMResponse.parse_raw(llm_output_text)
        decision = llm_response.decision.upper()
        reason = llm_response.reason

        # 4. Agisci in base alla decisione
        if decision in ["BUY", "SELL"]:
            print(f"--- DECISIONE: {decision}. Motivo: {reason} ---")
            print(f">>> Inoltro al Trade Guardian per il calcolo della dimensione...")

            # Prepara i dati per il Trade Guardian
            order_for_guardian = {
                "symbol": data.symbol,
                "side": "Buy" if decision == "BUY" else "Sell", # Il guardian vuole "Buy" o "Sell"
                "current_price": data.current_price
            }

            # Inoltra la richiesta al Trade Guardian
            async with httpx.AsyncClient() as http_client:
                try:
                    guardian_response = await http_client.post(TRADE_GUARDIAN_URL, json=order_for_guardian, timeout=30.0)
                    guardian_response.raise_for_status()
                    print("<<< Risposta ricevuta dal Trade Guardian e inoltrata al client.")
                    return guardian_response.json()
                except httpx.RequestError as e:
                    print(f"!!! ERRORE CRITICO: Impossibile comunicare con il Trade Guardian a {TRADE_GUARDIAN_URL}. Dettagli: {e}")
                    raise HTTPException(status_code=503, detail=f"Errore di comunicazione con il Trade Guardian: {e}")

        elif decision == "HOLD":
            print(f"--- DECISIONE: HOLD. Motivo: {reason} ---")
            return {"status": "success", "decision": "HOLD", "reason": reason}
        else:
            print(f"!!! ERRORE: L'LLM ha restituito una decisione non valida: '{decision}'")
            raise HTTPException(status_code=500, detail=f"Decisione non valida ricevuta dall'LLM: {decision}")

    except openai.APIError as e:
        print(f"!!! ERRORE API OPENAI: {e}")
        raise HTTPException(status_code=500, detail=f"Errore dall'API di OpenAI: {e}")
    except Exception as e:
        print(f"!!! ERRORE SCONOSCIUTO: {e}")
        raise HTTPException(status_code=500, detail=f"Errore imprevisto durante il processo decisionale: {str(e)}")