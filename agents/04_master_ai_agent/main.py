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

# Risk-based sizing configuration (anti-blowup protection)
MAX_LOSS_USDT_PER_TRADE = float(os.getenv("MAX_LOSS_USDT_PER_TRADE", "0.35"))  # Maximum loss per trade in USDT
MAX_TOTAL_RISK_USDT = float(os.getenv("MAX_TOTAL_RISK_USDT", "1.5"))  # Maximum total risk across all positions
MIN_SL_DISTANCE_PCT = float(os.getenv("MIN_SL_DISTANCE_PCT", "0.0025"))  # Minimum SL distance (0.25%)
MAX_SL_DISTANCE_PCT = float(os.getenv("MAX_SL_DISTANCE_PCT", "0.025"))  # Maximum SL distance (2.5%)
MAX_NOTIONAL_USDT = float(os.getenv("MAX_NOTIONAL_USDT", "50.0"))  # Maximum notional size per trade
MARGIN_SAFETY_FACTOR = float(os.getenv("MARGIN_SAFETY_FACTOR", "0.85"))  # Margin safety factor

# Recovery sizing configuration (martingale-like, default OFF for LIVE)
ENABLE_RECOVERY_SIZING = os.getenv("ENABLE_RECOVERY_SIZING", "false").lower() == "true"

# Leverage constraints
MIN_LEVERAGE = float(os.getenv("MIN_LEVERAGE", "3"))  # Minimum leverage for OPEN actions
MAX_LEVERAGE_OPEN = float(os.getenv("MAX_LEVERAGE_OPEN", "10"))  # Maximum leverage for OPEN actions
ENABLE_CONFIDENCE_LEVERAGE_ADJUST = os.getenv("ENABLE_CONFIDENCE_LEVERAGE_ADJUST", "false").lower() == "true"
LEVERAGE_CAP_CONFIDENCE_LOW = float(os.getenv("LEVERAGE_CAP_CONFIDENCE_LOW", "60"))
LEVERAGE_CAP_CONFIDENCE_MED = float(os.getenv("LEVERAGE_CAP_CONFIDENCE_MED", "75"))
LEVERAGE_MAX_CONFIDENCE_LOW = float(os.getenv("LEVERAGE_MAX_CONFIDENCE_LOW", "4"))
LEVERAGE_MAX_CONFIDENCE_MED = float(os.getenv("LEVERAGE_MAX_CONFIDENCE_MED", "6"))

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
    """Salva la decisione AI per visualizzarla nella dashboard con metadata input per audit"""
    try:
        decisions = []
        if os.path.exists(AI_DECISIONS_FILE):
            with open(AI_DECISIONS_FILE, 'r') as f:
                decisions = json.load(f)
        
        # Prepare input snapshot for audit/correlation
        input_snapshot = {}
        if 'input_snapshot' in decision_data:
            input_snapshot = decision_data['input_snapshot']
        else:
            # Create minimal snapshot if not provided
            input_snapshot = {
                'entry_price': decision_data.get('entry_price'),
                'sl_pct': decision_data.get('sl_pct'),
                'tp_pct': decision_data.get('tp_pct'),
                'leverage': decision_data.get('leverage'),
                'entry_type': decision_data.get('entry_type'),
                'wallet_available': decision_data.get('wallet_available'),
                'positions_open': decision_data.get('positions_open'),
            }
        
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
            'direction_considered': decision_data.get('direction_considered', 'NONE'),
            # Input snapshot for audit/correlation
            'input_snapshot': input_snapshot,
            'prompt_version': 'v3_neutral',  # Track prompt version for A/B testing
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

# Valid blocker values (used for normalization/mapping)
VALID_HARD_BLOCKERS = {
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
}

VALID_SOFT_BLOCKERS = {
    "LOW_CONFIDENCE",
    "CONFLICTING_SIGNALS",
}

