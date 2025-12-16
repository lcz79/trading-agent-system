import os
import json
import logging
import httpx
import asyncio
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
    learning_params: Optional[Dict[str, Any]] = None

class ReverseAnalysisRequest(BaseModel):
    symbol: str
    current_position: Dict[str, Any]

class PositionData(BaseModel):
    """Dati di una singola posizione critica"""
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    mark_price: float
    leverage: float
    size: Optional[float] = None
    pnl: Optional[float] = None
    is_disabled: Optional[bool] = False  # Se il simbolo è disabilitato

class ManageCriticalPositionsRequest(BaseModel):
    """Richiesta per gestire posizioni critiche in perdita"""
    positions: List[PositionData]
    portfolio_snapshot: Optional[Dict[str, Any]] = None  # equity, free balance, etc.
    learning_params: Optional[dict] = None


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

## REGOLE RSI (ANTI-CONTRADDIZIONE)
- Mean-reversion (default):
  - Se direction_considered = "LONG": RSI basso (es. < 35) è a favore del LONG (possibile rimbalzo). RSI alto (> 65) è contro LONG.
  - Se direction_considered = "SHORT": RSI alto (es. > 65) è a favore dello SHORT (possibile ritracciamento). RSI basso (< 35) è contro SHORT.
- Eccezione trend-following (solo se trend molto forte e confermato multi-timeframe):
  - Puoi considerare SHORT anche con RSI basso (< 35) solo se ci sono conferme di continuazione ribassista (lower highs/lower lows, breakdown di supporto, momentum/MACD coerente, nessun segnale chiaro di reversal). In questo caso scrivi nel rationale che stai seguendo il trend e che RSI oversold e` un rischio di rimbalzo.
- In ogni caso: NON dire mai "RSI oversold e` una conferma per SHORT" senza spiegare l`eccezione trend-following.

Decidi TU leva e size in base alla tua confidenza e alle condizioni di mercato:
- Alta confidenza (90%+): considera leverage più alto e size maggiore
- Media confidenza (70-89%): usa leverage moderato e size standard
- Bassa confidenza (50-69%): riduci leverage e size
- Confidenza insufficiente (<50%): NON APRIRE (HOLD) e usa blocked_by: ["LOW_CONFIDENCE"]

Considera anche:
- Volatilità del mercato (alta volatilità → leverage più basso)
- Numero di conferme (più conferme → maggiore fiducia)
- Performance recente del sistema (se in drawdown → più conservativo)

