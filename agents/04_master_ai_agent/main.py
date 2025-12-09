import os
import json
import logging
from fastapi import FastAPI
from pydantic import BaseModel, field_validator
from typing import Dict, Any, Literal, Optional, List
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MasterAI")

app = FastAPI()

# DeepSeek Configuration
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# Validate configuration
if not DEEPSEEK_API_KEY:
    logger.error("DEEPSEEK_API_KEY is not set in environment variables!")
    logger.error("Please set DEEPSEEK_API_KEY in your .env file")
    raise ValueError("Missing DEEPSEEK_API_KEY - cannot initialize AI agent")

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
)

logger.info(f"DeepSeek AI initialized with model: {DEEPSEEK_MODEL}")

class Decision(BaseModel):
    symbol: str
    action: Literal["OPEN_LONG", "OPEN_SHORT", "HOLD", "CLOSE", "REVERSE_LONG", "REVERSE_SHORT"]
    leverage: float = 1.0  
    size_pct: float = 0.0
    rationale: str
    is_reverse: bool = False
    recovery_multiplier: float = 1.0

    # Validator permissivi
    @field_validator("leverage")
    def clamp_lev(cls, v): return max(1.0, min(v, 10.0))
    
    @field_validator("size_pct")
    def clamp_size(cls, v): return max(0.05, min(v, 0.30)) # Min 5% - Max 30% (increased for recovery)
    
    @field_validator("recovery_multiplier")
    def clamp_recovery(cls, v): return max(1.0, min(v, 2.5)) # Max 2.5x for loss recovery

class AnalysisPayload(BaseModel):
    global_data: Dict[str, Any]
    assets_data: Dict[str, Any]

SYSTEM_PROMPT = """
Sei un TRADER ALGORITMICO AGGRESSIVO con capacità di REVERSE STRATEGY.
Il tuo compito è ESEGUIRE decisioni autonome dopo aver analizzato i dati degli agenti.

REGOLE CRITICHE:
1. ANALISI AUTONOMA: Dopo aver ricevuto le analisi degli agenti tecnici, sentiment, Fibonacci, Gann, decidi TU la strategia.
2. REVERSE STRATEGY: Se una posizione è in perdita oltre il 2%, valuta IMMEDIATAMENTE un reverse:
   - Se avevi LONG in perdita -> apri SHORT con size maggiorato per recuperare
   - Se avevi SHORT in perdita -> apri LONG con size maggiorato per recuperare
   - Calcola il recovery_multiplier per coprire la perdita (es: perdita $100 -> usa 1.5x-2.0x sulla nuova posizione)
3. APERTURA POSIZIONI: 
   - Se l'analisi è "Bullish" e non hai posizioni -> OPEN_LONG
   - Se l'analisi è "Bearish" e non hai posizioni -> OPEN_SHORT
4. SIZE & LEVERAGE:
   - Leva standard: 5x-7x per operazioni normali
   - Size standard: 0.15 (15% del wallet)
   - Per REVERSE: aumenta size proporzionalmente alla perdita (usa recovery_multiplier)
5. STOP LOSS: Il Position Manager gestirà trailing stop ogni 60 secondi

FORMATO RISPOSTA JSON OBBLIGATORIO:
{
  "analysis_summary": "Sintesi completa della tua analisi autonoma",
  "market_conditions": "Condizioni di mercato rilevate",
  "decisions": [
    { 
      "symbol": "ETHUSDT", 
      "action": "OPEN_LONG" | "OPEN_SHORT" | "REVERSE_LONG" | "REVERSE_SHORT" | "HOLD",
      "leverage": 5.0, 
      "size_pct": 0.15,
      "is_reverse": false,
      "recovery_multiplier": 1.0,
      "rationale": "Spiegazione dettagliata della decisione"
    }
  ],
  "risk_assessment": "Valutazione del rischio generale"
}

NOTA: Le azioni REVERSE_LONG/REVERSE_SHORT indicano che stai chiudendo una posizione perdente e aprendo la opposta.
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
                "macd": t.get('macd_hist'),
                "fibonacci": v.get('fib', {}),
                "gann": v.get('gann', {}),
                "sentiment": v.get('sentiment', {})
            }
        
        # Include learning data if available
        learning_insights = payload.global_data.get('learning_insights', {})
            
        prompt_data = {
            "wallet_equity": payload.global_data.get('portfolio', {}).get('equity'),
            "active_positions": payload.global_data.get('already_open', []),
            "positions_details": payload.global_data.get('positions_details', []),
            "market_data": assets_summary,
            "learning_insights": learning_insights
        }

        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL, 
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"ANALIZZA E DECIDI AUTONOMAMENTE: {json.dumps(prompt_data, indent=2)}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )

        content = response.choices[0].message.content
        logger.info(f"DeepSeek AI Raw Response: {content}") # Debug nel log
        
        decision_json = json.loads(content)
        
        valid_decisions = []
        for d in decision_json.get("decisions", []):
            try: 
                valid_decisions.append(Decision(**d))
            except Exception as e: 
                logger.warning(f"Invalid decision: {e}")

        result = {
            "analysis": decision_json.get("analysis_summary", "No analysis"),
            "market_conditions": decision_json.get("market_conditions", "Unknown"),
            "risk_assessment": decision_json.get("risk_assessment", "Not provided"),
            "decisions": [d.model_dump() for d in valid_decisions]
        }
        
        # Store latest reasoning for dashboard
        global latest_reasoning
        latest_reasoning = result
        
        return result

    except Exception as e:
        logger.error(f"AI Critical Error: {e}")
        return {
            "analysis": "Error occurred",
            "market_conditions": "Unknown",
            "risk_assessment": "Error",
            "decisions": []
        }

# Storage for latest AI reasoning
latest_reasoning = {}

@app.get("/latest_reasoning")
def get_latest_reasoning():
    return latest_reasoning

@app.get("/health")
def health(): return {"status": "active", "model": DEEPSEEK_MODEL}
