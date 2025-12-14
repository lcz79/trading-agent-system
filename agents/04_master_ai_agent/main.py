import os
import json
import logging
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI
from pydantic import BaseModel, field_validator
from typing import Dict, Any, Literal, Optional, List
from openai import OpenAI
from threading import Lock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MasterAI")

app = FastAPI()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# Agent URLs for reverse analysis
AGENT_URLS = {
    "technical": "http://01_technical_analyzer:8000",
    "fibonacci": "http://03_fibonacci_agent:8000",
    "gann": "http://05_gann_analyzer_agent:8000",
    "news": "http://06_news_sentiment_agent:8000",
    "forecaster": "http://08_forecaster_agent:8000"
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
RECENT_CLOSES_FILE = "/data/recent_closes.json"
TRADING_HISTORY_FILE = "/data/trading_history.json"

# Configuration constants
# Possono essere sovrascritti da variabili d'ambiente se necessario
LOSS_THRESHOLD_PCT = float(os.getenv("LOSS_THRESHOLD_PCT", "-5"))  # Soglia perdita trade
MAX_RECENT_LOSSES = int(os.getenv("MAX_RECENT_LOSSES", "10"))  # Numero max perdite recenti
MIN_CONFIRMATIONS_REQUIRED = 3  # Numero minimo di conferme per aprire una posizione
CONFIDENCE_THRESHOLD_LOW = 50  # Soglia confidenza bassa per blocco automatico

# Cooldown configuration
COOLDOWN_MINUTES = 15

file_lock = Lock()


def ensure_parent_dir(path: str) -> None:
    """Crea la directory padre se non esiste"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def load_json_file(filepath: str, default: Any = None):
    """Carica file JSON con gestione thread-safe"""
    if default is None:
        default = []
    with file_lock:
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return json.load(f)
            return default
        except Exception as e:
            logger.error(f"Errore caricamento {filepath}: {e}")
            return default


def save_json_file(filepath: str, data: Any):
    """Salva file JSON con gestione thread-safe"""
    ensure_parent_dir(filepath)
    with file_lock:
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Errore salvataggio {filepath}: {e}")
            return False


def save_close_event(symbol: str, side: str, reason: str):
    """Salva evento di chiusura per cooldown"""
    closes = load_json_file(RECENT_CLOSES_FILE, [])
    now = datetime.now()
    closes.append({
        "timestamp": now.isoformat(),
        "symbol": symbol,
        "side": side,
        "reason": reason
    })
    # Mantieni solo ultime 24 ore - usa confronto stringhe per efficienza
    # Nota: datetime.isoformat() produce formato ordinabile (ISO 8601)
    cutoff_ts = (now - timedelta(hours=24)).isoformat()
    closes = [c for c in closes if c.get("timestamp", "") > cutoff_ts]
    save_json_file(RECENT_CLOSES_FILE, closes)
    logger.info(f"💾 Cooldown salvato: {symbol} {side} - {reason}")


def load_recent_closes(minutes: int = COOLDOWN_MINUTES) -> List[dict]:
    """Carica chiusure negli ultimi N minuti"""
    closes = load_json_file(RECENT_CLOSES_FILE, [])
    cutoff = datetime.now() - timedelta(minutes=minutes)
    cutoff_ts = cutoff.isoformat()
    
    # Ottimizzazione: confronta stringhe ISO invece di parsing
    # Funziona perché datetime.isoformat() produce formato ordinabile lessicograficamente
    # Es: "2024-01-15T10:30:00" < "2024-01-15T11:30:00"
    recent = [c for c in closes if c.get("timestamp", "") > cutoff_ts]
    return recent


def calculate_performance(trades: List[dict]) -> dict:
    """Calcola metriche di performance da lista trade"""
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
        }
    
    completed_trades = [t for t in trades if t.get('pnl_pct') is not None]
    
    if not completed_trades:
        return {
            "total_trades": len(trades),
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
        }
    
    total_pnl = sum(t.get('pnl_pct', 0) for t in completed_trades)
    winning_trades = [t for t in completed_trades if t.get('pnl_pct', 0) > 0]
    losing_trades = [t for t in completed_trades if t.get('pnl_pct', 0) <= 0]
    
    win_rate = len(winning_trades) / len(completed_trades) if completed_trades else 0
    
    # Simple drawdown calculation
    cumulative_pnl = 0
    peak = 0
    max_drawdown = 0
    for trade in completed_trades:
        cumulative_pnl += trade.get('pnl_pct', 0)
        peak = max(peak, cumulative_pnl)
        drawdown = peak - cumulative_pnl
        max_drawdown = max(max_drawdown, drawdown)
    
    return {
        "total_trades": len(completed_trades),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "max_drawdown": round(max_drawdown, 2),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
    }


def normalize_position_side(side_raw: str) -> Optional[str]:
    """Normalizza side verso 'long' / 'short'"""
    s = (side_raw or "").lower().strip()
    if s in ("long", "buy"):
        return "long"
    if s in ("short", "sell"):
        return "short"
    return None


def enforce_decision_consistency(decision_dict: dict) -> dict:
    """
    Applica guardrail per garantire coerenza nella decisione AI.
    Post-processa il JSON per:
    1. Garantire che direction_considered sia coerente con action
    2. Garantire che blocked_by sia presente se action=HOLD con bassa confidence
    3. Separare setup_confirmations da risk_factors
    4. Validare che rationale non contenga contraddizioni
    """
    action = decision_dict.get('action', 'HOLD')
    confidence = decision_dict.get('confidence', 50)
    
    # 1. Inferisci direction_considered da action se mancante
    if not decision_dict.get('direction_considered'):
        if action == 'OPEN_LONG':
            decision_dict['direction_considered'] = 'LONG'
        elif action == 'OPEN_SHORT':
            decision_dict['direction_considered'] = 'SHORT'
        else:
            decision_dict['direction_considered'] = 'NONE'
    
    # 2. Valida coerenza action vs direction_considered
    direction = decision_dict.get('direction_considered', 'NONE')
    if action == 'OPEN_LONG' and direction != 'LONG':
        logger.warning(f"⚠️ Incoerenza rilevata: OPEN_LONG ma direction={direction}, corretto a LONG")
        decision_dict['direction_considered'] = 'LONG'
    elif action == 'OPEN_SHORT' and direction != 'SHORT':
        logger.warning(f"⚠️ Incoerenza rilevata: OPEN_SHORT ma direction={direction}, corretto a SHORT")
        decision_dict['direction_considered'] = 'SHORT'
    
    # 3. Se setup_confirmations non è presente, usa confirmations (backward compat)
    if not decision_dict.get('setup_confirmations') and decision_dict.get('confirmations'):
        decision_dict['setup_confirmations'] = decision_dict['confirmations']
    
    # 4. Inferisci blocked_by se action=HOLD con bassa confidence
    if action == 'HOLD' and not decision_dict.get('blocked_by'):
        if confidence < CONFIDENCE_THRESHOLD_LOW:
            decision_dict['blocked_by'] = ['LOW_CONFIDENCE']
            logger.info(f"✅ Inferito blocked_by=['LOW_CONFIDENCE'] per HOLD con confidence={confidence}")
        elif not decision_dict.get('setup_confirmations') or len(decision_dict.get('setup_confirmations', [])) < MIN_CONFIRMATIONS_REQUIRED:
            decision_dict['blocked_by'] = ['CONFLICTING_SIGNALS']
            logger.info(f"✅ Inferito blocked_by=['CONFLICTING_SIGNALS'] per HOLD con poche conferme")
    
    # 5. Se ci sono blocked_by, action DEVE essere HOLD (o CLOSE se posizione aperta)
    if decision_dict.get('blocked_by') and action not in ['HOLD', 'CLOSE']:
        logger.warning(f"⚠️ Incoerenza: blocked_by presente ma action={action}, forzato a HOLD")
        decision_dict['action'] = 'HOLD'
        decision_dict['leverage'] = 1.0
        decision_dict['size_pct'] = 0.0
    
    # 6. Valida rationale per contraddizioni comuni
    rationale = decision_dict.get('rationale', '').lower()
    if action == 'OPEN_SHORT':
        # Non dovrebbe menzionare "long setup" o "buy" come setup considerato
        if any(phrase in rationale for phrase in ['long setup', 'aprire long', 'opening long', 'setup long']):
            logger.warning(f"⚠️ Rationale per OPEN_SHORT menziona 'long setup', potrebbe essere incoerente")
    elif action == 'OPEN_LONG':
        # Non dovrebbe menzionare "short setup" o "sell" come setup considerato
        if any(phrase in rationale for phrase in ['short setup', 'aprire short', 'opening short', 'setup short']):
            logger.warning(f"⚠️ Rationale per OPEN_LONG menziona 'short setup', potrebbe essere incoerente")
    
    return decision_dict


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
            'analysis_summary': decision_data.get('analysis_summary', ''),
            'confidence': decision_data.get('confidence'),
            'confirmations': decision_data.get('confirmations', []),
            'risk_factors': decision_data.get('risk_factors', []),
            'source': decision_data.get('source', 'master_ai'),
            # New structured fields
            'setup_confirmations': decision_data.get('setup_confirmations', []),
            'blocked_by': decision_data.get('blocked_by', []),
            'direction_considered': decision_data.get('direction_considered', 'NONE')
        })
        
        # Mantieni solo le ultime 100 decisioni
        decisions = decisions[-100:]
        
        os.makedirs(os.path.dirname(AI_DECISIONS_FILE), exist_ok=True)
        with open(AI_DECISIONS_FILE, 'w') as f:
            json.dump(decisions, f, indent=2)
            
        logger.info(f"💾 AI decision saved: {decision_data.get('action')} on {decision_data.get('symbol')}")
    except Exception as e:
        logger.error(f"Error saving AI decision: {e}")


# Blocker reasons for structured decisions
BLOCKER_REASONS = Literal[
    "INSUFFICIENT_MARGIN",
    "MAX_POSITIONS",
    "COOLDOWN",
    "DRAWDOWN_GUARD",
    "PATTERN_LOSING",
    "CONFLICTING_SIGNALS",
    "LOW_CONFIDENCE"
]

class Decision(BaseModel):
    symbol: str
    action: Literal["OPEN_LONG", "OPEN_SHORT", "HOLD", "CLOSE"]
    leverage: float = 1.0  
    size_pct: float = 0.0
    rationale: str
    confidence: Optional[int] = None
    confirmations: Optional[List[str]] = None
    risk_factors: Optional[List[str]] = None
    # New structured fields for coherence
    setup_confirmations: Optional[List[str]] = None
    blocked_by: Optional[List[BLOCKER_REASONS]] = None
    direction_considered: Optional[Literal["LONG", "SHORT", "NONE"]] = None

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
    """Ottieni insights dal Learning Agent per il contesto di DeepSeek"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            # Performance recenti
            perf_resp = await http_client.get(f"{LEARNING_AGENT_URL}/performance")
            perf_data = perf_resp.json() if perf_resp.status_code == 200 else {}
            
            # Storico trade per pattern analysis
            performance = perf_data.get("performance", {})
            
            # Carica trading history per pattern analysis
            trading_history = load_json_file(TRADING_HISTORY_FILE, [])
            recent_losses = [t for t in trading_history if t.get('pnl_pct', 0) < LOSS_THRESHOLD_PCT][-MAX_RECENT_LOSSES:]
            
            # Identifica losing patterns
            losing_patterns = []
            for trade in recent_losses:
                market_cond = trade.get('market_conditions', {})
                losing_patterns.append(f"{trade.get('symbol')} {trade.get('side')}: {market_cond}")
            
            return {
                "performance": {
                    "win_rate": performance.get('win_rate', 0) * 100,
                    "total_pnl": performance.get('total_pnl', 0),
                    "max_drawdown": performance.get('max_drawdown', 0),
                    "winning_trades": performance.get('winning_trades', 0),
                    "losing_trades": performance.get('losing_trades', 0),
                    "total_trades": performance.get('total_trades', 0)
                },
                "recent_losses": recent_losses[:5],  # Ultimi 5 trade in perdita
                "losing_patterns": losing_patterns[:3],  # Top 3 pattern perdenti
            }
    except Exception as e:
        logger.warning(f"⚠️ Could not get learning insights: {e}")
        return {
            "performance": {},
            "recent_losses": [],
            "losing_patterns": []
        }


async def collect_full_analysis(symbol: str, http_client) -> dict:
    """Raccoglie tutti i dati da tutti gli agenti per un asset"""
    data = {}
    
    # Technical Analysis (già implementato tramite orchestrator)
    # Viene passato direttamente nel payload
    
    # Fibonacci
    try:
        resp = await http_client.post(
            f"{AGENT_URLS['fibonacci']}/analyze_fib",
            json={"symbol": symbol},
            timeout=10.0
        )
        if resp.status_code == 200:
            data['fibonacci'] = resp.json()
            logger.info(f"✅ Fibonacci data per {symbol}")
    except Exception as e:
        logger.warning(f"⚠️ Fibonacci failed for {symbol}: {e}")
        data['fibonacci'] = {}
    
    # Gann
    try:
        resp = await http_client.post(
            f"{AGENT_URLS['gann']}/analyze_gann",
            json={"symbol": symbol},
            timeout=10.0
        )
        if resp.status_code == 200:
            data['gann'] = resp.json()
            logger.info(f"✅ Gann data per {symbol}")
    except Exception as e:
        logger.warning(f"⚠️ Gann failed for {symbol}: {e}")
        data['gann'] = {}
    
    # News Sentiment
    try:
        resp = await http_client.post(
            f"{AGENT_URLS['news']}/analyze_sentiment",
            json={"symbol": symbol},
            timeout=10.0
        )
        if resp.status_code == 200:
            data['news'] = resp.json()
            logger.info(f"✅ News sentiment per {symbol}")
    except Exception as e:
        logger.warning(f"⚠️ News failed for {symbol}: {e}")
        data['news'] = {}
    
    # Forecast
    try:
        resp = await http_client.post(
            f"{AGENT_URLS['forecaster']}/forecast",
            json={"symbol": symbol},
            timeout=10.0
        )
        if resp.status_code == 200:
            data['forecast'] = resp.json()
            logger.info(f"✅ Forecast data per {symbol}")
    except Exception as e:
        logger.warning(f"⚠️ Forecaster failed for {symbol}: {e}")
        data['forecast'] = {}
    
    return data


SYSTEM_PROMPT = """
Sei un TRADER PROFESSIONISTA con 20 anni di esperienza sui mercati crypto.
Il tuo obiettivo è MASSIMIZZARE I PROFITTI minimizzando i rischi.

## PROCESSO DECISIONALE STRUTTURATO

1. **ANALIZZA TUTTI I DATI** - Non basarti su un solo indicatore
2. **IDENTIFICA LA DIREZIONE** - Determina quale setup stai valutando (LONG, SHORT o NONE)
3. **RACCOGLI CONFERME** - Elenca tutte le conferme per il setup specifico
4. **APPLICA VINCOLI** - Verifica se ci sono blocchi (margin, positions, cooldown, drawdown, ecc.)
5. **DECIDI AZIONE** - Se bloccato → HOLD, altrimenti segui le conferme

## CONFERME NECESSARIE PER APRIRE (almeno 3 su 5)
- ✅ Trend concorde su almeno 2 timeframe (15m, 1h, 4h)
- ✅ RSI in zona di ipervenduto/ipercomprato appropriata per la direzione del trade
- ✅ Prezzo vicino a livello chiave (Fibonacci o Gann)
- ✅ Sentiment/news non contrario
- ✅ Forecast concorde con la direzione

## VINCOLI CHE BLOCCANO L'APERTURA
- INSUFFICIENT_MARGIN: Margine disponibile insufficiente
- MAX_POSITIONS: Massimo numero posizioni raggiunto
- COOLDOWN: Posizione chiusa di recente nella stessa direzione
- DRAWDOWN_GUARD: Sistema in drawdown eccessivo
- PATTERN_LOSING: Pattern con storico di perdite
- CONFLICTING_SIGNALS: Segnali contrastanti tra indicatori
- LOW_CONFIDENCE: Confidenza < 50%

## REGOLE DI COERENZA CRITICA
- **DIREZIONE**: Se action è OPEN_SHORT, direction_considered DEVE essere "SHORT" e setup_confirmations devono essere per SHORT
- **SEPARAZIONE**: NON mescolare risk factors con setup confirmations
- **BLOCCO**: Se blocked_by è presente, action DEVE essere HOLD (o CLOSE se applicabile)
- **RATIONALE**: Deve riflettere la logica strutturata: setup analizzato → conferme trovate → vincoli applicati → decisione

Esempio CORRETTO per OPEN_SHORT:
- direction_considered: "SHORT"
- setup_confirmations: ["Trend bearish confermato su 1h e 4h", "RSI > 60 (zona ipercomprato)", "Resistenza Fibonacci rifiutata"]
- blocked_by: [] (vuoto se non bloccato)
- rationale: "Analizzato setup SHORT: trovate 3 conferme bearish. Nessun vincolo attivo. Apertura SHORT con leverage moderato."

Esempio ERRATO da EVITARE:
- action: "OPEN_SHORT" ma setup_confirmations contiene "BTC long setup con RSI basso" ❌

## GESTIONE RISCHIO DINAMICA
Decidi TU leva e size in base alla tua confidenza e alle condizioni di mercato:
- Alta confidenza (90%+): considera leverage più alto e size maggiore
- Media confidenza (70-89%): usa leverage moderato e size standard
- Bassa confidenza (50-69%): riduci leverage e size
- Confidenza insufficiente (<50%): NON APRIRE (HOLD) e usa blocked_by: ["LOW_CONFIDENCE"]

Considera anche:
- Volatilità del mercato (alta volatilità → leverage più basso)
- Numero di conferme (più conferme → maggiore fiducia)
- Performance recente del sistema (se in drawdown → più conservativo)

## OUTPUT JSON OBBLIGATORIO
{
  "analysis_summary": "Sintesi ragionata della situazione",
  "decisions": [
    {
      "symbol": "ETHUSDT",
      "action": "OPEN_LONG|OPEN_SHORT|HOLD",
      "leverage": 5.0,
      "size_pct": 0.15,
      "confidence": 75,
      "rationale": "Spiegazione dettagliata seguendo processo strutturato",
      "confirmations": ["lista conferme generali (backward compat)"],
      "risk_factors": ["lista rischi identificati (backward compat)"],
      "setup_confirmations": ["conferme specifiche per la direzione considerata"],
      "blocked_by": ["INSUFFICIENT_MARGIN", "MAX_POSITIONS", "COOLDOWN", "DRAWDOWN_GUARD", "PATTERN_LOSING", "CONFLICTING_SIGNALS", "LOW_CONFIDENCE"],
      "direction_considered": "LONG|SHORT|NONE"
    }
  ]
}

RICORDA: Meglio HOLD che un trade perdente. Non forzare mai. Mantieni coerenza tra direction_considered, setup_confirmations e action.
"""

@app.post("/decide_batch")
async def decide_batch(payload: AnalysisPayload):
    try:
        # 1. Carica chiusure recenti (cooldown)
        recent_closes = load_recent_closes(COOLDOWN_MINUTES)
        
        # 2. Carica storico trading per apprendimento
        trading_history = load_json_file(TRADING_HISTORY_FILE, [])
        recent_losses = [t for t in trading_history if t.get('pnl_pct', 0) < -5][-10:]
        
        # 3. Calcola performance sistema
        performance = calculate_performance(trading_history[-50:])  # Ultimi 50 trade
        
        # 4. Get learning insights
        learning_insights = await get_learning_insights()
        
        # 5. Per ogni asset, raccogli TUTTI i dati dagli agenti
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            # Ottieni lista asset da analizzare (quelli senza posizione aperta)
            already_open = payload.global_data.get('already_open', [])
            
            # Arricchisci assets_data con dati da tutti gli agenti
            enriched_assets_data = {}
            for symbol, asset_data in payload.assets_data.items():
                # Raccoglie dati da Fibonacci, Gann, News, Forecast
                additional_data = await collect_full_analysis(symbol, http_client)
                
                # Combina technical analysis (già presente) con nuovi dati
                enriched_assets_data[symbol] = {
                    "technical": asset_data.get('tech', {}),
                    "fibonacci": additional_data.get('fibonacci', {}),
                    "gann": additional_data.get('gann', {}),
                    "news": additional_data.get('news', {}),
                    "forecast": additional_data.get('forecast', {})
                }
        
        # 6. Costruisci prompt con TUTTO il contesto
        # Estrai informazioni sui vincoli dal payload
        max_positions = payload.global_data.get('max_positions', 3)
        positions_open_count = payload.global_data.get('positions_open_count', len(already_open))
        wallet_info = payload.global_data.get('wallet', {})
        drawdown_pct = payload.global_data.get('drawdown_pct', 0)
        
        prompt_data = {
            "wallet_equity": payload.global_data.get('portfolio', {}).get('equity'),
            "wallet_available": wallet_info.get('available', 0),
            "wallet_available_for_trades": wallet_info.get('available_for_new_trades', 0),
            "max_positions": max_positions,
            "positions_open_count": positions_open_count,
            "positions_remaining": max(0, max_positions - positions_open_count),
            "drawdown_pct": drawdown_pct,
            "active_positions": already_open,
            "market_data": enriched_assets_data,
            "recent_closes": recent_closes,
            "recent_losses": recent_losses[:5],
            "system_performance": performance,
            "learning_insights": learning_insights
        }
        
        # 7. Costruisci contesto per DeepSeek con informazioni sui vincoli
        constraints_text = f"""
## VINCOLI ATTUALI DEL SISTEMA
- Posizioni aperte: {positions_open_count}/{max_positions}
- Wallet disponibile: ${wallet_info.get('available', 0):.2f}
- Wallet per nuovi trade: ${wallet_info.get('available_for_new_trades', 0):.2f}
- Drawdown corrente: {drawdown_pct:.2f}%

⚠️ IMPORTANTE: 
- Se positions_open_count >= max_positions, usa blocked_by: ["MAX_POSITIONS"]
- Se wallet_available_for_new_trades < $100, usa blocked_by: ["INSUFFICIENT_MARGIN"]
- Se drawdown_pct < -10%, usa blocked_by: ["DRAWDOWN_GUARD"]
"""
        
        cooldown_text = ""
        if recent_closes:
            cooldown_text = "\n\n## CHIUSURE RECENTI (ultimi 15 minuti)\n"
            for close in recent_closes:
                cooldown_text += f"- {close['symbol']} {close['side'].upper()} chiuso: {close['reason']}\n"
            cooldown_text += "\n⚠️ NON riaprire queste posizioni nella stessa direzione! Se tentato, usa blocked_by: ['COOLDOWN']"
        
        performance_text = ""
        if performance.get('total_trades', 0) > 0:
            performance_text = f"""

## PERFORMANCE SISTEMA RECENTE
- Totale trade: {performance['total_trades']}
- Win rate: {performance['win_rate']*100:.1f}%
- PnL totale: {performance['total_pnl']:.2f}%
- Max drawdown: {performance['max_drawdown']:.2f}%
- Trade vincenti: {performance['winning_trades']}
- Trade perdenti: {performance['losing_trades']}
"""
        
        learning_text = ""
        if learning_insights.get('losing_patterns'):
            learning_text = "\n\n## PATTERN PERDENTI DA EVITARE\n"
            for pattern in learning_insights['losing_patterns']:
                learning_text += f"- {pattern}\n"
        
        enhanced_system_prompt = SYSTEM_PROMPT + constraints_text + cooldown_text + performance_text + learning_text
        
        response = client.chat.completions.create(
            model="deepseek-chat", 
            messages=[
                {"role": "system", "content": enhanced_system_prompt},
                {"role": "user", "content": f"ANALIZZA E DECIDI: {json.dumps(prompt_data, indent=2)}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        
        # Logga i costi API per tracking DeepSeek
        if hasattr(response, 'usage') and response.usage:
            log_api_call(
                tokens_in=response.usage.prompt_tokens,
                tokens_out=response.usage.completion_tokens
            )

        content = response.choices[0].message.content
        logger.info(f"AI Raw Response: {content}")
        
        decision_json = json.loads(content)
        
        valid_decisions = []
        for d in decision_json.get("decisions", []):
            try:
                # Applica guardrail per garantire coerenza
                d = enforce_decision_consistency(d)
                
                valid_dec = Decision(**d)
                valid_decisions.append(valid_dec)
                
                # Salva la decisione per la dashboard
                save_ai_decision({
                    'symbol': valid_dec.symbol,
                    'action': valid_dec.action,
                    'leverage': valid_dec.leverage,
                    'size_pct': valid_dec.size_pct,
                    'rationale': valid_dec.rationale,
                    'analysis_summary': decision_json.get("analysis_summary", ""),
                    'confidence': valid_dec.confidence,
                    'confirmations': valid_dec.confirmations or [],
                    'risk_factors': valid_dec.risk_factors or [],
                    'source': 'master_ai',
                    'setup_confirmations': valid_dec.setup_confirmations or [],
                    'blocked_by': valid_dec.blocked_by or [],
                    'direction_considered': valid_dec.direction_considered or 'NONE'
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
        
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            # Technical Analysis
            try:
                resp = await http_client.post(
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
                resp = await http_client.post(
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
                resp = await http_client.post(
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
                resp = await http_client.post(
                    f"{AGENT_URLS['news']}/analyze_sentiment",
                    json={"symbol": symbol}
                )
                if resp.status_code == 200:
                    agents_data['news'] = resp.json()
                    logger.info(f"✅ News sentiment received for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ News analyzer failed: {e}")
                agents_data['news'] = {}
            
            # Forecaster
            try:
                resp = await http_client.post(
                    f"{AGENT_URLS['forecaster']}/forecast",
                    json={"symbol": symbol}
                )
                if resp.status_code == 200:
                    agents_data['forecaster'] = resp.json()
                    logger.info(f"✅ Forecast data received for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Forecaster failed: {e}")
                agents_data['forecaster'] = {}
        
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
            "news_sentiment": agents_data.get('news', {}),
            "forecast": agents_data.get('forecaster', {})
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
- Forecast prevede movimento nella direzione opposta

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
            model="deepseek-chat",
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
                "news_available": bool(agents_data.get('news')),
                "forecast_available": bool(agents_data.get('forecaster'))
            }
        }
        
        # Salva evento di chiusura se l'azione è CLOSE o REVERSE
        if action in ["CLOSE", "REVERSE"]:
            side_dir = normalize_position_side(position.get('side', '')) or "long"
            save_close_event(
                symbol=symbol,
                side=side_dir,
                reason=f"{action}: {rationale[:100]}"  # Primi 100 char del rationale
            )
        
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