## QUANDO NON APRIRE (HOLD)
- Indicatori contrastanti
- Nessuna conferma multipla
- Appena chiusa posizione simile
- Pattern storicamente perdente
- Mercato troppo incerto/volatile
- Performance sistema in forte drawdown
- **MARGINE INSUFFICIENTE**: available_for_new_trades < 10.0 USDT (BLOCCANTE)

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
        payload_learning_params = (payload.learning_params or {}) if hasattr(payload, "learning_params") else {}
        payload_learning_params_params = (payload_learning_params.get("params") if isinstance(payload_learning_params, dict) else {}) or {}
        payload_learning_params_meta = {
            "status": payload_learning_params.get("status") if isinstance(payload_learning_params, dict) else None,
            "version": payload_learning_params.get("version") if isinstance(payload_learning_params, dict) else None,
            "evolved_at": payload_learning_params.get("evolved_at") if isinstance(payload_learning_params, dict) else None,
        }

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
        # Estrai informazioni dal payload (tutte da portfolio e global_data)
        max_positions = payload.global_data.get('max_positions', 3)
        positions_open_count = payload.global_data.get('positions_open_count', len(already_open))
        drawdown_pct = payload.global_data.get('drawdown_pct', 0)
        learning_context = payload.global_data.get('learning_context', {})
        
        # Leggi dati wallet da portfolio
        portfolio = payload.global_data.get('portfolio', {})
        wallet_equity = portfolio.get('equity', 0)
        wallet_available = portfolio.get('available', 0)
        # Fallback: se available_for_new_trades manca, usa 95% di available (come orchestrator)
        wallet_available_for_new_trades = portfolio.get('available_for_new_trades', 
                                                        max(0.0, wallet_available * 0.95) if wallet_available > 0 else 0.0)
        wallet_source = portfolio.get('available_source', 'unknown')
        
        # Hard constraint: se margine insufficiente, blocca nuove aperture
        margin_threshold = 10.0
        can_open_new_positions = wallet_available_for_new_trades >= margin_threshold
        
        prompt_data = {
            "wallet": {
                "equity": wallet_equity,
                "available": wallet_available,
                "available_for_new_trades": wallet_available_for_new_trades,
                "available_source": wallet_source,
                "can_open_new_positions": can_open_new_positions,
                "margin_threshold": margin_threshold
            },
            "max_positions": max_positions,
            "positions_open_count": positions_open_count,
            "positions_remaining": max(0, max_positions - positions_open_count),
            "drawdown_pct": drawdown_pct,
            "active_positions": already_open,
            "market_data": enriched_assets_data,
            "recent_closes": recent_closes,
            "recent_losses": recent_losses[:5],
            "system_performance": performance,
            "learning_insights": learning_insights,
            "learning_params": payload_learning_params_params,
            "learning_params_meta": payload_learning_params_meta,
            "learning_context": learning_context  # Nuovo: contesto di apprendimento completo
        }
        
        # 7. Costruisci contesto per DeepSeek con informazioni sui vincoli
        constraints_text = f"""
## VINCOLI ATTUALI DEL SISTEMA
- Posizioni aperte: {positions_open_count}/{max_positions}
- Wallet disponibile: ${wallet_available:.2f}
- Wallet per nuovi trade: ${wallet_available_for_new_trades:.2f}
- Drawdown corrente: {drawdown_pct:.2f}%

⚠️ IMPORTANTE: 
- Se positions_open_count >= max_positions, usa blocked_by: ["MAX_POSITIONS"]
- Se wallet_available_for_new_trades < 10.0 USDT, usa blocked_by: ["INSUFFICIENT_MARGIN"]
- Se drawdown_pct < -10%, usa blocked_by: ["DRAWDOWN_GUARD"]
"""
        
        # 8. Costruisci contesto per DeepSeek
        margin_text = ""
        if not can_open_new_positions:
            margin_text = f"""

## ⚠️ MARGINE INSUFFICIENTE - NUOVE APERTURE BLOCCATE
- Available for new trades: {wallet_available_for_new_trades:.2f} USDT
- Soglia minima: {margin_threshold:.2f} USDT
- Fonte dati: {wallet_source}
- **AZIONE RICHIESTA**: Ritorna solo HOLD per tutti gli asset. Non aprire nuove posizioni.
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
        learning_policy_text = ""
        if payload_learning_params_params:
            learning_policy_text = f"""
## LEARNING POLICY (guidance, NOT hard rules)
- Questi parametri sono evoluti dal Learning Agent e servono come guardrail.
- Puoi scegliere leva e size liberamente, ma se fai override rispetto alla policy devi spiegarlo nel rationale.
- In generale: se vai contro policy, riduci rischio (leva/size) e aumenta prudenza.

Evolved params (guidance):
{json.dumps(payload_learning_params_params, indent=2)[:1200]}
"""

        if learning_insights.get('losing_patterns'):
            learning_text = "\n\n## PATTERN PERDENTI DA EVITARE\n"
            for pattern in learning_insights['losing_patterns']:
                learning_text += f"- {pattern}\n"
        
        # Costruisci sezione learning context
        learning_context_text = ""
        if learning_context and learning_context.get("status") == "success":
            lc_perf = learning_context.get("performance", {})
            lc_recent = learning_context.get("recent_trades", [])
            lc_by_symbol = learning_context.get("by_symbol", {})
            lc_risk = learning_context.get("risk_flags", {})
            
            learning_context_text = f"""

## LEARNING CONTEXT (Historical Performance & Risk Signals)
Use this context to adjust your aggressiveness and selectivity, while keeping full discretion on leverage and position size.

