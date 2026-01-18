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
MIN_CONFIRMATIONS_REQUIRED = 2  # Numero minimo di conferme per aprire una posizione
CONFIDENCE_THRESHOLD_LOW = 50  # Soglia confidenza bassa per blocco automatico

# Cooldown configuration
COOLDOWN_MINUTES = 5

# Crash Guard configuration - momentum filters to avoid knife catching
CRASH_GUARD_5M_LONG_BLOCK_PCT = float(os.getenv("CRASH_GUARD_5M_LONG_BLOCK_PCT", "0.6"))  # Block LONG if return_5m <= -0.6%
CRASH_GUARD_5M_SHORT_BLOCK_PCT = float(os.getenv("CRASH_GUARD_5M_SHORT_BLOCK_PCT", "1.5"))  # Block SHORT if return_5m >= +0.6%

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
    2. Separare HARD blockers (blocked_by) da SOFT flags (soft_blockers)
    3. Garantire che HARD blockers forzino HOLD, SOFT flags no
    4. Separare setup_confirmations da risk_factors
    5. Validare che rationale non contenga contraddizioni
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
    
    # 4. Backward compatibility: migrate legacy soft reasons from blocked_by to soft_blockers
    blocked_by = decision_dict.get('blocked_by', [])
    soft_blockers = decision_dict.get('soft_blockers', [])
    
    if blocked_by:
        # Define soft reasons that should be migrated
        soft_reasons = ['LOW_CONFIDENCE', 'CONFLICTING_SIGNALS']
        hard_reasons = []
        migrated_soft = []
        
        for reason in blocked_by:
            if reason in soft_reasons:
                migrated_soft.append(reason)
            else:
                hard_reasons.append(reason)
        
        # Update blocked_by to contain only hard reasons
        decision_dict['blocked_by'] = hard_reasons
        
        # Merge migrated soft reasons into soft_blockers
        if migrated_soft:
            existing_soft = list(soft_blockers) if isinstance(soft_blockers, list) else []
            combined_soft = list(set(existing_soft + migrated_soft))
            decision_dict['soft_blockers'] = combined_soft
            logger.info(f"✅ Migrated soft reasons from blocked_by to soft_blockers: {migrated_soft}")
    
    # 5. Inferisci soft_blockers se action=HOLD con bassa confidence e nessun hard blocker
    if action == 'HOLD' and not decision_dict.get('blocked_by') and not decision_dict.get('soft_blockers'):
        if confidence < CONFIDENCE_THRESHOLD_LOW:
            decision_dict['soft_blockers'] = ['LOW_CONFIDENCE']
            logger.info(f"✅ Inferito soft_blockers=['LOW_CONFIDENCE'] per HOLD con confidence={confidence}")
        elif not decision_dict.get('setup_confirmations') or len(decision_dict.get('setup_confirmations', [])) < MIN_CONFIRMATIONS_REQUIRED:
            decision_dict['soft_blockers'] = ['CONFLICTING_SIGNALS']
            logger.info(f"✅ Inferito soft_blockers=['CONFLICTING_SIGNALS'] per HOLD con poche conferme")
    
    # 6. Se ci sono HARD blockers (blocked_by), action DEVE essere HOLD (o CLOSE se posizione aperta)
    if decision_dict.get('blocked_by') and action not in ['HOLD', 'CLOSE']:
        logger.warning(f"⚠️ Incoerenza: HARD blocked_by presente ma action={action}, forzato a HOLD")
        decision_dict['action'] = 'HOLD'
        decision_dict['leverage'] = 1.0
        decision_dict['size_pct'] = 0.0
    
    # 7. Valida rationale per contraddizioni comuni
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
            'soft_blockers': decision_data.get('soft_blockers', []),
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
# HARD constraints that ALWAYS block OPEN actions
HARD_BLOCKER_REASONS = Literal[
    "INSUFFICIENT_MARGIN",
    "MAX_POSITIONS",
    "COOLDOWN",
    "DRAWDOWN_GUARD",
    "CRASH_GUARD",
    "LOW_PRE_SCORE",
    "LOW_RANGE_SCORE",
    "MOMENTUM_UP_15M",
    "MOMENTUM_DOWN_15M",
    "LOW_VOLATILITY",
    ""
]

