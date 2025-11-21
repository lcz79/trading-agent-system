import os
import json
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI

# --- CONFIGURAZIONE ---
# Assicurati di avere OPENAI_API_KEY nelle variabili d'ambiente
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# Se vuoi velocità e risparmio usa "gpt-3.5-turbo-0125"
# Se vuoi ragionamento massimo (consigliato per trading) usa "gpt-4o"
MODEL_NAME = "gpt-4o" 

app = FastAPI(title="Master Brain powered by OpenAI")

# --- MODELLI DATI ---

class DecisionRequest(BaseModel):
    symbol: str
    tech_data: Dict[str, Any]
    fib_data: Dict[str, Any]
    gann_data: Dict[str, Any]
    sentiment_data: Dict[str, Any]

class TradeSetup(BaseModel):
    strategy_name: str
    action: str          # "OPEN_LONG", "OPEN_SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    size_pct: float
    risk_reward: float
    reasoning: str       # Spiegazione dell'AI

class DecisionResponse(BaseModel):
    symbol: str
    decision: str        # "WAIT", "OPEN_LONG", "OPEN_SHORT"
    logic_log: List[str]
    trade_setup: Optional[TradeSetup]

# --- SYSTEM PROMPT ---
# Qui definiamo la "Personalità" del trader. È fondamentale.
SYSTEM_PROMPT = """
You are a Senior Crypto Portfolio Manager AI. Your goal is capital preservation first, profit second.
You will receive technical data, Fibonacci levels, Gann analysis, and News Sentiment.

YOUR MANDATE:
1. Analyze the CONFLUENCE of data. Do not trade on weak signals.
2. If Sentiment is extremely negative (< -0.8), DO NOT open LONG positions.
3. If Sentiment is extremely positive (> 0.8), DO NOT open SHORT positions.
4. Calculate strict Stop Loss (SL) and Take Profit (TP).
   - For LONG: SL must be below support (Swing Low or Gann/Fib level).
   - For SHORT: SL must be above resistance (Swing High or Gann/Fib level).
5. Risk/Reward Ratio MUST be > 1.2. If not, reply with decision "WAIT".
6. Position Sizing: Suggest 0.5 (50%) for weak setups, 1.0 (100%) for strong confluences.

OUTPUT FORMAT:
You must return valid JSON ONLY. No markdown, no explanations outside JSON.
Structure:
{
  "decision": "OPEN_LONG" | "OPEN_SHORT" | "WAIT",
  "strategy_name": "Name of the setup identified (e.g., Fibonacci Bounce)",
  "entry_price": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "size_pct": <float 0.1 to 1.0>,
  "reasoning": "Short explanation of why"
}
"""

# --- FUNZIONE PRINCIPALE ---

@app.post("/decide", response_model=DecisionResponse)
def ask_chatgpt_decision(request: DecisionRequest):
    symbol = request.symbol
    
    # 1. Preparazione del Payload per l'AI
    # Creiamo un riassunto strutturato dei dati per non consumare troppi token
    market_context = {
        "symbol": symbol,
        "price": request.fib_data.get("current_price"),
        "technical_15m": {
            "rsi": request.tech_data.get("data", {}).get("15", {}).get("rsi_14", {}).get("current"),
            "macd_cross": "Bullish" if request.tech_data.get("data", {}).get("15", {}).get("macd_hist", {}).get("current", 0) > 0 else "Bearish"
        },
        "trend_4h": "Bullish" if request.tech_data.get("data", {}).get("240", {}).get("close_price", 0) > request.tech_data.get("data", {}).get("240", {}).get("sma_200", {}).get("current", 0) else "Bearish",
        "fibonacci": {
            "trend": request.fib_data.get("trend_direction"),
            "in_golden_pocket": request.fib_data.get("in_golden_pocket"),
            "swing_low": request.fib_data.get("swing_low"),
            "swing_high": request.fib_data.get("swing_high")
        },
        "sentiment": {
            "score": request.sentiment_data.get("coin_news_score"),
            "verdict": request.sentiment_data.get("final_verdict")
        },
        "gann": {
            "support": request.gann_data.get("support_angle"),
            "resistance": request.gann_data.get("resistance_angle")
        }
    }

    # Convertiamo in stringa per il prompt
    user_message = f"Analyze this market data for {symbol}: {json.dumps(market_context)}"

    try:
        # 2. Chiamata OpenAI
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2, # Bassa temperatura = Più razionale e deterministico
            response_format={ "type": "json_object" } # Forza output JSON
        )
        
        # Parsing della risposta
        ai_content = response.choices[0].message.content
        ai_decision = json.loads(ai_content)
        
    except Exception as e:
        print(f"OpenAI Error: {e}")
        return DecisionResponse(symbol=symbol, decision="ERROR", logic_log=[str(e)], trade_setup=None)

    # 3. Validazione "Anti-Suicidio" (Il controllo umano/algoritmico finale)
    # Anche se l'AI è intelligente, verifichiamo che non abbia dato numeri a caso.
    
    decision_enum = ai_decision.get("decision", "WAIT")
    
    if decision_enum == "WAIT":
        return DecisionResponse(
            symbol=symbol, 
            decision="WAIT", 
            logic_log=[ai_decision.get("reasoning", "AI decided to wait")], 
            trade_setup=None
        )
    
    # Estrazione parametri
    entry = float(ai_decision.get("entry_price", 0))
    sl = float(ai_decision.get("stop_loss", 0))
    tp = float(ai_decision.get("take_profit", 0))
    
    # Controllo Geometrico
    is_valid = False
    risk = 0.0
    
    if decision_enum == "OPEN_LONG":
        if sl < entry < tp:
            risk = entry - sl
            is_valid = True
    elif decision_enum == "OPEN_SHORT":
        if tp < entry < sl:
            risk = sl - entry
            is_valid = True
            
    # Calcolo Risk:Reward reale
    rr = 0.0
    if is_valid and risk > 0:
        rr = abs(tp - entry) / risk
    
    # Controllo R:R minimo (Ridondante col prompt, ma sicurezza extra)
    if rr < 1.2:
        return DecisionResponse(
            symbol=symbol, decision="WAIT", 
            logic_log=[f"AI proposed trade but R:R {rr:.2f} is too low (Hallucination check)."], 
            trade_setup=None
        )

    # Se tutto è valido, creiamo il TradeSetup
    setup = TradeSetup(
        strategy_name=ai_decision.get("strategy_name", "AI Strategy"),
        action=decision_enum,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        size_pct=float(ai_decision.get("size_pct", 0.5)),
        risk_reward=round(rr, 2),
        reasoning=ai_decision.get("reasoning", "No reason provided")
    )

    return DecisionResponse(
        symbol=symbol,
        decision=decision_enum,
        logic_log=["AI Analysis Successful", setup.reasoning],
        trade_setup=setup
    )

@app.get("/")
def root():
    return {"agent": "OpenAI GPT-4o Trader", "status": "Active"}