### Overall Performance (last {learning_context.get('period_hours', 0)} hours)
- Total trades: {lc_perf.get('total_trades', 0)}
- Win rate: {lc_perf.get('win_rate', 0)*100:.1f}%
- Total PnL: {lc_perf.get('total_pnl', 0):.2f}%
- Max drawdown: {lc_perf.get('max_drawdown', 0):.2f}%
- Winning: {lc_perf.get('winning_trades', 0)} | Losing: {lc_perf.get('losing_trades', 0)}

### Per-Symbol Performance
"""
            if lc_by_symbol:
                for symbol, stats in lc_by_symbol.items():
                    line = (
                        f"- **{symbol}**: {stats.get('total_trades', 0)} trades, "
                        f"win_rate={stats.get('win_rate', 0)*100:.0f}%, "
                        f"total_pnl={stats.get('total_pnl', 0):.1f}%, "
                        f"avg_pnl={stats.get('avg_pnl', 0):.1f}%, "
                        f"max_dd={stats.get('max_drawdown', 0):.1f}%\n"
                    )
                    learning_context_text += line
            else:
                learning_context_text += "- No per-symbol data available yet\n"
            
            learning_context_text += f"""
### Risk Flags (Heuristics)
- Losing streak: {lc_risk.get('losing_streak_count', 0)} consecutive losses
- Last trade PnL: {lc_risk.get('last_trade_pnl_pct', 0):.2f}%
- Negative PnL period: {'YES' if lc_risk.get('negative_pnl_period', False) else 'NO'}
- High drawdown period: {'YES' if lc_risk.get('high_drawdown_period', False) else 'NO'}

### Recent Trades Sample (last {len(lc_recent)} completed)
"""
            # Mostra solo gli ultimi 5 trade per non appesantire il prompt
            for trade in lc_recent[-5:]:
                ts = trade.get('timestamp', '')[:16]  # Solo data e ora
                sym = trade.get('symbol', 'UNK')
                side = trade.get('side', '?')
                pnl = trade.get('pnl_pct', 0)
                learning_context_text += f"- [{ts}] {sym} {side}: PnL={pnl:.2f}%\n"
            
            learning_context_text += """