# SOFT constraints that are warnings/flags but don't force HOLD
SOFT_BLOCKER_REASONS = Literal[
    "LOW_CONFIDENCE",
    "CONFLICTING_SIGNALS",
    ""
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
    blocked_by: Optional[List[HARD_BLOCKER_REASONS]] = None  # HARD constraints only
    soft_blockers: Optional[List[SOFT_BLOCKER_REASONS]] = None  # SOFT warnings/flags
    direction_considered: Optional[Literal["LONG", "SHORT", "NONE"]] = None
    # Scalping parameters
    tp_pct: Optional[float] = None  # Take profit percentage (e.g., 0.02 for 2%)
    sl_pct: Optional[float] = None  # Stop loss percentage (e.g., 0.015 for 1.5%)
    time_in_trade_limit_sec: Optional[int] = None  # Max holding time in seconds
    cooldown_sec: Optional[int] = None  # Cooldown period after close (per symbol+direction)
    trail_activation_roi: Optional[float] = None  # ROI threshold to activate trailing (optional)
    # LIMIT entry parameters
    entry_type: Optional[Literal["MARKET", "LIMIT"]] = "MARKET"  # Entry order type
    entry_price: Optional[float] = None  # Entry price for LIMIT orders (required when entry_type=LIMIT)
    entry_expires_sec: Optional[int] = 240  # TTL for LIMIT orders in seconds (default 240, range 10-3600)

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
Sei un TRADER PROFESSIONISTA SCALPER con 20 anni di esperienza sui mercati crypto.
Il tuo obiettivo è MASSIMIZZARE I PROFITTI con strategie di SCALPING AGGRESSIVE MA PROFITTEVOLI.

## FILOSOFIA AI-FIRST (CAMBIAMENTO FONDAMENTALE)
**TU SEI L'INTELLIGENZA PRINCIPALE** - I punteggi matematici (pre_score, range_score) sono SOLO un controllo di sanità mentale, 
NON un ostacolo che blocca le tue decisioni quando vedi opportunità valide.

**LIBERTÀ OPERATIVA**:
- Se vedi un setup chiaro con conferme multiple (≥3), puoi aprire anche se pre_score o range_score sono sotto la soglia minima
- Gli indicatori matematici rigidi servono SOLO per evitare trade completamente assurdi (es. pre_score < 30)
- NON devi essere "paralizzato" da un pre_score di 45-50 se il contesto contestuale è forte
- La tua analisi contestuale ha PRIORITÀ sui segnali deboli degli indicatori meccanici

**QUANDO GLI SCORE BASSI SONO OK**:
- Se hai ≥3 conferme solide da fonti diverse (momentum, volume, S/R, sentiment)
- Se vedi un pattern chiaro che giustifica l'operazione
- Se il rischio è gestibile e il reward è interessante
- Se il timing è giusto anche se gli indicatori a lungo termine sono neutrali

**QUANDO DEVI COMUNQUE RISPETTARE GLI SCORE**:
- Se pre_score < 30 AND range_score < 30 (setup troppo debole)
- Se NON hai almeno 3 conferme solide
- Se ci sono blocchi hard (INSUFFICIENT_MARGIN, MAX_POSITIONS, COOLDOWN, CRASH_GUARD)

## FILOSOFIA SCALPING
- **Alta frequenza**: Cerca opportunità frequenti (1m, 5m, 15m timeframe, conferma 1h opzionale)
- **Target piccoli**: 1-3% ROI con leva (leverage 3-10x basato su volatilità)
- **Stop stretti**: 1-2% stop loss per proteggere capitale
- **Uscita rapida**: Max 20-120 minuti in trade (configurabile via time_in_trade_limit_sec)
- **Gestione seria**: Guardrail di emergenza più larghi per permetterti di operare

## PROCESSO DECISIONALE STRUTTURATO

1. **ANALIZZA TUTTI I DATI** - Non basarti su un solo indicatore
2. **IDENTIFICA LA DIREZIONE** - Determina quale setup stai valutando (LONG, SHORT o NONE)
3. **RACCOGLI CONFERME** - Elenca tutte le conferme per il setup specifico
4. **VALUTA SCORE** - Controlla pre_score/range_score come sanity check, NON come blocco assoluto
5. **APPLICA VINCOLI HARD** - Verifica se ci sono blocchi ASSOLUTI (margin, positions, cooldown, crash guard)
6. **DECIDI AZIONE** - Se bloccato da vincoli HARD → HOLD, altrimenti usa il tuo giudizio
7. **PARAMETRI SCALPING** - Imposta tp_pct, sl_pct, time_in_trade_limit_sec, cooldown_sec

## CONFERME NECESSARIE PER APRIRE (almeno 3 su 5)
- ✅ Momentum a breve termine concorde (1m, 5m almeno allineati)
- ✅ Spread e volatilità OK (no chop/consolidamento estremo)
- ✅ RSI in zona appropriata per la direzione del trade (mean-reversion o trend-following)
- ✅ Prezzo vicino a livello chiave (Fibonacci o Gann) o breakout confermato
- ✅ Sentiment/news non contrario e volume adeguato

## VINCOLI CHE BLOCCANO L'APERTURA (GUARDRAIL ASSOLUTI - HARD CONSTRAINTS)
Questi vanno in `blocked_by` e DEVONO forzare action=HOLD:
- **INSUFFICIENT_MARGIN**: Margine disponibile insufficiente (< 10 USDT disponibili)
- **MAX_POSITIONS**: Massimo numero posizioni raggiunto
- **COOLDOWN**: Posizione chiusa di recente nella stessa direzione (evita revenge trading)
- **DRAWDOWN_GUARD**: Sistema in drawdown eccessivo (< -10%)
- **CRASH_GUARD**: Movimento violento contro la direzione (no knife catching)
  - Block LONG se return_5m <= -0.6% (crash in atto)
  - Block SHORT se return_5m >= +0.6% (pump violento in atto)
- **LOW_PRE_SCORE + LOW_RANGE_SCORE**: Entrambi gli score sotto soglia E < 3 conferme
- **MOMENTUM_UP_15M / MOMENTUM_DOWN_15M**: SOL airbag per evitare contrarian in trend forte
- **LOW_VOLATILITY**: Volatilità troppo bassa, mercato in chop

## VINCOLI SOFT (FLAGS/WARNINGS - NON BLOCCANO APERTURA)
Questi vanno in `soft_blockers` e NON forzano HOLD - puoi aprire comunque se giustificato:
- **LOW_CONFIDENCE**: Confidenza < 50% - ma se hai buone ragioni e ≥3 conferme, puoi aprire
- **CONFLICTING_SIGNALS**: Segnali contrastanti - valuta quale è più importante e giustifica
- Pattern perdenti storici: Non è un blocco, aumenta solo prudenza

## REGOLE DI COERENZA CRITICA
- **DIREZIONE**: Se action è OPEN_SHORT, direction_considered DEVE essere "SHORT" e setup_confirmations devono essere per SHORT
- **SEPARAZIONE**: NON mescolare risk factors con setup confirmations
- **SEPARAZIONE BLOCCHI**: HARD constraints vanno in `blocked_by`, SOFT in `soft_blockers`
- **BLOCCO HARD**: Se `blocked_by` contiene vincolo HARD, action DEVE essere HOLD
- **BLOCCHI SOFT**: Se `soft_blockers` contiene flags, puoi APRIRE se hai ≥3 conferme e rationale forte
- **RATIONALE**: Spiega sempre perché superi un vincolo soft se lo fai

Esempio CORRETTO per OPEN_SHORT con scalping e soft blocker:
- direction_considered: "SHORT"
- setup_confirmations: ["Momentum 5m ribassista", "RSI > 65 (zona ipercomprato)", "Resistenza rifiutata", "Volume conferma"]
- blocked_by: [] (vuoto - nessun HARD blocker)
- soft_blockers: ["LOW_CONFIDENCE"] (confidence 55% ma ho 4 conferme solide)
- rationale: "Setup SHORT scalping: momentum 5m bearish + RSI ipercomprato + resistenza + volume. 4 conferme solide giustificano apertura nonostante confidence 55%. Apertura SHORT con target 2%, SL 1.5%, max 60 min."
- tp_pct: 0.02
- sl_pct: 0.015
- time_in_trade_limit_sec: 3600
- cooldown_sec: 900

## PARAMETRI SCALPING (SEMPRE OBBLIGATORI PER OPEN)
**tp_pct**: Target profit come frazione (0.01 = 1%, 0.02 = 2%, 0.03 = 3%)
  - Alta confidenza (>85%): 0.025-0.03 (2.5-3%)
  - Media confidenza (70-85%): 0.015-0.025 (1.5-2.5%)
  - Bassa confidenza (50-70%): 0.01-0.015 (1-1.5%)

**sl_pct**: Stop loss come frazione (0.01 = 1%, 0.015 = 1.5%, 0.02 = 2%)
  - Volatilità bassa: 0.01-0.015 (1-1.5%)
  - Volatilità media: 0.015-0.02 (1.5-2%)
  - Volatilità alta: 0.02-0.025 (2-2.5%)

**time_in_trade_limit_sec**: Max holding time in secondi
  - Setup molto forte: 1800-3600 (30-60 min)
  - Setup buono: 3600-5400 (60-90 min)
  - Setup moderato: 5400-7200 (90-120 min)

**cooldown_sec**: Cooldown dopo chiusura (default 900 = 15 min)
  - Trade vincente: 300-600 (5-10 min)
  - Trade perdente: 900-1800 (15-30 min) per evitare revenge trading

**trail_activation_roi** (opzionale): ROI leveraged per attivare trailing (es. 0.01 = 1%)

## PARAMETRI LIMIT ENTRY (OPZIONALI - per entry più precisa)
**entry_type**: Tipo di ordine entry ("MARKET" o "LIMIT")
  - "MARKET" (default): Entry immediato al prezzo di mercato
  - "LIMIT": Entry a prezzo specifico, più preciso ma richiede che il prezzo venga raggiunto
  
**entry_price** (richiesto quando entry_type="LIMIT"): Prezzo esatto per LIMIT order
  - Per LONG: entry_price leggermente sotto il prezzo attuale (es. -0.1% a -0.5%) per migliore fill
  - Per SHORT: entry_price leggermente sopra il prezzo attuale (es. +0.1% a +0.5%)
  - Se entry_price manca o è invalido con entry_type="LIMIT", il sistema fa fallback a MARKET con warning
  
**entry_expires_sec** (opzionale, default 240): TTL per LIMIT order in secondi (range 10-3600)
  - Setup molto forte: 60-120 sec (1-2 min) - se non riempie velocemente, probabilmente non è più valido
  - Setup normale: 180-300 sec (3-5 min)
  - Setup paziente: 300-600 sec (5-10 min)
  - Max consigliato: 600 sec (10 min) per scalping 15m

SEMANTICA LIMIT ENTRY:
- Il sistema piazza un ordine LIMIT GTC a entry_price con orderLinkId tracking
- Se l'ordine non si riempie entro entry_expires_sec, viene cancellato automaticamente
- Se nel frattempo arriva una nuova decisione AI con entry_price diverso, il sistema cancella l'ordine vecchio e ne piazza uno nuovo (cancel+replace)
- Una volta riempito, il sistema piazza automaticamente lo stop-loss e inizia il monitoring come per MARKET entry

QUANDO USARE LIMIT ENTRY:
✅ Usa LIMIT quando:
  - Prezzo è vicino a supporto/resistenza e vuoi entry preciso
  - Setup molto pulito ma prezzo non è ancora ideale
  - Vuoi ottimizzare entry per ridurre slippage
  - Hai alta confidenza che il prezzo raggiungerà il livello target
  
❌ Usa MARKET quando:
  - Setup time-sensitive che richiede entry immediato
  - Alta volatilità dove LIMIT potrebbe non riempire
  - Confidenza bassa e vuoi entry rapido per gestire meglio il rischio
  - Breakout/momentum trade che non aspetta

## GESTIONE RISCHIO DINAMICA

## REGOLE RSI (ANTI-CONTRADDIZIONE)

## BOOST CONFIDENCE + PLAYBOOK SELECTION (REGOLA OBBLIGATORIA)
- Prima scegli il **Playbook**:
  - "Playbook: TREND" se il contesto indica trend-following (pre_score alto, momentum e struttura EMA coerenti).
  - "Playbook: RANGE" se il contesto indica mean-reversion (range_score alto + prezzo vicino support/resistenza).
  - Se non sei sicuro ma hai ≥3 conferme → APRI con prudenza (leverage moderato)

- Losing patterns storici: non sono un blocco assoluto, ma se un pattern si ripete aumenta prudenza (riduci size/leverage, alza cooldown) e spiega nel rationale.
  - RANGE: RSI 15m > 80 -> setup SHORT molto forte (ma solo se vicino resistenza e momentum NON è in accelerazione).
  - RANGE: RSI 15m < 25 -> setup LONG molto forte (ma solo se vicino supporto e momentum NON è in accelerazione).

- Il momentum contrario NON è "sempre normale":
  - In RANGE può esistere mean-reversion contro momentum SOLO se hai range_score >= MIN_RANGE_SCORE e almeno 1 conferma di livello (support/resistance) e segnali di rallentamento (es. return_5m non in accelerazione).
  - In TREND evitare contrarian: se price è in EMA upstack e return_15m è positivo, SHORT è di norma un errore; viceversa per LONG in downstack.

- Se RSI è estremo (>80 o <25) puoi aprire anche con 2 conferme SOLO in RANGE e SOLO se non violi crash_guard.
- **Alta confidenza (90%+)**: leverage 7-10x, size 0.15-0.20
- **Media confidenza (70-89%)**: leverage 5-7x, size 0.12-0.15
- **Bassa confidenza (50-69%)**: leverage 3-5x, size 0.08-0.12
- **Confidenza bassa ma conferme solide**: leverage 3-4x, size 0.08-0.10, spiega nel rationale

Considera anche:
- **Volatilità del mercato**: Alta volatilità → leverage più basso, SL più ampio
- **Numero di conferme**: Più conferme → maggiore fiducia, target più ambizioso
- **Performance recente del sistema**: Se in drawdown → più conservativo
- **Spread e slippage**: Se spread > 0.1% → riduci size o evita

## QUANDO NON APRIRE (HOLD)
- Vincoli HARD attivi (margin, max positions, cooldown, crash guard)
- Nessuna conferma solida (< 2 conferme)
- Mercato completamente incerto/violento
- Pre_score < 30 AND range_score < 30 AND meno di 3 conferme
- **MARGINE INSUFFICIENTE**: available_for_new_trades < 10.0 USDT (BLOCCANTE HARD)
- **CRASH GUARD**: Movimento violento contro direzione (BLOCCANTE HARD)

## OUTPUT JSON OBBLIGATORIO
{
  "analysis_summary": "Sintesi ragionata della situazione market-wide",
  "decisions": [
    {
      "symbol": "ETHUSDT",
      "action": "OPEN_LONG|OPEN_SHORT|HOLD",
      "leverage": 5.0,
      "size_pct": 0.15,
      "confidence": 75,
      "rationale": "Spiegazione dettagliata seguendo processo strutturato. Se superi vincolo soft, spiega perché.",
      "confirmations": ["lista conferme generali (backward compat)"],
      "risk_factors": ["lista rischi identificati (backward compat)"],
      "setup_confirmations": ["conferme specifiche per la direzione considerata"],
      "blocked_by": ["HARD constraints: INSUFFICIENT_MARGIN, MAX_POSITIONS, COOLDOWN, DRAWDOWN_GUARD, CRASH_GUARD, LOW_PRE_SCORE, LOW_RANGE_SCORE, MOMENTUM_UP_15M, MOMENTUM_DOWN_15M, LOW_VOLATILITY"],
      "soft_blockers": ["SOFT warnings: LOW_CONFIDENCE, CONFLICTING_SIGNALS - NON bloccano apertura"],
      "direction_considered": "LONG|SHORT|NONE",
      "tp_pct": 0.02,
      "sl_pct": 0.015,
      "time_in_trade_limit_sec": 3600,
      "cooldown_sec": 900,
      "trail_activation_roi": 0.01,
      "entry_type": "MARKET",
      "entry_price": null,
      "entry_expires_sec": 240
    }
  ]
}

ESEMPIO con LIMIT entry (opzionale):
{
  "symbol": "BTCUSDT",
  "action": "OPEN_LONG",
  "leverage": 5.0,
  "size_pct": 0.12,
  "confidence": 80,
  "rationale": "Setup LONG con prezzo vicino a supporto chiave $95000. Uso LIMIT entry a $95100 per entry preciso al supporto con minor slippage. Se prezzo rimbalza prima (60 sec), entry comunque valido.",
  "entry_type": "LIMIT",
  "entry_price": 95100.0,
  "entry_expires_sec": 60,
  "tp_pct": 0.02,
  "sl_pct": 0.015,
  "time_in_trade_limit_sec": 3600
}

RICORDA: 
- **AI-FIRST**: Gli score sono un controllo di sanità, NON una prigione
- Se hai ≥3 conferme solide, puoi aprire anche con score bassi (45-60)
- Spiega sempre nel rationale se superi un vincolo soft
- I vincoli HARD (margin, positions, cooldown, crash guard) vanno SEMPRE rispettati
- Meglio un trade cauto che nessun trade se vedi opportunità reale
- **SEMPRE** fornisci tp_pct, sl_pct, time_in_trade_limit_sec quando apri posizione

## PRE_SCORE (base_confidence) — CONTROLLO DI SANITÀ (NON BLOCCO ASSOLUTO)
Nel contesto troverai, per ogni simbolo:
market_data[SYMBOL].pre_score.LONG.base_confidence
market_data[SYMBOL].pre_score.SHORT.base_confidence

Questi valori rappresentano una stima quantitativa "prior" della qualità del setup (0–100).
- Se pre_score >= 45 E hai ≥3 conferme solide → puoi aprire
- Se pre_score < 30 E range_score < 30 → serve rationale molto forte per aprire
- Gli score sono un SUGGERIMENTO, non un muro invalicabile
- La tua analisi contestuale ha PRIORITÀ se giustificata


## RANGE_SCORE — PLAYBOOK MEAN-REVERSION (RANGE)
Nel contesto troverai anche:
market_data[SYMBOL].range_score.LONG.base_confidence
market_data[SYMBOL].range_score.SHORT.base_confidence

Usa RANGE_SCORE solo per strategie mean-reversion in regime RANGE.
- Puoi aprire un trade con playbook RANGE se range_score >= 50 O se hai ≥3 conferme di mean-reversion
- Nel rationale devi indicare esplicitamente: "Playbook: RANGE" oppure "Playbook: TREND".


## PLAYBOOK RANGE — PARAMETRI DI RISCHIO (LEVA + DYNAMIC SL)
Quando scegli "Playbook: RANGE" (mean-reversion su 15m), i parametri TP/SL devono essere ragionati in termini di ROI sul margine (leva inclusa), non solo in % prezzo.

Profili consigliati (scalping 15m):
A) Majors (BTC/ETH)
- ROI target tipico: +3% .. +6% (sul margine)
- ROI rischio iniziale/worst-case: -2% .. -4% (sul margine)
- time_in_trade_limit_sec: 1800 .. 5400 (30–90 min)
- trail_activation_roi: +1% .. +2% (attiva presto)