# Mapping for common aliases/variations
HARD_BLOCKER_ALIASES = {
    "INSUFFICIENT_BALANCE": "INSUFFICIENT_MARGIN",
    "NO_MARGIN": "INSUFFICIENT_MARGIN",
    "LOW_CONFIDENCE_SETUP": "LOW_PRE_SCORE",  # Map to closest hard blocker
    "MAX_POSITION": "MAX_POSITIONS",
    "POSITION_LIMIT": "MAX_POSITIONS",
    "COOLDOWN_ACTIVE": "COOLDOWN",
    "DRAWDOWN": "DRAWDOWN_GUARD",
    "DRAWDOWN_LIMIT": "DRAWDOWN_GUARD",
    "CRASH": "CRASH_GUARD",
    "KNIFE_CATCHING": "CRASH_GUARD",
    "LOW_VOL": "LOW_VOLATILITY",
    "NO_VOLATILITY": "LOW_VOLATILITY",
    "MOMENTUM_UP": "MOMENTUM_UP_15M",
    "MOMENTUM_DOWN": "MOMENTUM_DOWN_15M",
}

SOFT_BLOCKER_ALIASES = {
    "LOW_CONF": "LOW_CONFIDENCE",
    "CONFIDENCE_LOW": "LOW_CONFIDENCE",
    "CONFLICTING": "CONFLICTING_SIGNALS",
    "MIXED_SIGNALS": "CONFLICTING_SIGNALS",
}


def normalize_blocker_value(value: str, blocker_type: str = "hard") -> Optional[str]:
    """
    Normalize a blocker value by:
    1. Stripping whitespace
    2. Extracting token before first space or '('
    3. Converting to uppercase
    4. Replacing '-' with '_'
    5. Mapping common aliases to valid enum values
    6. Returning None for unknown values (with warning)
    
    Args:
        value: Raw blocker string from LLM (e.g., "LOW_PRE_SCORE (47)")
        blocker_type: Either "hard" or "soft"
    
    Returns:
        Normalized blocker string or None if invalid
    """
    if not value or not isinstance(value, str):
        return None
    
    # Step 1: Strip whitespace
    value = value.strip()
    
    # Step 2: Extract token before first space or '('
    if ' ' in value:
        value = value.split(' ')[0]
    if '(' in value:
        value = value.split('(')[0].strip()
    
    # Step 3: Uppercase
    value = value.upper()
    
    # Step 4: Replace '-' with '_'
    value = value.replace('-', '_')
    
    # Step 5: Check if empty after processing
    if not value:
        return None
    
    # Step 6: Check if already valid
    if blocker_type == "hard":
        if value in VALID_HARD_BLOCKERS:
            return value
        # Check aliases
        if value in HARD_BLOCKER_ALIASES:
            return HARD_BLOCKER_ALIASES[value]
    else:  # soft
        if value in VALID_SOFT_BLOCKERS:
            return value
        # Check aliases
        if value in SOFT_BLOCKER_ALIASES:
            return SOFT_BLOCKER_ALIASES[value]
    
    # Step 7: Unknown value - log warning and return None
    logger.warning(f"⚠️ Unknown {blocker_type} blocker value: '{value}' - dropping")
    return None


def normalize_blocker_list(values: List[str], blocker_type: str = "hard") -> List[str]:
    """
    Normalize a list of blocker values, dropping invalid ones.
    
    Args:
        values: List of raw blocker strings
        blocker_type: Either "hard" or "soft"
    
    Returns:
        List of normalized, valid blocker strings
    """
    if not values:
        return []
    
    normalized = []
    for value in values:
        norm_value = normalize_blocker_value(value, blocker_type)
        if norm_value is not None:
            normalized.append(norm_value)
    
    return normalized


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
    blocked_by: Optional[List[str]] = None  # HARD constraints (normalized via field_validator, unknown values dropped)
    soft_blockers: Optional[List[str]] = None  # SOFT warnings/flags (normalized via field_validator, unknown values dropped)
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
    
    @field_validator('blocked_by', mode='before')
    @classmethod
    def normalize_blocked_by(cls, v):
        """Normalize blocked_by field to handle LLM output variations"""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        # Normalize each value
        return normalize_blocker_list(v, blocker_type="hard")
    
    @field_validator('soft_blockers', mode='before')
    @classmethod
    def normalize_soft_blockers(cls, v):
        """Normalize soft_blockers field to handle LLM output variations"""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        # Normalize each value
        return normalize_blocker_list(v, blocker_type="soft")

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