### How to use this context:
- **If win_rate is low (<50%)**: Be MORE SELECTIVE. Require stronger confirmations (4-5 instead of 3).
- **If losing streak > 2**: Consider REDUCING position sizes and leverage to limit further damage.
- **If high_drawdown_period = YES**: Be CONSERVATIVE. Avoid aggressive trades.
- **If negative_pnl_period = YES**: Focus on HIGH CONFIDENCE setups only (confidence >80%).
- **Per-symbol stats**: If a symbol has poor historical performance, be extra cautious or skip it.
- **YOU DECIDE leverage and size**: Use this context as guidance, not hard rules. Explain your reasoning if you deviate.
"""
        
        enhanced_system_prompt = (
            SYSTEM_PROMPT
            + constraints_text
            + margin_text
            + cooldown_text
            + performance_text
            + learning_text
            + learning_policy_text
            + learning_context_text
        )
        
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

                # CAP ENTRY CONFIDENCE by setup_confirmations (soft sanity-check)
                sc = valid_dec.setup_confirmations or valid_dec.confirmations or []
                sc_n = len(sc) if isinstance(sc, list) else 0
                if valid_dec.confidence is not None:
                    try:
                        conf = int(valid_dec.confidence)
                    except Exception:
                        conf = 50
                    if sc_n <= 0:
                        conf = min(conf, 55)
                    elif sc_n == 1:
                        conf = min(conf, 65)
                    elif sc_n == 2:
                        conf = min(conf, 75)
                    valid_dec.confidence = max(0, min(100, conf))

                # HARD CONSTRAINT: blocca OPEN_LONG/OPEN_SHORT se margine insufficiente
                if not can_open_new_positions and valid_dec.action in ["OPEN_LONG", "OPEN_SHORT"]:
                    logger.warning(
                        f"🚫 Blocked {valid_dec.action} on {valid_dec.symbol}: "
                        f"insufficient margin (available={wallet_available_for_new_trades:.2f}, threshold={margin_threshold})"
                    )
                    # Converti in HOLD con rationale chiaro
                    valid_dec.action = "HOLD"
                    valid_dec.leverage = 0
                    valid_dec.size_pct = 0
                    valid_dec.rationale = (
                        f"Blocked: insufficient free margin "
                        f"(available_for_new_trades={wallet_available_for_new_trades:.2f}, "
                        f"threshold={margin_threshold}). "
                        f"Original: {valid_dec.rationale}"
                    )
                
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


@app.post("/manage_critical_positions")
async def manage_critical_positions(request: ManageCriticalPositionsRequest):
    """
    Gestione robusta di posizioni critiche in perdita.
    
    Usa fast path (portfolio snapshot + technical multi-timeframe), 
    hard timeout su LLM, fallback deterministico.
    Constraints: simboli disabilitati → mai REVERSE; preferisce CLOSE su REVERSE a meno che confirmations>=4.
    
    Returns:
        {
          "actions": [{"symbol": "BTCUSDT", "action": "CLOSE|REVERSE|HOLD", "score_breakdown": {...}, "loss_pct_with_leverage": -12.5}],
          "meta": {"timeout_occurred": false, "processing_time_ms": 450}
        }
    """
    start_time = datetime.now()
    timeout_occurred = False
    actions_result = []
    
    try:
        logger.info(f"🔥 Managing {len(request.positions)} critical positions")
        learning_params = getattr(request, "learning_params", None) or {}
        learning_params_params = (learning_params.get("params") if isinstance(learning_params, dict) else {}) or {}
        learning_params_meta = {
            "status": learning_params.get("status") if isinstance(learning_params, dict) else None,
            "version": learning_params.get("version") if isinstance(learning_params, dict) else None,
            "evolved_at": learning_params.get("evolved_at") if isinstance(learning_params, dict) else None,
        }

        # Fast path: ottieni dati tecnici per tutti i simboli in parallelo
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            tech_tasks = []
            for pos in request.positions:
                task = http_client.post(
                    f"{AGENT_URLS['technical']}/analyze_multi_tf_full",
                    json={"symbol": pos.symbol}
                )
                tech_tasks.append(task)
            
            # Raccogli risultati tecnici
            tech_results = await asyncio.gather(*tech_tasks, return_exceptions=True)
            tech_data_map = {}
            for i, pos in enumerate(request.positions):
                if isinstance(tech_results[i], Exception):
                    logger.warning(f"⚠️ Tech data failed for {pos.symbol}: {tech_results[i]}")
                    tech_data_map[pos.symbol] = {}
                else:
                    try:
                        tech_data_map[pos.symbol] = tech_results[i].json()
                    except:
                        tech_data_map[pos.symbol] = {}
        
        # Processa ogni posizione
        for pos in request.positions:
            # Calcola loss_pct_with_leverage in modo consistente
            entry = pos.entry_price
            mark = pos.mark_price
            leverage = pos.leverage
            side = pos.side.lower()
            
            if entry > 0 and mark > 0:
                if side in ['long', 'buy']:
                    loss_pct_with_leverage = ((mark - entry) / entry) * leverage * 100
                else:  # short
                    loss_pct_with_leverage = -((mark - entry) / entry) * leverage * 100
            else:
                loss_pct_with_leverage = 0.0
            
            logger.info(f"  📊 {pos.symbol} {side}: loss_pct_with_leverage={loss_pct_with_leverage:.2f}%")
            
            # Prepara prompt per LLM
            tech_data = tech_data_map.get(pos.symbol, {})
            
            # Conta conferme tecniche per REVERSE
            confirmations_count = 0
            confirmations_list = []
            
            # Analizza dati tecnici per conferme
            if tech_data:
                # RSI oversold/overbought nella direzione opposta
                rsi_1h = tech_data.get('timeframes', {}).get('1h', {}).get('rsi')
                if rsi_1h:
                    if side == 'long' and rsi_1h < 30:  # oversold for long = potential reverse to short
                        confirmations_count += 1
                        confirmations_list.append(f"RSI 1h oversold ({rsi_1h:.1f})")
                    elif side == 'short' and rsi_1h > 70:  # overbought for short = potential reverse to long
                        confirmations_count += 1
                        confirmations_list.append(f"RSI 1h overbought ({rsi_1h:.1f})")
                
                # Trend opposto confermato
                trend_1h = tech_data.get('timeframes', {}).get('1h', {}).get('trend')
                if trend_1h:
                    if (side == 'long' and trend_1h == 'bearish') or (side == 'short' and trend_1h == 'bullish'):
                        confirmations_count += 1
                        confirmations_list.append(f"Trend 1h opposto ({trend_1h})")
                
                # MACD inversione
                macd_signal = tech_data.get('timeframes', {}).get('1h', {}).get('macd_signal')
                if macd_signal:
                    if (side == 'long' and macd_signal == 'bearish') or (side == 'short' and macd_signal == 'bullish'):
                        confirmations_count += 1
                        confirmations_list.append(f"MACD segnale opposto ({macd_signal})")
                
                # Volume trend
                volume_trend = tech_data.get('timeframes', {}).get('1h', {}).get('volume_trend')
                if volume_trend == 'increasing':
                    confirmations_count += 1
                    confirmations_list.append("Volume in aumento")
            
            logger.info(f"  ✅ Confirmations: {confirmations_count} - {confirmations_list}")
            
            # Sistema di punteggio
            score_breakdown = {
                "technical_score": confirmations_count * 25,  # Max 100 se 4 conferme
                "loss_severity": min(100, abs(loss_pct_with_leverage) * 5),  # Quanto è grave la perdita
                "trend_alignment": 50 if confirmations_count >= 2 else 0,
                "volume_confirmation": 25 if "Volume in aumento" in confirmations_list else 0
            }
            
            # Costruisci prompt per LLM con timeout
            system_prompt = """Sei un trader esperto che analizza posizioni critiche in perdita.

