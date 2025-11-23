import os
import json
from typing import Dict, Any, List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI(title="Master AI Agent (DeepSeek/GPT)")

# --- CONFIGURAZIONE ---
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"), 
    base_url="https://api.deepseek.com"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELLI ---
class AnalysisPayload(BaseModel):
    symbol: str
    user_config: Dict[str, Any] = {} 
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

@app.get("/health")
def health_check(): return {"status": "ok"}

@app.post("/decide", response_model=DecisionResponse)
async def decide(payload: AnalysisPayload):
    # Recupera la strategia utente (Default: intraday)
    strategy = payload.user_config.get("strategy", "intraday")
    risk_pct = payload.user_config.get("risk_per_trade", 1.0)
    
    # Dati tecnici
    tech_15m = payload.tech_data.get("data", {}).get("15", {})
    tech_4h = payload.tech_data.get("data", {}).get("240", {})
    current_price = payload.fib_data.get("current_price", 0.0)

    # Costruiamo il prompt per l'AI
    system_prompt = f"""
    You are an elite Crypto Trading AI. Your goal is to find PROFITABLE entries, not to be passive.
    
    CURRENT STRATEGY: {strategy.upper()}
    
    RULES FOR TIMEFRAME CONFLICTS:
    1. If Strategy is INTRADAY: You MUST prioritize the 15-minute timeframe signals. Use 4H only for major support/resistance levels, NOT for trend direction. If 15m is strong, TAKE THE TRADE even if 4H is weak.
    2. If Strategy is SWING: You MUST prioritize the 4-Hour timeframe. Use 15m only to fine-tune entry price.
    
    RULES FOR MISSING DATA:
    - If Sentiment is "N/A" or missing, IGNORE IT. Do not let missing news stop a technical trade. Focus on Price Action, RSI, MACD, and Levels.
    
    DECISION LOGIC:
    - OPEN_LONG if the PRIMARY timeframe for the strategy shows Bullish momentum (RSI < 70, MACD cross up, Price > EMA).
    - OPEN_SHORT if the PRIMARY timeframe for the strategy shows Bearish momentum (RSI > 30, MACD cross down, Price < EMA).
    - WAIT only if the PRIMARY timeframe itself is flat/choppy/neutral.
    
    OUTPUT FORMAT (JSON):
    {{
      "decision": "OPEN_LONG" | "OPEN_SHORT" | "WAIT",
      "trade_setup": {{
        "entry_price": {current_price},
        "stop_loss": <price_level>,
        "take_profit": <price_level>,
        "size_pct": {risk_pct}
      }},
      "logic_log": ["Reason 1", "Reason 2"]
    }}
    """

    user_prompt = f"""
    Analyze {payload.symbol}. Price: {current_price}.
    
    [TECHNICAL 15m]: {json.dumps(tech_15m)}
    [TECHNICAL 4H]: {json.dumps(tech_4h)}
    [FIBONACCI]: {json.dumps(payload.fib_data)}
    [GANN]: {json.dumps(payload.gann_data)}
    [SENTIMENT]: {json.dumps(payload.sentiment_data)}
    
    Make a decision based on {strategy.upper()} strategy. Be decisive.
    """

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2, # Bassa temperatura per essere più logico e meno creativo
            max_tokens=500,
            response_format={ 'type': 'json_object' }
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        
        # Validazione base
        if data['decision'] not in ["OPEN_LONG", "OPEN_SHORT", "WAIT"]:
            data['decision'] = "WAIT"
            
        return data

    except Exception as e:
        print(f"AI Error: {e}")
        return {
            "decision": "WAIT", 
            "trade_setup": None, 
            "logic_log": [f"Error: {str(e)}"]
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