def compute_risk_based_size(
    symbol: str,
    entry_price: float,
    stop_loss_price: float,
    leverage: float,
    available_for_new_trades: float,
    active_positions: List[dict],
) -> dict:
    """
    Calculate position size based on maximum loss per trade (risk-based sizing).
    Returns dict with: {size_pct, notional_usdt, margin_required, blocked_by, blocked_reason}
    
    Logic:
    1. Calculate SL distance percentage
    2. Check SL distance is within [MIN_SL_DISTANCE_PCT, MAX_SL_DISTANCE_PCT]
    3. Calculate notional = MAX_LOSS_USDT_PER_TRADE / sl_distance_pct
    4. Clamp notional to MAX_NOTIONAL_USDT
    5. Calculate margin_required = notional / leverage
    6. Check margin_required <= available_for_new_trades * MARGIN_SAFETY_FACTOR
    7. Check total risk across all positions + this trade <= MAX_TOTAL_RISK_USDT
    
    If any check fails, return blocked_by with reason.
    """
    try:
        # Validate inputs
        if entry_price <= 0 or stop_loss_price <= 0 or leverage <= 0:
            return {
                "size_pct": 0.0,
                "notional_usdt": 0.0,
                "margin_required": 0.0,
                "blocked_by": ["INVALID_RISK_PARAMS"],
                "blocked_reason": f"Invalid risk params: entry={entry_price}, sl={stop_loss_price}, lev={leverage}"
            }
        
        # 1. Calculate SL distance percentage
        sl_distance_pct = abs(entry_price - stop_loss_price) / entry_price
        
        # 2. Check SL distance bounds
        if sl_distance_pct < MIN_SL_DISTANCE_PCT:
            return {
                "size_pct": 0.0,
                "notional_usdt": 0.0,
                "margin_required": 0.0,
                "blocked_by": ["SL_TOO_TIGHT"],
                "blocked_reason": f"SL distance {sl_distance_pct*100:.3f}% < min {MIN_SL_DISTANCE_PCT*100:.3f}%"
            }
        
        if sl_distance_pct > MAX_SL_DISTANCE_PCT:
            return {
                "size_pct": 0.0,
                "notional_usdt": 0.0,
                "margin_required": 0.0,
                "blocked_by": ["SL_TOO_WIDE"],
                "blocked_reason": f"SL distance {sl_distance_pct*100:.3f}% > max {MAX_SL_DISTANCE_PCT*100:.3f}%"
            }
        
        # 3. Calculate notional based on max loss per trade
        notional_usdt = MAX_LOSS_USDT_PER_TRADE / sl_distance_pct
        
        # 4. Clamp to MAX_NOTIONAL_USDT
        notional_usdt = min(notional_usdt, MAX_NOTIONAL_USDT)
        
        # 5. Calculate margin required
        margin_required = notional_usdt / leverage
        
        # 6. Check margin availability
        max_margin_allowed = available_for_new_trades * MARGIN_SAFETY_FACTOR
        if margin_required > max_margin_allowed:
            return {
                "size_pct": 0.0,
                "notional_usdt": notional_usdt,
                "margin_required": margin_required,
                "blocked_by": ["INSUFFICIENT_MARGIN_FOR_RISK"],
                "blocked_reason": f"Margin required {margin_required:.2f} > available {max_margin_allowed:.2f} (safety factor {MARGIN_SAFETY_FACTOR})"
            }
        
        # 7. Check total risk across portfolio
        # Calculate risk for existing positions (estimate based on SL distance)
        total_existing_risk = 0.0
        for pos in active_positions:
            # Estimate risk as a fraction of current value
            # Conservative assumption: 1% SL distance if actual SL not available
            # TODO: Fetch actual SL from position manager for more accurate calculation
            conservative_sl_estimate_pct = 0.01  # 1% conservative estimate
            try:
                pos_mark_price = float(pos.get('mark_price', 0))
                pos_size = float(pos.get('size', 0))
                pos_leverage = float(pos.get('leverage', 1))
                if pos_mark_price > 0 and pos_size > 0:
                    pos_notional = pos_mark_price * pos_size
                    # Use conservative SL distance for risk estimation
                    estimated_sl_dist = conservative_sl_estimate_pct
                    pos_risk = pos_notional * estimated_sl_dist
                    total_existing_risk += pos_risk
            except Exception:
                pass
        
        new_trade_risk = notional_usdt * sl_distance_pct
        total_risk = total_existing_risk + new_trade_risk
        
        if total_risk > MAX_TOTAL_RISK_USDT:
            return {
                "size_pct": 0.0,
                "notional_usdt": notional_usdt,
                "margin_required": margin_required,
                "blocked_by": ["MAX_TOTAL_RISK_EXCEEDED"],
                "blocked_reason": f"Total portfolio risk {total_risk:.2f} USDT > max {MAX_TOTAL_RISK_USDT:.2f} USDT"
            }
        
        # Calculate size_pct for backward compatibility
        # Formula: size_pct = margin_required / available_for_new_trades
        # Note: This is the fraction of available margin to use, not the fraction of notional
        size_pct = margin_required / available_for_new_trades if available_for_new_trades > 0 else 0.0
        size_pct = min(size_pct, 1.0)  # Cap at 100%
        
        return {
            "size_pct": size_pct,
            "notional_usdt": notional_usdt,
            "margin_required": margin_required,
            "blocked_by": [],
            "blocked_reason": "",
            "sl_distance_pct": sl_distance_pct,
            "total_risk_usdt": total_risk,
            "new_trade_risk_usdt": new_trade_risk
        }
        
    except Exception as e:
        logger.error(f"❌ Error in compute_risk_based_size: {e}")
        return {
            "size_pct": 0.0,
            "notional_usdt": 0.0,
            "margin_required": 0.0,
            "blocked_by": ["RISK_CALC_ERROR"],
            "blocked_reason": f"Risk calculation error: {str(e)}"
        }