DECISIONI POSSIBILI:
1. HOLD = Correzione temporanea, trend principale valido
2. CLOSE = Incertezza, meglio chiudere
3. REVERSE = Inversione di trend CONFERMATA da multipli indicatori

CRITERI REVERSE (servono ALMENO 4 conferme):
- RSI oversold/overbought direzione opposta
- Trend opposto confermato
- MACD segnale inversione
- Volume in aumento

Rispondi SOLO in formato JSON:
{"action": "HOLD|CLOSE|REVERSE", "confidence": 0-100, "rationale": "breve spiegazione"}"""
            user_prompt = f"""POSIZIONE CRITICA:
Symbol: {pos.symbol}
Side: {side}
Loss: {loss_pct_with_leverage:.2f}%
Confirmations: {confirmations_count} - {confirmations_list}

LEARNING_POLICY (evolved params, guidance not hard rules):
{json.dumps(learning_params_params, indent=2)[:800]}

Regole di disciplina:
- Puoi fare override rispetto alla policy, ma devi spiegarlo nel rationale.
- Se le conferme sono poche (0-1), preferisci CLOSE o HOLD prudente: confidence moderata.
- REVERSE solo se conferme >=4 (verificato a valle).

Technical data summary:
{json.dumps(tech_data.get('timeframes', {}).get('1h', {}), indent=2)[:500]}

