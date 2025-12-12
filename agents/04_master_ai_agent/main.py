import os
import json
import logging
import httpx
from datetime import datetime
from fastapi import FastAPI
from pydantic import BaseModel, field_validator
from typing import Dict, Any, Literal, Optional
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MasterAI")

app = FastAPI()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Agent URLs for reverse analysis
AGENT_URLS = {
    "technical": "http://01_technical_analyzer:8000",
    "fibonacci": "http://03_fibonacci_agent:8000",
    "gann": "http://05_gann_analyzer_agent:8000",
    "news": "http://06_news_sentiment_agent:8000"
}

LEARNING_AGENT_URL = "http://10_learning_agent:8000"

# Default parameters (fallback)
DEFAULT_PARAMS = {
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "default_leverage": 5,
    "size_pct": 0.15,
    "reverse_threshold": 2.0,
    "atr_multiplier_sl": 2.0,
    "atr_multiplier_tp": 3.0,
    "min_rsi_for_long": 40,
    "max_rsi_for_short": 60,
}

EVOLVED_PARAMS_FILE = "/data/evolved_params.json"
API_COSTS_FILE = "/data/api_costs.json"
AI_DECISIONS_FILE = "/data/ai_decisions.json"


def log_api_call(tokens_in: int, tokens_out: int):
    """
    Logga una chiamata API per il tracking dei costi DeepSeek.
    
    Args:
        tokens_in: Token input della richiesta
        tokens_out: Token output della risposta
    """
    try:
        # Carica i dati esistenti
        if os.path.exists(API_COSTS_FILE):
            with open(API_COSTS_FILE, 'r') as f:
                data = json.load(f)
        else:
            data = {'calls': []}
        
        # Aggiungi la nuova chiamata
        data['calls'].append({
            'timestamp': datetime.now().isoformat(),
            'tokens_in': tokens_in,
            'tokens_out': tokens_out
        })
        
        # Salva i dati aggiornati
        os.makedirs(os.path.dirname(API_COSTS_FILE), exist_ok=True)
        with open(API_COSTS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"API call logged: {tokens_in} in, {tokens_out} out")
    except Exception as e:
        logger.error(f"Error logging API call: {e}")


def save_ai_decision(decision_data):
    """Salva la decisione AI per visualizzarla nella dashboard"""
    try:
        decisions = []
        if os.path.exists(AI_DECISIONS_FILE):
            with open(AI_DECISIONS_FILE, 'r') as f:
                decisions = json.load(f)
        
        # Aggiungi nuova decisione
        decisions.append({
            'timestamp': datetime.now().isoformat(),
            'symbol': decision_data.get('symbol'),
            'action': decision_data.get('action'),  # OPEN_LONG, OPEN_SHORT, HOLD, CLOSE
            'leverage': decision_data.get('leverage', 1),
            'size_pct': decision_data.get('size_pct', 0),
            'rationale': decision_data.get('rationale', ''),
            'analysis_summary': decision_data.get('analysis_summary', '')
        })
        
        # Mantieni solo le ultime 100 decisioni
        decisions = decisions[-100:]
        
        os.makedirs(os.path.dirname(AI_DECISIONS_FILE), exist_ok=True)
        with open(AI_DECISIONS_FILE, 'w') as f:
            json.dump(decisions, f, indent=2)
            
        logger.info(f"AI decision saved: {decision_data.get('action')} on {decision_data.get('symbol')}")
    except Exception as e:
        logger.error(f"Error saving AI decision: {e}")


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

class ReverseAnalysisRequest(BaseModel):
    symbol: str
    current_position: Dict[str, Any]