def clamp_leverage_by_confidence(leverage: float, confidence: Optional[int]) -> float:
    """
    Clamp leverage based on confidence level if ENABLE_CONFIDENCE_LEVERAGE_ADJUST is true.
    
    Returns clamped leverage in range [MIN_LEVERAGE, MAX_LEVERAGE_OPEN]
    """
    # Always apply min/max bounds
    leverage = max(MIN_LEVERAGE, min(leverage, MAX_LEVERAGE_OPEN))
    
    # Apply confidence-based adjustment if enabled
    if ENABLE_CONFIDENCE_LEVERAGE_ADJUST and confidence is not None:
        if confidence < LEVERAGE_CAP_CONFIDENCE_LOW:
            # Low confidence: cap at lower leverage
            leverage = min(leverage, LEVERAGE_MAX_CONFIDENCE_LOW)
        elif confidence < LEVERAGE_CAP_CONFIDENCE_MED:
            # Medium confidence: cap at medium leverage
            leverage = min(leverage, LEVERAGE_MAX_CONFIDENCE_MED)
        # High confidence (>=75): use full range up to MAX_LEVERAGE_OPEN
    
    return leverage


SYSTEM_PROMPT = """
You are an experienced crypto trading AI analyzing market data to make informed trading decisions.

## Your Role
Analyze the provided market data and make trading decisions based on your assessment of the setup quality.
You have access to technical indicators, price action, volume data, support/resistance levels, and market sentiment.

## Decision Format
For each asset, provide a JSON decision with:
- **symbol**: Asset symbol
- **action**: "OPEN_LONG", "OPEN_SHORT", or "HOLD"
- **direction_considered**: "LONG", "SHORT", or "NONE"
- **setup_confirmations**: List of factors supporting your chosen direction
- **blocked_by**: List of HARD constraints preventing trade (empty if none)
- **soft_blockers**: List of SOFT concerns (warnings, not blockers)
- **confidence**: Your confidence level (0-100)
- **rationale**: Clear explanation of your decision
- **leverage**: Proposed leverage (will be clamped to safe range)
- **size_pct**: Position size as fraction of available capital (advisory only)
- **tp_pct**, **sl_pct**: Target profit and stop loss percentages
- **time_in_trade_limit_sec**: Maximum holding time in seconds
- **cooldown_sec**: Cooldown period after close
- **entry_type**: "MARKET" or "LIMIT"
- **entry_price**: Required if entry_type="LIMIT"
- **entry_expires_sec**: TTL for LIMIT orders (60-600 seconds recommended)

## Hard Constraints (MUST Block Trade)
If any of these conditions exist, set `blocked_by` and `action` to "HOLD":
- **INSUFFICIENT_MARGIN**: Available balance below minimum threshold
- **MAX_POSITIONS**: Maximum positions limit reached
- **COOLDOWN**: Recent close in same direction
- **DRAWDOWN_GUARD**: Portfolio drawdown exceeds limit
- **CRASH_GUARD**: Extreme momentum against intended direction
- **SYMBOL_ALREADY_OPEN**: Symbol already has an open position
- **LOW_PRE_SCORE**, **LOW_RANGE_SCORE**: Setup quality scores too low
- **MOMENTUM_UP_15M**, **MOMENTUM_DOWN_15M**: Strong trend against direction
- **LOW_VOLATILITY**: Market too choppy for entry

## Soft Constraints (Warnings Only)
These go in `soft_blockers` but don't force HOLD:
- **LOW_CONFIDENCE**: Confidence below 50% but with valid confirmations
- **CONFLICTING_SIGNALS**: Mixed signals requiring careful consideration

## Available Data
You receive for each symbol:
- **market_data**: Technical indicators (RSI, MACD, ADX, EMA, ATR, returns) across multiple timeframes (15m, 1h, 4h, 1d)
- **fibonacci**: Fibonacci retracement/extension levels
- **gann**: Gann levels and geometric support/resistance
- **news**: Sentiment analysis from news sources
- **forecast**: Price prediction models
- **fase2_metrics**: Volatility, ADX, trend strength, EMA positioning

## Decision Guidelines
1. Analyze all available data for each symbol
2. Identify potential setup direction (LONG/SHORT/NONE)
3. Collect confirmations supporting your direction
4. Check for hard constraints in `wallet.can_open_new_positions` and other system flags
5. Make decision: if hard-blocked → HOLD, otherwise use your judgment
6. Provide clear rationale explaining your analysis

## Risk Parameters
- Use `sl_pct` to define stop loss distance (e.g., 0.015 = 1.5%)
- Use `tp_pct` to define take profit target (e.g., 0.02 = 2%)
- Stop loss should be tight enough for capital protection but wide enough to avoid noise
- Your `size_pct` is advisory; actual sizing will be calculated based on risk management rules

## LIMIT Entry Strategy
Use LIMIT entries when:
- Price is near a key support/resistance level (Fibonacci, Gann)
- You want precise entry at a specific price
- Market is in RANGE mode (not trending strongly)

Use MARKET entries when:
- Setup is time-sensitive (breakout, momentum)
- High volatility or trending market
- No clear support/resistance nearby

## Output JSON Format
```json
{
  "analysis_summary": "Brief market overview",
  "decisions": [
    {
      "symbol": "BTCUSDT",
      "action": "OPEN_LONG" | "OPEN_SHORT" | "HOLD",
      "direction_considered": "LONG" | "SHORT" | "NONE",
      "setup_confirmations": ["confirmation1", "confirmation2", "confirmation3"],
      "blocked_by": [],
      "soft_blockers": [],
      "confidence": 75,
      "rationale": "Detailed explanation of decision and reasoning",
      "leverage": 5.0,
      "size_pct": 0.15,
      "tp_pct": 0.02,
      "sl_pct": 0.015,
      "time_in_trade_limit_sec": 3600,
      "cooldown_sec": 900,
      "entry_type": "MARKET" | "LIMIT",
      "entry_price": 50000.0,
      "entry_expires_sec": 240
    }
  ]
}
```

Remember: Focus on quality setups with multiple confirmations. Respect hard constraints. Provide clear rationale for every decision.
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

        
        # Create cleaned market_data for LLM (remove labels, keep only numeric metrics)
        cleaned_market_data_for_llm = {}
        
        # Whitelist of numeric fields to include from fase2_metrics
        fase2_numeric_fields = {"volatility_pct", "atr", "trend_strength", "adx", "ema_20", "ema_200"}
        
        for symbol, data in enriched_assets_data.items():
            # Deep copy to avoid modifying original
            cleaned_data = {}
            cleaned_data["technical"] = data.get("technical", {})
            cleaned_data["fibonacci"] = data.get("fibonacci", {})
            cleaned_data["gann"] = data.get("gann", {})
            cleaned_data["news"] = data.get("news", {})
            cleaned_data["forecast"] = data.get("forecast", {})
            
            # Include fase2_metrics but filter to numeric fields only (exclude labels)
            fase2 = data.get("fase2_metrics", {})
            if fase2:
                cleaned_fase2 = {k: v for k, v in fase2.items() if k in fase2_numeric_fields}
                cleaned_data["fase2_metrics"] = cleaned_fase2
            
            # OMIT pre_score and range_score from LLM payload
            # These will still be used server-side for validation but not sent to AI
            
            cleaned_market_data_for_llm[symbol] = cleaned_data
        
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
            "market_data": cleaned_market_data_for_llm,  # Use cleaned data without labels
            "recent_closes": recent_closes,
            "recent_losses": recent_losses[:5],
            "system_performance": performance,
            "learning_insights": learning_insights,
            "learning_params": payload_learning_params_params,
            "learning_params_meta": payload_learning_params_meta
        }
        
        # Use SYSTEM_PROMPT directly without concatenating constraints/policy text
        # All necessary context is in prompt_data
        enhanced_system_prompt = SYSTEM_PROMPT
        
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
                
                # LIMIT entry validation - convert to HOLD if invalid (no fallback to MARKET)
                if d.get("entry_type") == "LIMIT":
                    entry_price = d.get("entry_price")
                    entry_expires_sec = d.get("entry_expires_sec", 240)
                    
                    # Validate entry_price
                    # Check for valid positive price (minimum 0.01 to avoid extremely small values)
                    if not entry_price or not isinstance(entry_price, (int, float)) or entry_price < 0.01:
                        logger.warning(f"⚠️ LIMIT entry without valid entry_price for {d.get('symbol')}: {entry_price}. Converting to HOLD.")
                        # Convert to HOLD instead of fallback to MARKET
                        d["action"] = "HOLD"
                        d["entry_type"] = "MARKET"  # Reset to default
                        d["entry_price"] = None
                        d["entry_expires_sec"] = None
                        d["leverage"] = 0
                        d["size_pct"] = 0
                        # Add to blocked_by
                        if "blocked_by" not in d or not isinstance(d["blocked_by"], list):
                            d["blocked_by"] = []
                        if "INVALID_ENTRY_PRICE" not in d["blocked_by"]:
                            d["blocked_by"].append("INVALID_ENTRY_PRICE")
                        # Update rationale
                        original_rationale = d.get("rationale", "")
                        d["rationale"] = f"Blocked: LIMIT entry without valid entry_price ({entry_price}). Original: {original_rationale}"
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
                
                # === SYMBOL_ALREADY_OPEN CHECK ===
                # One position per symbol hard constraint
                if valid_dec.action in ["OPEN_LONG", "OPEN_SHORT"]:
                    # Check if symbol is already in active positions
                    symbol_already_open = False
                    for active_sym in already_open:
                        if active_sym == valid_dec.symbol:
                            symbol_already_open = True
                            break
                    
                    if symbol_already_open:
                        logger.warning(f"🚫 Blocked {valid_dec.action} on {valid_dec.symbol}: symbol already has open position")
                        valid_dec.action = "HOLD"
                        valid_dec.leverage = 0
                        valid_dec.size_pct = 0
                        current_blocked = list(valid_dec.blocked_by or [])
                        if "SYMBOL_ALREADY_OPEN" not in current_blocked:
                            current_blocked.append("SYMBOL_ALREADY_OPEN")
                        valid_dec.blocked_by = current_blocked
                        valid_dec.rationale = f"Blocked: symbol {valid_dec.symbol} already has open position (one per symbol constraint). Original: {valid_dec.rationale}"
                
                # === LEVERAGE CLAMP ===
                # Apply leverage clamping for OPEN actions
                if valid_dec.action in ["OPEN_LONG", "OPEN_SHORT"] and valid_dec.leverage > 0:
                    original_leverage = valid_dec.leverage
                    valid_dec.leverage = clamp_leverage_by_confidence(valid_dec.leverage, valid_dec.confidence)
                    if abs(original_leverage - valid_dec.leverage) > 0.1:
                        logger.info(f"📊 Leverage clamped for {valid_dec.symbol}: {original_leverage:.1f}x → {valid_dec.leverage:.1f}x (confidence={valid_dec.confidence})")
                
                # === RISK-BASED SIZING ===
                # Apply risk-based sizing for OPEN actions (unless ENABLE_RECOVERY_SIZING is true)
                if valid_dec.action in ["OPEN_LONG", "OPEN_SHORT"] and not ENABLE_RECOVERY_SIZING:
                    # Calculate risk-based size using entry_price and sl_pct
                    # For LIMIT orders, use entry_price; for MARKET, estimate from current price
                    try:
                        tech_data = enriched_assets_data.get(valid_dec.symbol, {}).get('technical', {})
                        mark_price = tech_data.get('summary', {}).get('price', 0) if tech_data.get('summary') else 0
                        
                        # Use entry_price if LIMIT, otherwise use mark_price
                        entry_price_for_calc = valid_dec.entry_price if valid_dec.entry_type == "LIMIT" and valid_dec.entry_price else mark_price
                        
                        if entry_price_for_calc > 0 and valid_dec.sl_pct and valid_dec.sl_pct > 0:
                            # Calculate stop loss price
                            if valid_dec.action == "OPEN_LONG":
                                stop_loss_price = entry_price_for_calc * (1 - valid_dec.sl_pct)
                            else:  # OPEN_SHORT
                                stop_loss_price = entry_price_for_calc * (1 + valid_dec.sl_pct)
                            
                            # Get active positions for portfolio risk calculation
                            active_positions_details = []
                            try:
                                # Extract position details from global_data if available
                                for pos in payload.global_data.get('active_positions_details', []):
                                    active_positions_details.append(pos)
                            except Exception:
                                pass
                            
                            # Compute risk-based size
                            risk_sizing = compute_risk_based_size(
                                symbol=valid_dec.symbol,
                                entry_price=entry_price_for_calc,
                                stop_loss_price=stop_loss_price,
                                leverage=valid_dec.leverage,
                                available_for_new_trades=wallet_available_for_new_trades,
                                active_positions=active_positions_details
                            )
                            
                            # Check if blocked by risk constraints
                            if risk_sizing.get("blocked_by"):
                                logger.warning(f"🚫 Risk-based sizing blocked {valid_dec.action} on {valid_dec.symbol}: {risk_sizing.get('blocked_reason')}")
                                valid_dec.action = "HOLD"
                                valid_dec.leverage = 0
                                valid_dec.size_pct = 0
                                current_blocked = list(valid_dec.blocked_by or [])
                                for blocker in risk_sizing.get("blocked_by", []):
                                    if blocker not in current_blocked:
                                        current_blocked.append(blocker)
                                valid_dec.blocked_by = current_blocked
                                valid_dec.rationale = f"Blocked by risk management: {risk_sizing.get('blocked_reason')}. Original: {valid_dec.rationale}"
                            else:
                                # Apply risk-based sizing
                                original_size_pct = valid_dec.size_pct
                                valid_dec.size_pct = risk_sizing.get("size_pct", 0.0)
                                logger.info(
                                    f"📊 Risk-based sizing for {valid_dec.symbol}: "
                                    f"size_pct {original_size_pct:.3f} → {valid_dec.size_pct:.3f}, "
                                    f"notional={risk_sizing.get('notional_usdt', 0):.2f} USDT, "
                                    f"margin={risk_sizing.get('margin_required', 0):.2f} USDT, "
                                    f"sl_dist={risk_sizing.get('sl_distance_pct', 0)*100:.2f}%, "
                                    f"risk={risk_sizing.get('new_trade_risk_usdt', 0):.2f} USDT"
                                )
                        else:
                            logger.warning(f"⚠️ Cannot compute risk-based sizing for {valid_dec.symbol}: missing price or sl_pct")
                    except Exception as e:
                        logger.error(f"❌ Risk-based sizing error for {valid_dec.symbol}: {e}")
                
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
