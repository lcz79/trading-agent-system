import os
import json
import logging
from fastapi import FastAPI
from pydantic import BaseModel, field_validator
from typing import Dict, Any, Literal, Optional
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MasterAI")

app = FastAPI()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

class Decision(BaseModel):
    symbol: str
    action: Literal["OPEN_LONG", "OPEN_SHORT", "HOLD", "CLOSE"]
    leverage: float = 1.0  
    size_pct: float = 0.0
    rationale: str

    # Validator permissivi
    @field_validator("leverage")
    def clamp_lev(cls, v): return max(1.0, min(v, 10.0))
    
    @field_validator("size_pct")
    def clamp_size(cls, v): return max(0.05, min(v, 0.25)) # Min 5% - Max 25%

class AnalysisPayload(BaseModel):
    global_data: Dict[str, Any]
    assets_data: Dict[str, Any]

SYSTEM_PROMPT = """
Sei un TRADER ALGORITMICO AGGRESSIVO.
Il tuo compito non è solo analizzare, è ESEGUIRE.

REGOLE CRITICHE:
1. Se l'analisi è "Bullish" e non hai posizioni -> DEVI ordinare "OPEN_LONG".
2. Se l'analisi è "Bearish" e non hai posizioni -> DEVI ordinare "OPEN_SHORT".
3. NON dire "consiglio di aprire" senza mettere l'ordine nel JSON. FALLO.
4. Leva consigliata: 5x - 7x per Scalp.
5. Size consigliata: 0.15 (15% del wallet) per trade.

FORMATO RISPOSTA JSON OBBLIGATORIO:
{
  "analysis_summary": "Breve sintesi del perché",
  "decisions": [
    { 
      "symbol": "ETHUSDT", 
      "action": "OPEN_LONG", 
      "leverage": 5.0, 
      "size_pct": 0.15, 
      "rationale": "RSI basso su supporto" 
    }
  ]
}
"""

@app.post("/decide_batch")
def decide_batch(payload: AnalysisPayload):
    try:
        # Semplificazione dati per prompt
        assets_summary = {}
        for k, v in payload.assets_data.items():
            t = v.get('tech', {})
            assets_summary[k] = {
                "price": t.get('price'),
                "rsi_7": t.get('rsi'), # Usiamo RSI veloce
                "trend": t.get('trend'),
                "macd": t.get('macd_hist')
            }
            
        prompt_data = {
            "wallet_equity": payload.global_data.get('portfolio', {}).get('equity'),
            "active_positions": payload.global_data.get('already_open', []),
            "market_data": assets_summary
        }

        response = client.chat.completions.create(
            model="gpt-5.1", 
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"ANALIZZA E AGISCI: {json.dumps(prompt_data)}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.7, # Più creatività = più trade
        )

        content = response.choices[0].message.content
        logger.info(f"AI Raw Response: {content}") # Debug nel log
        
        decision_json = json.loads(content)
        
        valid_decisions = []
        for d in decision_json.get("decisions", []):
            try: valid_decisions.append(Decision(**d))
            except Exception as e: logger.warning(f"Invalid decision: {e}")

        return {
            "analysis": decision_json.get("analysis_summary", "No analysis"),
            "decisions": [d.model_dump() for d in valid_decisions]
        }

    except Exception as e:
        logger.error(f"AI Critical Error: {e}")
        return {"analysis": "Error", "decisions": []}

@app.get("/health")
def health(): return {"status": "active"}