B) Volatili (es. SOL / alts liquide)
- ROI target tipico: +4% .. +8% (sul margine)
- ROI rischio iniziale/worst-case: -3% .. -5% (sul margine)
- time_in_trade_limit_sec: 1800 .. 5400 (30–90 min)
- trail_activation_roi: +1.5% .. +2.5%

Conversione coerente con la leva:
- tp_pct (su prezzo) ≈ ROI_target / leverage
- sl_pct (su prezzo) ≈ ROI_risk / leverage

Importante:
- Non sovrascrivere o "bloccare" il sistema di stop loss dinamico già implementato: sl_pct è un riferimento iniziale/fallback, mentre la gestione dinamica/trailing può stringere o gestire l'uscita secondo le regole del sistema.


Linee guida (scalping 15m, majors):
- ROI target tipico: +3% .. +6% (sul margine)
- ROI rischio iniziale/worst-case: -2% .. -4% (sul margine)
- time_in_trade_limit_sec: 1800 .. 5400 (30–90 min)
- trail_activation_roi: +1% .. +2% (attiva presto)

Conversione coerente con la leva:
- tp_pct (su prezzo) ≈ ROI_target / leverage
- sl_pct (su prezzo) ≈ ROI_risk / leverage

Importante:
- Non sovrascrivere o "bloccare" il sistema di stop loss dinamico già implementato: sl_pct è un riferimento iniziale/fallback, mentre la gestione dinamica/trailing può stringere o gestire l'uscita secondo le regole del sistema.