def get_evolved_params() -> Dict[str, Any]:
    """Load evolved parameters from Learning Agent or use defaults"""
    try:
        if os.path.exists(EVOLVED_PARAMS_FILE):
            with open(EVOLVED_PARAMS_FILE, 'r') as f:
                data = json.load(f)
                version = data.get('version', 'unknown')
                logger.info(f"📚 Using evolved params {version}")
                return data.get("params", DEFAULT_PARAMS.copy())
        else:
            logger.info("📚 No evolved params found, using defaults")
            return DEFAULT_PARAMS.copy()
    except Exception as e:
        logger.warning(f"⚠️ Error loading evolved params: {e}")
        return DEFAULT_PARAMS.copy()


async def get_learning_insights():
    """Ottieni insights dal Learning Agent"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Performance recenti
            perf_resp = await client.get(f"{LEARNING_AGENT_URL}/performance")
            perf_data = perf_resp.json() if perf_resp.status_code == 200 else {}
            
            # Parametri evoluti
            params_resp = await client.get(f"{LEARNING_AGENT_URL}/current_params")
            params_data = params_resp.json() if params_resp.status_code == 200 else {}
            
            return {
                "performance": perf_data.get("performance", {}),
                "evolved_params": params_data.get("params", {}),
                "version": params_data.get("version", "unknown")
            }
    except Exception as e:
        logger.warning(f"⚠️ Could not get learning insights: {e}")
        return {}


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
async def decide_batch(payload: AnalysisPayload):
    try:
        # Load evolved parameters (hot-reload on each request)
        params = get_evolved_params()
        
        # Get learning insights from Learning Agent
        learning_insights = await get_learning_insights()
        
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
            "market_data": assets_summary,
            "learning_insights": learning_insights
        }
        
        # Enhanced system prompt with evolved parameters and learning insights
        insights_text = ""
        if learning_insights:
            perf = learning_insights.get("performance", {})
            if perf:
                insights_text = f"""

INSIGHTS DAL LEARNING AGENT (v{learning_insights.get('version', 'unknown')}):
- Trades recenti: {perf.get('total_trades', 0)}
- Win rate: {perf.get('win_rate', 0)*100:.1f}%
- PnL totale: {perf.get('total_pnl', 0):.2f}%
- Max drawdown: {perf.get('max_drawdown', 0):.2f}%

CONSIDERA questi dati di performance recenti nelle tue decisioni.
"""
        
        enhanced_system_prompt = SYSTEM_PROMPT + f"""