DECIDI: HOLD, CLOSE o REVERSE"""
            
            # LLM call con timeout e fallback
            decision_action = "CLOSE"  # Default fallback
            decision_confidence = 50
            decision_rationale = "Timeout o errore LLM, fallback a CLOSE per sicurezza"
            
            try:
                # Hard timeout 20s
                async def call_llm():
                    return await asyncio.to_thread(
                        lambda: client.chat.completions.create(
                            model="deepseek-chat",
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.3
                        )
                    )
                
                response = await asyncio.wait_for(call_llm(), timeout=20.0)
                
                # Log API costs
                if hasattr(response, 'usage') and response.usage:
                    log_api_call(
                        tokens_in=response.usage.prompt_tokens,
                        tokens_out=response.usage.completion_tokens
                    )
                
                content = response.choices[0].message.content
                decision_data = json.loads(content)
                
                decision_action = decision_data.get("action", "CLOSE").upper()
                decision_confidence = decision_data.get("confidence", 50)
                decision_rationale = decision_data.get("rationale", "No rationale")

                # CAP CONFIDENCE by confirmations_count (soft sanity-check)
                try:
                    decision_confidence = float(decision_confidence)
                except Exception:
                    decision_confidence = 50
                if confirmations_count <= 0:
                    decision_confidence = min(decision_confidence, 55)
                elif confirmations_count == 1:
                    decision_confidence = min(decision_confidence, 65)
                elif confirmations_count == 2:
                    decision_confidence = min(decision_confidence, 75)
                decision_confidence = int(max(0, min(100, decision_confidence)))

            except asyncio.TimeoutError:
                logger.warning(f"⏱️ LLM timeout for {pos.symbol}, using fallback")
                timeout_occurred = True
            except Exception as e:
                logger.warning(f"⚠️ LLM error for {pos.symbol}: {e}, using fallback")
            
            # Applica constraints
            # 1. Se simbolo disabilitato, mai REVERSE
            if pos.is_disabled and decision_action == "REVERSE":
                logger.warning(f"⚠️ Symbol {pos.symbol} disabled, forcing CLOSE instead of REVERSE")
                decision_action = "CLOSE"
                decision_rationale = "Simbolo disabilitato, REVERSE non permesso. " + decision_rationale
            
            # 2. Preferisce CLOSE su REVERSE a meno che confirmations>=4
            if decision_action == "REVERSE" and confirmations_count < 4:
                logger.warning(f"⚠️ {pos.symbol} confirmations={confirmations_count}<4, downgrade REVERSE to CLOSE")
                decision_action = "CLOSE"
                decision_rationale = f"Solo {confirmations_count} conferme (<4), troppo rischioso per REVERSE. " + decision_rationale
            
            # Salva evento di chiusura se azione è CLOSE o REVERSE
            if decision_action in ["CLOSE", "REVERSE"]:
                save_close_event(
                    symbol=pos.symbol,
                    side=side,
                    reason=f"{decision_action}: {decision_rationale[:100]}"
                )
            
            actions_result.append({
                "symbol": pos.symbol,
                "action": decision_action,
                "confidence": decision_confidence,
                "rationale": decision_rationale,
                "score_breakdown": score_breakdown,
                "loss_pct_with_leverage": round(loss_pct_with_leverage, 2),
                "confirmations_count": confirmations_count,
                "confirmations": confirmations_list
            })
            
            logger.info(f"  ✅ {pos.symbol}: {decision_action} (confidence={decision_confidence}%)")
        
        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        result = {
            "actions": actions_result,
            "meta": {
                "timeout_occurred": timeout_occurred,
                "processing_time_ms": elapsed_ms,
                "total_positions": len(request.positions),
                "learning_params": learning_params_meta,
            }
        }
        
        logger.info(f"✅ Critical positions management complete: {elapsed_ms}ms, {len(actions_result)} actions")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Critical positions management error: {e}")
        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # Fallback per tutte le posizioni
        fallback_actions = []
        for pos in request.positions:
            entry = pos.entry_price
            mark = pos.mark_price
            leverage = pos.leverage
            side = pos.side.lower()
            
            if entry > 0 and mark > 0:
                if side in ['long', 'buy']:
                    loss_pct = ((mark - entry) / entry) * leverage * 100
                else:
                    loss_pct = -((mark - entry) / entry) * leverage * 100
            else:
                loss_pct = 0.0
            
            fallback_actions.append({
                "symbol": pos.symbol,
                "action": "CLOSE",  # Fallback sicuro
                "confidence": 0,
                "rationale": f"Errore durante analisi: {str(e)}. Fallback a CLOSE per sicurezza.",
                "score_breakdown": {
                    "technical_score": 0,
                    "loss_severity": min(100, abs(loss_pct) * 5),
                    "trend_alignment": 0,
                    "volume_confirmation": 0
                },
                "loss_pct_with_leverage": round(loss_pct, 2),
                "confirmations_count": 0,
                "confirmations": []
            })
        
        return {
            "actions": fallback_actions,
            "meta": {
                "timeout_occurred": True,
                "processing_time_ms": elapsed_ms,
                "total_positions": len(request.positions),
                "error": str(e)
            }
        }


@app.get("/health")
def health(): return {"status": "active"}
