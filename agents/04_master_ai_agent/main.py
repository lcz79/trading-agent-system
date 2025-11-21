import os
import json
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# --- CONFIGURAZIONE ---
# Carica la chiave API e inizializza il client (Sintassi v1.0+)
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# Modello consigliato: gpt-4o (veloce e intelligente) o gpt-4-turbo
MODEL_NAME = "gpt-4o"

app = FastAPI(title="Master AI Brain V3 (Smart & Safe)")

# --- ABILITAZIONE CORS (Necessario per la Dashboard) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELLI DATI ---
class AnalysisPayload(BaseModel):
    symbol: str
    tech_data: Dict[str, Any]
    fib_data: Dict[str, Any]
    gann_data: Dict[str, Any]
    sentiment_data: Dict[str, Any]

class TradeSetup(BaseModel):
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    size_pct: Optional[float]

class DecisionResponse(BaseModel):
    decision: str
    trade_setup: Optional[TradeSetup]
    logic_log: List[str]

# --- PROMPT DI SISTEMA V2 (Il tuo prompt migliorato) ---
SYSTEM_PROMPT = """
You are "Master-AI-Trader", a sophisticated trading analysis bot. Your primary goal is to identify high-probability trading setups by analyzing market data from multiple agents.

**DECISION HIERARCHY & WEIGHTING:**
1. PRIMARY DRIVERS (High Weight): `tech_data` (Trend D/4H) and `fib_data` (Key Levels). A strong signal here is the main reason to act.
2. CONFIRMATION (Medium Weight): `gann_data` for timing/precision.
3. CONTEXT (Low Weight): `sentiment_data`.
   **CRITICAL RULE:** If `sentiment_data` is missing, empty, or neutral, YOU MUST STILL DECIDE based on Technicals. Do NOT block a trade just because news are missing.

**DECISION LOGIC:**
- OPEN_LONG: Bounce off Support (Fib/Gann) + Bullish Tech (RSI oversold turning up, MACD cross).
- OPEN_SHORT: Rejection at Resistance (Fib/Gann) + Bearish Tech (RSI overbought turning down).
- WAIT: Conflicting signals or Sideways market.

**RISK MANAGEMENT RULES (MANDATORY):**
- Stop Loss MUST be technical (below support for Long, above resistance for Short).
- Risk/Reward Ratio MUST be > 1.2. If the setup offers less, output WAIT.

**OUTPUT FORMAT (JSON ONLY):**
{
  "decision": "OPEN_LONG | OPEN_SHORT | WAIT",
  "trade_setup": {
    "entry_price": <float>,
    "stop_loss": <float>,
    "take_profit": <float>,
    "size_pct": <float 0.1-1.0>
  },
  "logic_log": ["Detailed reason 1", "Detailed reason 2"]
}
"""

@app.post("/decide", response_model=DecisionResponse)
async def decide(payload: AnalysisPayload):
    
    # 1. Preparazione Dati (Gestione Sentiment vuoto)
    sent_score = payload.sentiment_data.get("coin_news_score", "N/A")
    
    # Creiamo un contesto pulito per l'AI
    context = {
        "price": payload.fib_data.get("current_price"),
        "trend_structure": payload.fib_data.get("trend_direction"),
        "tech_15m": payload.tech_data.get("data", {}).get("15", {}),
        "tech_4h": payload.tech_data.get("data", {}).get("240", {}),
        "fib_levels": payload.fib_data.get("levels"),
        "gann_levels": {
            "support": payload.gann_data.get("support_level"),
            "resistance": payload.gann_data.get("resistance_level")
        },
        "sentiment": sent_score
    }
    
    user_prompt = f"Analyze {payload.symbol}. Market Data: {json.dumps(context)}"

    try:
        # 2. Chiamata OpenAI
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2, # Bassa temperatura = più razionalità
            response_format={"type": "json_object"}
        )
        
        ai_content = response.choices[0].message.content
        decision_json = json.loads(ai_content)
        
        decision = decision_json.get("decision", "WAIT")
        raw_setup = decision_json.get("trade_setup") or {}
        
        # Se l'AI dice WAIT, ci fermiamo qui
        if decision == "WAIT":
            return DecisionResponse(
                decision="WAIT",
                trade_setup=None,
                logic_log=decision_json.get("logic_log", ["Wait signal generated"])
            )

        # --- 3. VALIDAZIONE "ANTI-SUICIDIO" (Safety Check) ---
        # Verifichiamo che l'AI non abbia allucinato numeri rischiosi
        
        entry = float(raw_setup.get("entry_price") or 0)
        sl = float(raw_setup.get("stop_loss") or 0)
        tp = float(raw_setup.get("take_profit") or 0)
        size = float(raw_setup.get("size_pct") or 0.5)
        
        is_valid = False
        if decision == "OPEN_LONG" and sl < entry < tp: is_valid = True
        if decision == "OPEN_SHORT" and tp < entry < sl: is_valid = True
        
        # Calcolo Risk Reward Ratio
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = 0.0
        if risk > 0:
            rr = reward / risk
            
        # BLOCCO DI SICUREZZA
        if not is_valid:
            return DecisionResponse(
                decision="WAIT",
                trade_setup=None,
                logic_log=[f"SAFETY BLOCK: Invalid Trade Geometry. Entry:{entry}, SL:{sl}, TP:{tp}"]
            )
            
        if rr < 1.2:
            return DecisionResponse(
                decision="WAIT",
                trade_setup=None,
                logic_log=[f"SAFETY BLOCK: R:R too low ({rr:.2f}). Minimum 1.2 required."]
            )

        # Se passiamo i controlli, restituiamo il trade approvato
        return DecisionResponse(
            decision=decision,
            trade_setup=TradeSetup(
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                size_pct=size
            ),
            logic_log=decision_json.get("logic_log", ["Trade Approved"])
        )

    except Exception as e:
        # Fail-safe: in caso di errore, non fare nulla (WAIT)
        print(f"Brain Error: {e}")
        return DecisionResponse(decision="WAIT", trade_setup=None, logic_log=[f"System Error: {str(e)}"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