PARAMETRI OTTIMIZZATI (dall'evoluzione automatica):
- RSI Overbought (per short): {params.get('rsi_overbought', 70)}
- RSI Oversold (per long): {params.get('rsi_oversold', 30)}
- Leverage suggerito: {params.get('default_leverage', 5)}x
- Size per trade: {params.get('size_pct', 0.15)*100:.0f}% del wallet
- Soglia reverse: {params.get('reverse_threshold', 2.0)}%
- Min RSI per long: {params.get('min_rsi_for_long', 40)}
- Max RSI per short: {params.get('max_rsi_for_short', 60)}

USA QUESTI PARAMETRI EVOLUTI nelle tue decisioni.
{insights_text}"""

        response = client.chat.completions.create(
            model="gpt-5.1", 
            messages=[
                {"role": "system", "content": enhanced_system_prompt},
                {"role": "user", "content": f"ANALIZZA E AGISCI: {json.dumps(prompt_data)}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.7, # Più creatività = più trade
        )
        
        # Logga i costi API per tracking DeepSeek
        if hasattr(response, 'usage') and response.usage:
            log_api_call(
                tokens_in=response.usage.prompt_tokens,
                tokens_out=response.usage.completion_tokens
            )

        content = response.choices[0].message.content
        logger.info(f"AI Raw Response: {content}") # Debug nel log
        
        decision_json = json.loads(content)
        
        valid_decisions = []
        for d in decision_json.get("decisions", []):
            try: 
                valid_dec = Decision(**d)
                valid_decisions.append(valid_dec)
                
                # Salva la decisione per la dashboard
                save_ai_decision({
                    'symbol': valid_dec.symbol,
                    'action': valid_dec.action,
                    'leverage': valid_dec.leverage,
                    'size_pct': valid_dec.size_pct,
                    'rationale': valid_dec.rationale,
                    'analysis_summary': decision_json.get("analysis_summary", "")
                })
            except Exception as e: 
                logger.warning(f"Invalid decision: {e}")

        return {
            "analysis": decision_json.get("analysis_summary", "No analysis"),
            "decisions": [d.model_dump() for d in valid_decisions]
        }

    except Exception as e:
        logger.error(f"AI Critical Error: {e}")
        return {"analysis": "Error", "decisions": []}


@app.post("/analyze_reverse")
async def analyze_reverse(payload: ReverseAnalysisRequest):
    """
    Analizza posizione in perdita e decide: HOLD, CLOSE o REVERSE
    Raccoglie dati da tutti gli agenti per decisione informata
    """
    try:
        symbol = payload.symbol
        position = payload.current_position
        
        logger.info(f"🔍 Analyzing reverse for {symbol}: ROI={position.get('roi_pct', 0)*100:.2f}%")
        
        # Raccolta dati da tutti gli agenti
        agents_data = {}
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Technical Analysis
            try:
                resp = await client.post(
                    f"{AGENT_URLS['technical']}/analyze_multi_tf",
                    json={"symbol": symbol}
                )
                if resp.status_code == 200:
                    agents_data['technical'] = resp.json()
                    logger.info(f"✅ Technical data received for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Technical analyzer failed: {e}")
                agents_data['technical'] = {}
            
            # Fibonacci Analysis
            try:
                resp = await client.post(
                    f"{AGENT_URLS['fibonacci']}/analyze_fib",
                    json={"symbol": symbol}
                )
                if resp.status_code == 200:
                    agents_data['fibonacci'] = resp.json()
                    logger.info(f"✅ Fibonacci data received for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Fibonacci analyzer failed: {e}")
                agents_data['fibonacci'] = {}
            
            # Gann Analysis
            try:
                resp = await client.post(
                    f"{AGENT_URLS['gann']}/analyze_gann",
                    json={"symbol": symbol}
                )
                if resp.status_code == 200:
                    agents_data['gann'] = resp.json()
                    logger.info(f"✅ Gann data received for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Gann analyzer failed: {e}")
                agents_data['gann'] = {}
            
            # News Sentiment
            try:
                resp = await client.post(
                    f"{AGENT_URLS['news']}/analyze_sentiment",
                    json={"symbol": symbol}
                )
                if resp.status_code == 200:
                    agents_data['news'] = resp.json()
                    logger.info(f"✅ News sentiment received for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ News analyzer failed: {e}")
                agents_data['news'] = {}
        
        # Calcola recovery size usando la formula specificata
        pnl_dollars = position.get('pnl_dollars', 0)
        wallet_balance = position.get('wallet_balance', 0)
        
        # Se non abbiamo wallet_balance, usa una stima conservativa
        if wallet_balance == 0:
            wallet_balance = abs(pnl_dollars) * 3
        
        base_size_pct = 0.15
        loss_amount = abs(pnl_dollars)
        recovery_extra = (loss_amount / max(wallet_balance, 100)) / 0.02
        recovery_size_pct = min(base_size_pct + recovery_extra, 0.25)
        
        # Prepara prompt per DeepSeek
        prompt_data = {
            "symbol": symbol,
            "current_position": {
                "side": position.get('side'),
                "entry_price": position.get('entry_price'),
                "mark_price": position.get('mark_price'),
                "roi_pct": position.get('roi_pct', 0) * 100,  # Converti in percentuale
                "pnl_dollars": pnl_dollars,
                "leverage": position.get('leverage', 1)
            },
            "technical_analysis": agents_data.get('technical', {}),
            "fibonacci_analysis": agents_data.get('fibonacci', {}),
            "gann_analysis": agents_data.get('gann', {}),
            "news_sentiment": agents_data.get('news', {})
        }
        
        system_prompt = """Sei un TRADER ESPERTO che analizza posizioni in perdita.

DECISIONI POSSIBILI:
1. HOLD = È solo una correzione temporanea, il trend principale rimane valido. Mantieni la posizione.
2. CLOSE = Il trend è incerto, meglio chiudere e aspettare chiarezza. Non aprire nuove posizioni.
3. REVERSE = CHIARA INVERSIONE DI TREND confermata da MULTIPLI INDICATORI. Chiudi e apri posizione opposta.

CRITERI PER REVERSE (TUTTI devono essere soddisfatti):
- Almeno 3 indicatori tecnici confermano inversione
- RSI mostra chiaro over/undersold nella direzione opposta
- Fibonacci/Gann mostrano supporto/resistenza forte
- News/sentiment supportano la nuova direzione

CRITERI PER CLOSE:
- Indicatori contrastanti, no chiara direzione
- Alta volatilità o incertezza di mercato
- News negative o sentiment molto negativo

CRITERI PER HOLD:
- Trend principale ancora valido
- Solo correzione temporanea
- Supporti/resistenze tengono
- Indicatori mostrano possibile rimbalzo

FORMATO RISPOSTA JSON OBBLIGATORIO:
{
  "action": "HOLD" | "CLOSE" | "REVERSE",
  "confidence": 85,
  "rationale": "Spiegazione dettagliata basata sugli indicatori",
  "recovery_size_pct": 0.18
}

Usa recovery_size_pct fornito nel contesto per recuperare le perdite."""
        
        user_prompt = f"""ANALIZZA QUESTA POSIZIONE IN PERDITA E DECIDI:

{json.dumps(prompt_data, indent=2)}

Recovery size calcolato: {recovery_size_pct:.2f} ({recovery_size_pct*100:.1f}%)

Analizza TUTTI gli indicatori e decidi: HOLD, CLOSE o REVERSE."""
        
        response = client.chat.completions.create(
            model="gpt-5.1",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3  # Più conservativo per decisioni di risk management
        )
        
        # Log API costs
        if hasattr(response, 'usage') and response.usage:
            log_api_call(
                tokens_in=response.usage.prompt_tokens,
                tokens_out=response.usage.completion_tokens
            )
        
        content = response.choices[0].message.content
        logger.info(f"AI Reverse Analysis Response: {content}")
        
        decision = json.loads(content)
        
        # Valida e normalizza la risposta
        action = decision.get("action", "HOLD").upper()
        if action not in ["HOLD", "CLOSE", "REVERSE"]:
            action = "HOLD"
        
        confidence = max(0, min(100, decision.get("confidence", 50)))
        rationale = decision.get("rationale", "No rationale provided")
        
        # Usa recovery_size_pct dal decision se presente, altrimenti quello calcolato
        final_recovery_size = decision.get("recovery_size_pct", recovery_size_pct)
        final_recovery_size = max(0.05, min(0.25, final_recovery_size))
        
        result = {
            "action": action,
            "confidence": confidence,
            "rationale": rationale,
            "recovery_size_pct": final_recovery_size,
            "agents_data_summary": {
                "technical_available": bool(agents_data.get('technical')),
                "fibonacci_available": bool(agents_data.get('fibonacci')),
                "gann_available": bool(agents_data.get('gann')),
                "news_available": bool(agents_data.get('news'))
            }
        }
        
        logger.info(f"✅ Reverse analysis complete for {symbol}: {action} (confidence: {confidence}%)")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Reverse analysis error: {e}")
        # Default safe response
        return {
            "action": "HOLD",
            "confidence": 0,
            "rationale": f"Error during analysis: {str(e)}. Defaulting to HOLD for safety.",
            "recovery_size_pct": 0.15,
            "agents_data_summary": {}
        }


@app.get("/health")
def health(): return {"status": "active"}