"""


MIN_PRE_SCORE = int(os.getenv("MIN_PRE_SCORE", "45"))  # Minimum base confidence required to allow OPEN_LONG/OPEN_SHORT - lowered for AI autonomy
MIN_RANGE_SCORE = int(os.getenv("MIN_RANGE_SCORE", "50"))  # Minimum range score required to allow OPEN_LONG/OPEN_SHORT in RANGE playbook - lowered for AI autonomy

def _safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            return float(x.strip())
        return default
    except Exception:
        return default


def _extract_numeric_levels_from_dict(d):
    levels = []
    if isinstance(d, dict):
        for v in d.values():
            try:
                fv = float(v)
                if fv > 0:
                    levels.append(fv)
            except Exception:
                pass
    return levels


def _nearest_sr(price, levels):
    if not price or price <= 0 or not levels:
        return None, None
    below = [x for x in levels if x <= price]
    above = [x for x in levels if x >= price]
    support = max(below) if below else None
    resistance = min(above) if above else None
    return support, resistance


def _sr_bonus(direction, price, fib, gann):
    levels = []
    fib_levels = (fib or {}).get("fib_levels") or {}
    gann_levels = (gann or {}).get("next_important_levels") or {}
    levels += _extract_numeric_levels_from_dict(fib_levels)
    levels += _extract_numeric_levels_from_dict(gann_levels)

    support, resistance = _nearest_sr(price, levels)

    def dist_pct(level):
        if level is None or price <= 0:
            return None
        return abs(price - level) / price

    support_dist = dist_pct(support)
    resist_dist = dist_pct(resistance)

    chosen = support_dist if direction == "LONG" else resist_dist

    bonus = 0
    if chosen is not None:
        if chosen <= 0.0010:
            bonus = 12
        elif chosen <= 0.0025:
            bonus = 8
        elif chosen <= 0.0050:
            bonus = 4

    return bonus, {
        "levels_count": len(levels),
        "support": support,
        "resistance": resistance,
        "support_dist_pct": support_dist,
        "resistance_dist_pct": resist_dist,
        "chosen_dist_pct": chosen,
        "bonus": bonus,
    }


def _compute_base_score(direction, tf_15m, fase2_metrics, fib, gann):
    """
    Tuning v2 (15m scalping, "pro" / low-bias):
    - Trend/structure matters but doesn't dominate
    - Needs strength (ADX) or a trigger (momentum/volume)
    - Rewards location (S/R proximity) heavily
    - Penalizes chop only when ADX is weak (to avoid bias against healthy ranges/compressions)
    - Keeps RSI sanity small (avoid "overbought/oversold anchoring")
    """
    breakdown = {}
    score = 0

    price = _safe_float((tf_15m or {}).get("price"), 0.0)

    trend = str((tf_15m or {}).get("trend") or "").lower()
    rsi = _safe_float((tf_15m or {}).get("rsi"), 0.0)
    ret15 = _safe_float((tf_15m or {}).get("return_15m"), 0.0)
    adx = _safe_float((tf_15m or {}).get("adx"), 0.0)
    macd_mom_raw = (tf_15m or {}).get("macd_momentum")
    macd_state_raw = (tf_15m or {}).get("macd")
    macd_mom = _safe_float(macd_mom_raw, 0.0)  # compat if numeric in future
    vol_spike = bool((tf_15m or {}).get("volume_spike_15m"))
    ema20 = _safe_float((tf_15m or {}).get("ema_20"), 0.0)
    ema50 = _safe_float((tf_15m or {}).get("ema_50"), 0.0)
    ema200 = _safe_float((tf_15m or {}).get("ema_200"), 0.0)

    regime = str((fase2_metrics or {}).get("regime") or "").upper()
    range_15m_pct = _safe_float((tf_15m or {}).get("range_15m_pct"), 0.0)

    # A) Trend & structure (max 30)
    trend_alignment = 0
    ema_stacking = 0

    if direction == "LONG":
        trend_ok = (trend == "bullish") or (ema20 and ema200 and ema20 > ema200)
        if trend_ok:
            trend_alignment = 18
        if ema20 and ema50 and ema200 and (ema20 > ema50 > ema200):
            ema_stacking = 12
    else:
        trend_ok = (trend == "bearish") or (ema20 and ema200 and ema20 < ema200)
        if trend_ok:
            trend_alignment = 18
        if ema20 and ema50 and ema200 and (ema20 < ema50 < ema200):
            ema_stacking = 12

    score += trend_alignment + ema_stacking
    breakdown["trend_alignment"] = trend_alignment
    breakdown["ema_stacking"] = ema_stacking

    # B) Strength (ADX) (max 20)
    adx_points = 0
    if adx >= 25:
        adx_points = 20
    elif adx >= 18:
        adx_points = 12
    elif adx >= 14:
        adx_points = 6

    score += adx_points
    breakdown["adx"] = adx_points
    breakdown["adx_value"] = adx

    # C) Trigger (momentum + volume) (max 25)
    mom_points = 0
    if direction == "LONG":
        if ret15 > 0:
            mom_points += 8
        if macd_mom > 0:
            mom_points += 10
    else:
        if ret15 < 0:
            mom_points += 8
        if macd_mom < 0:
            mom_points += 10

    vol_points = 7 if vol_spike else 0

    score += mom_points + vol_points
    breakdown["momentum"] = mom_points
    breakdown["volume_spike_15m"] = vol_points
    breakdown["return_15m"] = ret15
    breakdown["macd_momentum"] = macd_mom
    # MACD string signals (tech agent returns strings like NEGATIVE/POSITIVE and RISING/FALLING)
    macd_sig_points = 0
    mom_s = str(macd_mom_raw or "").upper()
    state_s = str(macd_state_raw or "").upper()
    if direction == "LONG":
        if mom_s == "RISING":
            macd_sig_points += 6
        if state_s == "POSITIVE":
            macd_sig_points += 4
    else:
        if mom_s == "FALLING":
            macd_sig_points += 6
        if state_s == "NEGATIVE":
            macd_sig_points += 4
    score += macd_sig_points
    breakdown["macd_signal_points"] = macd_sig_points
    breakdown["macd_state_raw"] = macd_state_raw
    breakdown["macd_momentum_raw"] = macd_mom_raw

    # D) Location (S/R proximity) (max 20)
    _sr_points_raw, sr_details = _sr_bonus(direction, price, fib, gann)
    chosen_dist = sr_details.get("chosen_dist_pct", None)

    sr_points = 0
    if isinstance(chosen_dist, (int, float)):
        if chosen_dist <= 0.0010:
            sr_points = 20
        elif chosen_dist <= 0.0025:
            sr_points = 14
        elif chosen_dist <= 0.0050:
            sr_points = 8
        elif chosen_dist <= 0.0100:
            sr_points = 4

    score += sr_points
    breakdown["sr_bonus"] = sr_points
    breakdown["sr_details"] = sr_details

    # E) Chop filter (penalty up to -20, only when ADX weak)
    chop_pen = 0
    if adx < 14:
        chop_pen -= 10
        if 0 < range_15m_pct < 0.10:
            chop_pen -= 10

    if regime == "RANGE" and adx < 18:
        chop_pen -= 4

    score += chop_pen
    breakdown["chop_penalty"] = chop_pen
    breakdown["regime"] = regime
    breakdown["range_15m_pct"] = range_15m_pct

    # F) RSI sanity (small, max ±12)
    rsi_adj = 0
    if direction == "LONG":
        if rsi >= 72:
            rsi_adj -= 12
        elif rsi >= 65:
            rsi_adj -= 6
        elif 45 <= rsi <= 60:
            rsi_adj += 4
    else:
        if rsi <= 28:
            rsi_adj -= 12
        elif rsi <= 35:
            rsi_adj -= 6
        elif 40 <= rsi <= 55:
            rsi_adj += 4

    score += rsi_adj
    breakdown["rsi_adjust"] = rsi_adj
    breakdown["rsi"] = rsi

    score = max(0, min(100, int(round(score))))
    breakdown["final_score"] = score
    return score, breakdown



def _compute_range_score(direction, tf_15m, fase2_metrics, fib, gann):
    """
    RANGE playbook score (15m mean reversion).
    Purpose: allow trades in RANGE regime without lowering trend threshold.
    """
    breakdown = {}
    score = 0

    price = _safe_float((tf_15m or {}).get("price"), 0.0)
    rsi = _safe_float((tf_15m or {}).get("rsi"), 0.0)
    ret15 = _safe_float((tf_15m or {}).get("return_15m"), 0.0)
    adx = _safe_float((tf_15m or {}).get("adx"), 0.0)

    regime = str((fase2_metrics or {}).get("regime") or "").upper()
    breakdown["regime"] = regime
    breakdown["adx_value"] = adx
    breakdown["rsi"] = rsi
    breakdown["return_15m"] = ret15

    # 1) Must be RANGE
    if regime != "RANGE":
        breakdown["regime_gate"] = 0
        return 0, breakdown
    breakdown["regime_gate"] = 20
    score += 20

    # 2) Tradable range ADX band (12..22 best)
    adx_points = 0
    if 12 <= adx <= 22:
        adx_points = 20
    elif 10 <= adx < 12 or 22 < adx <= 25:
        adx_points = 10
    else:
        adx_points = 0
    score += adx_points
    breakdown["adx_band"] = adx_points

    # 3) Location at S/R (very important)
    _sr_points_raw, sr_details = _sr_bonus(direction, price, fib, gann)
    chosen_dist = sr_details.get("chosen_dist_pct", None)

    loc_points = 0
    if isinstance(chosen_dist, (int, float)):
        if chosen_dist <= 0.0010:
            loc_points = 35
        elif chosen_dist <= 0.0025:
            loc_points = 25
        elif chosen_dist <= 0.0050:
            loc_points = 12
        else:
            loc_points = 0
    score += loc_points
    breakdown["location_points"] = loc_points
    breakdown["sr_details"] = sr_details

    # 4) RSI mean-reversion filter (moderate weight)
    rsi_points = 0
    if direction == "LONG":
        if 40 <= rsi <= 55:
            rsi_points = 15
        elif 55 < rsi <= 62:
            rsi_points = 8
        elif rsi >= 70:
            rsi_points = -10
    else:
        if 45 <= rsi <= 60:
            rsi_points = 15
        elif 38 <= rsi < 45:
            rsi_points = 8
        elif rsi <= 30:
            rsi_points = -10
    score += rsi_points
    breakdown["rsi_points"] = rsi_points

    # 5) Anti-chase: avoid entering after an extended move
    chase_pen = 0
    if direction == "LONG" and ret15 > 0.20:
        chase_pen = -10
    if direction == "SHORT" and ret15 < -0.20:
        chase_pen = -10
    score += chase_pen
    breakdown["chase_penalty"] = chase_pen

    score = max(0, min(100, int(round(score))))
    breakdown["final_score"] = score
    return score, breakdown


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
                if os.getenv("DEBUG_TF_KEYS", "0") == "1":
                    try:
                        logger.info(f"[DEBUG] {symbol} additional_data keys: {sorted(list(additional_data.keys()))}")
                        fib = additional_data.get("fibonacci") or {}
                        gann = additional_data.get("gann") or {}
                        logger.info(f"[DEBUG] {symbol} fibonacci keys: {sorted(list(fib.keys()))}")
                        logger.info(f"[DEBUG] {symbol} fib_levels sample: {str(fib.get('fib_levels'))[:400]}")
                        logger.info(f"[DEBUG] {symbol} gann next_important_levels sample: {str(gann.get('next_important_levels'))[:400]}")

                        logger.info(f"[DEBUG] {symbol} gann keys: {sorted(list(gann.keys()))}")
                    except Exception as e:
                        logger.info(f"[DEBUG] {symbol} additional_data debug failed: {e}")

                
                # FASE 2: Compute volatility and regime metrics
                tech_data = asset_data.get('tech', {})
                timeframes = tech_data.get('timeframes', {})
                tf_15m = timeframes.get('15m', {})

                if os.getenv("DEBUG_TF_KEYS", "0") == "1":
                    logger.info(f"[DEBUG] {symbol} tf_15m keys: {sorted(tf_15m.keys())}")
                    logger.info(f"[DEBUG] {symbol} macd={tf_15m.get('macd')} macd_momentum={tf_15m.get('macd_momentum')}")


                
                # Volatility filter (anti-chop): volatility = ATR / price
                atr = tf_15m.get('atr') or 0
                price = tf_15m.get('price') or 0
                volatility_pct = (atr / price) if price > 0 else 0
                
                # Market regime detection: trend_strength = abs((EMA20 - EMA200) / EMA200)
                ema_20 = tf_15m.get('ema_20') or 0
                ema_200 = tf_15m.get('ema_200') or 0
                trend_strength = abs((ema_20 - ema_200) / ema_200) if ema_200 > 0 else 0
                
                # Regime classification: TREND if trend_strength > 0.005, else RANGE
                regime_threshold = float(os.getenv("REGIME_TREND_THRESHOLD", "0.005"))
                regime = "TREND" if trend_strength > regime_threshold else "RANGE"
                
                # ADX for trend confirmation
                adx = tf_15m.get('adx') or 0
                
                # Add FASE 2 metrics to technical data
                fase2_metrics = {
                    "volatility_pct": round(volatility_pct, 6),
                    "atr": atr,
                    "trend_strength": round(trend_strength, 6),
                    "regime": regime,
                    "adx": adx,
                    "ema_20": ema_20,
                    "ema_200": ema_200
                }
                
                # Combina technical analysis (già presente) con nuovi dati
                enriched_assets_data[symbol] = {
                    "technical": asset_data.get('tech', {}),
                    "fibonacci": additional_data.get('fibonacci', {}),
                    "gann": additional_data.get('gann', {}),
                    "news": additional_data.get('news', {}),
                    "forecast": additional_data.get('forecast', {}),
                    "fase2_metrics": fase2_metrics
                }
                # Pre-score (deterministic) used as base_confidence and guardrail
                tf_15m_local = asset_data.get('tech', {}).get('timeframes', {}).get('15m', {}) or {}
                fib = additional_data.get('fibonacci', {}) or {}
                gann = additional_data.get('gann', {}) or {}
                long_score, long_breakdown = _compute_base_score('LONG', tf_15m_local, fase2_metrics, fib, gann)
                short_score, short_breakdown = _compute_base_score('SHORT', tf_15m_local, fase2_metrics, fib, gann)
                enriched_assets_data[symbol]['pre_score'] = {
                    'LONG': {'base_confidence': long_score, 'breakdown': long_breakdown},
                    'SHORT': {'base_confidence': short_score, 'breakdown': short_breakdown},
                }
                # Range-score (deterministic) used as alternative playbook guardrail
                range_long_score, range_long_breakdown = _compute_range_score('LONG', tf_15m_local, fase2_metrics, fib, gann)
                range_short_score, range_short_breakdown = _compute_range_score('SHORT', tf_15m_local, fase2_metrics, fib, gann)
                enriched_assets_data[symbol]['range_score'] = {
                    'LONG': {'base_confidence': range_long_score, 'breakdown': range_long_breakdown},
                    'SHORT': {'base_confidence': range_short_score, 'breakdown': range_short_breakdown},
                }
                if os.getenv("DEBUG_TF_KEYS", "0") == "1":
                    logger.info(f"[PRESCORE] {symbol} LONG={long_score} SHORT={short_score}")
                    logger.info(f"[RANGE_SCORE] {symbol} LONG={range_long_score} SHORT={range_short_score}")

                    logger.info(f"[PRESCORE_BREAKDOWN] {symbol} LONG={json.dumps(long_breakdown, default=str)[:800]}")
                    logger.info(f"[PRESCORE_BREAKDOWN] {symbol} SHORT={json.dumps(short_breakdown, default=str)[:800]}")

        
        # 6. Costruisci prompt con TUTTO il contesto
        # Estrai informazioni dal payload (tutte da portfolio e global_data)
        max_positions = payload.global_data.get('max_positions', 3)
        positions_open_count = payload.global_data.get('positions_open_count', len(already_open))
        drawdown_pct = payload.global_data.get('drawdown_pct', 0)
        
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
            "learning_params_meta": payload_learning_params_meta
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
        
        # Build enhanced system prompt (fixed indentation - moved outside if block)
        enhanced_system_prompt = (
            SYSTEM_PROMPT
            + constraints_text
            + margin_text
            + cooldown_text
            + performance_text
            + learning_text
            + learning_policy_text
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
                
                # LIMIT entry validation and fallback
                if d.get("entry_type") == "LIMIT":
                    entry_price = d.get("entry_price")
                    entry_expires_sec = d.get("entry_expires_sec", 240)
                    
                    # Validate entry_price
                    # Check for valid positive price (minimum 0.01 to avoid extremely small values)
                    if not entry_price or not isinstance(entry_price, (int, float)) or entry_price < 0.01:
                        logger.warning(f"⚠️ LIMIT entry without valid entry_price for {d.get('symbol')}: {entry_price}. Falling back to MARKET.")
                        d["entry_type"] = "MARKET"
                        d["entry_price"] = None
                        d["entry_expires_sec"] = None
                        # Update rationale to reflect fallback
                        original_rationale = d.get("rationale", "")
                        d["rationale"] = f"[FALLBACK TO MARKET: invalid entry_price] {original_rationale}"
                    else:
                        # Validate and clamp entry_expires_sec
                        try:
                            entry_expires_sec = int(entry_expires_sec)
                            if entry_expires_sec < 10:
                                logger.warning(f"⚠️ entry_expires_sec {entry_expires_sec} < 10, clamping to 10")
                                entry_expires_sec = 10
                            elif entry_expires_sec > 3600:
                                logger.warning(f"⚠️ entry_expires_sec {entry_expires_sec} > 3600, clamping to 3600")
                                entry_expires_sec = 3600
                            d["entry_expires_sec"] = entry_expires_sec
                        except (ValueError, TypeError):
                            logger.warning(f"⚠️ Invalid entry_expires_sec for {d.get('symbol')}, using default 240")
                            d["entry_expires_sec"] = 240
                
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

                # PRE-SCORE + RANGE-SCORE GUARDRAIL:
                # Allow OPEN only if either:
                # - trend pre_score >= MIN_PRE_SCORE
                # - range_score >= MIN_RANGE_SCORE
                if valid_dec.action in ["OPEN_LONG", "OPEN_SHORT"]:
                    ps = enriched_assets_data.get(valid_dec.symbol, {}).get('pre_score', {}) or {}
                    rs = enriched_assets_data.get(valid_dec.symbol, {}).get('range_score', {}) or {}

                    dir_key = 'LONG' if valid_dec.action == 'OPEN_LONG' else 'SHORT'

                    base_conf = ps.get(dir_key, {}).get('base_confidence', None)
                    range_conf = rs.get(dir_key, {}).get('base_confidence', None)

                    base_conf_i = int(base_conf) if isinstance(base_conf, (int, float)) else None
                    range_conf_i = int(range_conf) if isinstance(range_conf, (int, float)) else None

                    passes_trend = (base_conf_i is not None and base_conf_i >= MIN_PRE_SCORE)
                    passes_range = (range_conf_i is not None and range_conf_i >= MIN_RANGE_SCORE)

                    if not (passes_trend or passes_range):
                        current_blocked = list(valid_dec.blocked_by or [])
                        if 'LOW_PRE_SCORE' not in current_blocked:
                            current_blocked.append('LOW_PRE_SCORE')
                        if 'LOW_RANGE_SCORE' not in current_blocked:
                            current_blocked.append('LOW_RANGE_SCORE')
                        valid_dec.blocked_by = current_blocked
                        valid_dec.action = 'HOLD'
                        valid_dec.leverage = 0
                        valid_dec.size_pct = 0
                        valid_dec.rationale = (
                            f"Blocked: trend_base_conf={base_conf_i} (min={MIN_PRE_SCORE}), "
                            f"range_base_conf={range_conf_i} (min={MIN_RANGE_SCORE}). "
                            f"Original: {valid_dec.rationale}"
                        )
                    else:
                        # Cap confidence to the best available score (+10)
                        best = None
                        if passes_trend:
                            best = base_conf_i
                        if passes_range and (best is None or (range_conf_i is not None and range_conf_i > best)):
                            best = range_conf_i

                        if best is not None:
                            if valid_dec.confidence is None:
                                valid_dec.confidence = best
                            else:
                                try:
                                    valid_dec.confidence = min(int(valid_dec.confidence), best + 10)
                                except Exception:
                                    valid_dec.confidence = best
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
                    
                    # Add INSUFFICIENT_MARGIN to blocked_by
                    current_blocked = list(valid_dec.blocked_by or [])
                    if "INSUFFICIENT_MARGIN" not in current_blocked:
                        current_blocked.append("INSUFFICIENT_MARGIN")
                    valid_dec.blocked_by = current_blocked
                    
                    valid_dec.rationale = (
                        f"Blocked: insufficient free margin "
                        f"(available_for_new_trades={wallet_available_for_new_trades:.2f}, "
                        f"threshold={margin_threshold}). "
                        f"Original: {valid_dec.rationale}"
                    )
                
                # CRASH GUARD: blocca OPEN_LONG/OPEN_SHORT basato su momentum 5m
                # Evita "knife catching" durante crash/pump rapidi
                symbol = valid_dec.symbol
                tech_data = enriched_assets_data.get(symbol, {}).get('technical', {})
                return_5m = tech_data.get('summary', {}).get('return_5m', 0)
                return_15m = tech_data.get('summary', {}).get('return_15m', 0)

                # AIRBAG (SOL only): block contrarian entries in moderate trend that may not trigger crash_guard
                # This prevents "price rising -> OPEN_SHORT" / "price falling -> OPEN_LONG" churn on SOL.
                try:
                    sym_u = (symbol or "").upper()
                    r15 = float(return_15m or 0)
                    if sym_u == "SOLUSDT" and valid_dec.action in ["OPEN_LONG", "OPEN_SHORT"]:
                        if valid_dec.action == "OPEN_SHORT" and r15 >= 0.25:
                            reason = (
                                f"MOMENTUM_15M_GUARD: Blocked OPEN_SHORT on SOL due to bullish 15m trend "
                                f"(return_15m={r15:.2f}% >= +0.25%). Avoiding shorting strength."
                            )
                            logger.warning(f"🚫 {reason}")
                            valid_dec.action = "HOLD"
                            valid_dec.leverage = 0
                            valid_dec.size_pct = 0
                            cb = list(valid_dec.blocked_by or [])
                            if "MOMENTUM_UP_15M" not in cb:
                                cb.append("MOMENTUM_UP_15M")
                            valid_dec.blocked_by = cb
                            valid_dec.rationale = f"{reason} Original: {valid_dec.rationale}"
                        elif valid_dec.action == "OPEN_LONG" and r15 <= -0.25:
                            reason = (
                                f"MOMENTUM_15M_GUARD: Blocked OPEN_LONG on SOL due to bearish 15m trend "
                                f"(return_15m={r15:.2f}% <= -0.25%). Avoiding catching a falling knife."
                            )
                            logger.warning(f"🚫 {reason}")
                            valid_dec.action = "HOLD"
                            valid_dec.leverage = 0
                            valid_dec.size_pct = 0
                            cb = list(valid_dec.blocked_by or [])
                            if "MOMENTUM_DOWN_15M" not in cb:
                                cb.append("MOMENTUM_DOWN_15M")
                            valid_dec.blocked_by = cb
                            valid_dec.rationale = f"{reason} Original: {valid_dec.rationale}"
                except Exception as _e:
                    logger.warning(f"⚠️ MOMENTUM_15M_GUARD failed: {_e}")
                
                crash_guard_blocked = False
                crash_guard_reason = ""
                
                # Block LONG if return_5m <= -CRASH_GUARD_5M_LONG_BLOCK_PCT (rapid dump)
                if valid_dec.action == "OPEN_LONG" and return_5m <= -CRASH_GUARD_5M_LONG_BLOCK_PCT:
                    crash_guard_blocked = True
                    crash_guard_reason = (
                        f"CRASH_GUARD: Blocked OPEN_LONG due to rapid dump "
                        f"(return_5m={return_5m:.2f}% <= -{CRASH_GUARD_5M_LONG_BLOCK_PCT}%). "
                        f"Avoiding knife catching."
                    )
                    logger.warning(f"🚫 {crash_guard_reason}")
                
                # Block SHORT if return_5m >= +CRASH_GUARD_5M_SHORT_BLOCK_PCT (rapid pump)
                elif valid_dec.action == "OPEN_SHORT" and return_5m >= CRASH_GUARD_5M_SHORT_BLOCK_PCT:
                    crash_guard_blocked = True
                    crash_guard_reason = (
                        f"CRASH_GUARD: Blocked OPEN_SHORT due to rapid pump "
                        f"(return_5m={return_5m:.2f}% >= +{CRASH_GUARD_5M_SHORT_BLOCK_PCT}%). "
                        f"Avoiding counter-momentum entry."
                    )
                    logger.warning(f"🚫 {crash_guard_reason}")
                
                if crash_guard_blocked:
                    # Converti in HOLD e aggiorna blocked_by
                    valid_dec.action = "HOLD"
                    valid_dec.leverage = 0
                    valid_dec.size_pct = 0
                    
                    # Aggiungi CRASH_GUARD a blocked_by se non già presente
                    current_blocked = list(valid_dec.blocked_by or [])
                    if "CRASH_GUARD" not in current_blocked:
                        current_blocked.append("CRASH_GUARD")
                    valid_dec.blocked_by = current_blocked
                    
                    # Aggiungi crash guard reason al rationale
                    valid_dec.rationale = f"{crash_guard_reason} Original: {valid_dec.rationale}"
                
                # FASE 2: VOLATILITY FILTER (anti-chop)
                # Block entry if volatility (ATR/price) is too low
                # Volatility filter thresholds (trend vs range playbook)
                min_volatility_trend = float(os.getenv("MIN_VOLATILITY_PCT_TREND", os.getenv("MIN_VOLATILITY_PCT", "0.0025")))
                min_volatility_range = float(os.getenv("MIN_VOLATILITY_PCT_RANGE", "0.0010"))
                fase2_metrics = enriched_assets_data.get(symbol, {}).get('fase2_metrics', {})
                volatility_pct = fase2_metrics.get('volatility_pct', 0)
                
                # Choose threshold based on whether RANGE playbook is eligible for this direction
                selected_threshold = min_volatility_trend
                try:
                    rs = enriched_assets_data.get(valid_dec.symbol, {}).get("range_score", {}) or {}
                    dir_key = "LONG" if valid_dec.action == "OPEN_LONG" else "SHORT"
                    range_conf = rs.get(dir_key, {}).get("base_confidence", None)
                    range_conf_i = int(range_conf) if isinstance(range_conf, (int, float)) else None
                    if range_conf_i is not None and range_conf_i >= MIN_RANGE_SCORE:
                        selected_threshold = min_volatility_range
                except Exception:
                    selected_threshold = min_volatility_trend

                if valid_dec.action in ["OPEN_LONG", "OPEN_SHORT"] and volatility_pct < selected_threshold:
                    volatility_blocked_reason = (
                        f"VOLATILITY_FILTER: Blocked {valid_dec.action} due to low volatility "
                        f"(volatility={volatility_pct:.4f} < threshold={selected_threshold}). "
                        f"Market in consolidation/chop mode - avoiding entry."
                    )
                    logger.warning(f"🚫 {volatility_blocked_reason}")
                    
                    # Convert to HOLD
                    valid_dec.action = "HOLD"
                    valid_dec.leverage = 0
                    valid_dec.size_pct = 0
                    
                    # Add to blocked_by
                    current_blocked = list(valid_dec.blocked_by or [])
                    if "LOW_VOLATILITY" not in current_blocked:
                        current_blocked.append("LOW_VOLATILITY")
                    valid_dec.blocked_by = current_blocked
                    
                    # Add to rationale
                    valid_dec.rationale = f"{volatility_blocked_reason} Original: {valid_dec.rationale}"
                
                valid_decisions.append(valid_dec)
                
                # Salva la decisione per la dashboard (including FASE 2 metrics)
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
                    'soft_blockers': valid_dec.soft_blockers or [],
                    'direction_considered': valid_dec.direction_considered or 'NONE',
                    # FASE 2 metrics
                    'regime': fase2_metrics.get('regime', 'UNKNOWN'),
                    'trend_strength': fase2_metrics.get('trend_strength', 0),
                    'volatility_pct': fase2_metrics.get('volatility_pct', 0),
                    'adx': fase2_metrics.get('adx', 0)
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
