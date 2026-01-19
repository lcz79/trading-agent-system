import asyncio, httpx, json, os, uuid
from datetime import datetime
import re
from datetime import timedelta

# Local backoff map: (SYMBOL, desired_side) -> datetime until which opens are blocked
OPEN_BACKOFF_UNTIL = {}

def _parse_cooldown_seconds(msg: str):
    """
    Parse messages like: "Anti-flip attivo per ETH/USDT:USDT: blocco long per altri 3589s"
    Returns remaining seconds as int if found, else None.
    """
    if not msg:
        return None
    m = re.search(r"per altri\\s+(\\d+)\\s*s", msg)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

URLS = {
    "tech": "http://01_technical_analyzer:8000",
    "pos": "http://07_position_manager:8000",
    "ai": "http://04_master_ai_agent:8000",
    "learning": "http://10_learning_agent:8000"
}

# --- SYMBOL UNIVERSE ---
DEFAULT_SCAN_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "BNBUSDT", "TRXUSDT",
]

# Comma-separated list of symbols to scan (e.g. "BTCUSDT,ETHUSDT,...")
SCAN_SYMBOLS_ENV = os.getenv("SCAN_SYMBOLS", "").strip()

if SCAN_SYMBOLS_ENV:
    # Normalize: split, strip, uppercase, drop empty, deduplicate preserving order
    _raw = [s.strip().upper() for s in SCAN_SYMBOLS_ENV.split(",")]
    SYMBOLS = list(dict.fromkeys([s for s in _raw if s]))
else:
    SYMBOLS = DEFAULT_SCAN_SYMBOLS[:]

# Optional: disable specific symbols without changing SCAN_SYMBOLS
DISABLED_SYMBOLS = os.getenv("DISABLED_SYMBOLS", "").split(",")  # Comma-separated list of disabled symbols
DISABLED_SYMBOLS = [s.strip().upper() for s in DISABLED_SYMBOLS if s.strip()]  # Clean up empty strings

# Final universe: filter out disabled symbols from the scan list
SYMBOLS = [s for s in SYMBOLS if s not in DISABLED_SYMBOLS]

# --- CONFIGURAZIONE OTTIMIZZAZIONE ---
# Maximum open positions (default 10, configurable via env)
MAX_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "10"))
REVERSE_THRESHOLD = float(os.getenv("REVERSE_THRESHOLD", "2.0"))  # Percentuale perdita per trigger reverse analysis
CRITICAL_LOSS_PCT_LEV = float(os.getenv("CRITICAL_LOSS_PCT_LEV", "12.0"))  # % perdita (con leva) per trigger gestione critica
CYCLE_INTERVAL = 60  # Secondi tra ogni ciclo di controllo (era 900)
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"  # Se true, logga solo azioni senza eseguirle

# --- HEDGE MODE & SCALE-IN CONFIGURATION ---
HEDGE_MODE = os.getenv("BYBIT_HEDGE_MODE", "false").lower() == "true"  # Allow long+short same symbol
ALLOW_SCALE_IN = os.getenv("ALLOW_SCALE_IN", "false").lower() == "true"  # Allow multiple entries same direction
MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE = int(os.getenv("MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE", "1"))

# --- CANCEL+REPLACE CONFIGURATION ---
# Price change threshold for cancel+replace logic (0.1% = 0.001)
PRICE_CHANGE_THRESHOLD_FOR_REPLACE = float(os.getenv("PRICE_CHANGE_THRESHOLD_FOR_REPLACE", "0.001"))

# --- CRITICAL CLOSE CONFIRMATION STATE ---
# Tracks pending CLOSE requests per symbol. Format: {symbol: cycle_count}
# Requires 2 consecutive cycles with CLOSE action to execute
pending_critical_closes = {}

# --- COOLDOWN AFTER CLOSE (prevent immediate re-entry) ---
# Tracks last close time per symbol. Format: {symbol: datetime}
last_close_times = {}
COOLDOWN_AFTER_CLOSE_SEC = 300  # 5 minuti di cooldown dopo chiusura

# --- FAST DECISION PATH TIMEOUTS ---
# Timeout for fast AI decision calls (lower than original 120s to fail faster)
FAST_DECISION_CALL_TIMEOUT_SEC = float(os.getenv("FAST_DECISION_CALL_TIMEOUT_SEC", "35.0"))

# --- AI PARAMS VALIDATION CONFIG (no silent clamping) ---
# These are used for warnings only - Master AI should follow these ranges
MIN_LEVERAGE = 3
MAX_LEVERAGE = 10
MIN_SIZE_PCT = 0.08
MAX_SIZE_PCT = 0.20

AI_DECISIONS_FILE = "/data/ai_decisions.json"


def validate_ai_params(leverage: float, size_pct: float, symbol: str = "") -> tuple:
    """
    Validate AI-provided leverage and size_pct against expected ranges.
    Logs warnings but does NOT modify values (trusts AI decision).
    Returns: (leverage, size_pct, had_warnings)
    """
    had_warnings = False
    warnings = []
    
    # Check leverage bounds
    if leverage < MIN_LEVERAGE:
        warnings.append(f"leverage {leverage:.1f} < {MIN_LEVERAGE} (conservative)")
    elif leverage > MAX_LEVERAGE:
        warnings.append(f"leverage {leverage:.1f} > {MAX_LEVERAGE} (aggressive)")
    
    # Check size_pct bounds
    if size_pct < MIN_SIZE_PCT:
        warnings.append(f"size_pct {size_pct:.3f} < {MIN_SIZE_PCT} (conservative)")
    elif size_pct > MAX_SIZE_PCT:
        warnings.append(f"size_pct {size_pct:.3f} > {MAX_SIZE_PCT} (aggressive)")
    
    if warnings:
        had_warnings = True
        print(f"        ⚠️ AI param validation for {symbol}: {'; '.join(warnings)}")
    
    return leverage, size_pct, had_warnings


async def fetch_learning_params(c: httpx.AsyncClient) -> dict:
    """Fetch evolved params from learning agent. Best-effort: returns {} on failure."""
    try:
        r = await c.get(f"{URLS['learning']}/current_params", timeout=5.0)
        if r.status_code == 200:
            return r.json() or {}
    except Exception as e:
        print(f"        ⚠️ Learning params fetch failed: {e}")
    return {}


# --- HTTP helper: retry su errori di rete/DNS (Temporary failure in name resolution) ---
import time
import random


# --- HTTPX async helper: retry su errori temporanei di rete/DNS ---
async def async_post_with_retry(client, url, json_payload, timeout=30.0, attempts=3, base_sleep=1.0):
    """
    POST JSON con retry/backoff per errori temporanei (DNS, timeout, connessione).
    attempts=3 -> sleep ~1s, ~2s, ~4s (+ jitter)
    """
    last_exc = None
    for n in range(1, attempts + 1):
        try:
            return await client.post(url, json=json_payload, timeout=timeout)
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            retryable = (
                "temporary failure in name resolution" in msg
                or "name resolution" in msg
                or "failed to establish a new connection" in msg
                or "connecterror" in msg
                or "connection refused" in msg
                or "timed out" in msg
                or "timeout" in msg
            )
            if (not retryable) or (n == attempts):
                raise
            sleep_s = (base_sleep * (2 ** (n - 1))) + random.uniform(0, 0.25)
            print(f"        ⏳ Retry {n}/{attempts} POST {url} dopo errore rete/DNS: {e} (sleep {sleep_s:.2f}s)")
            await asyncio.sleep(sleep_s)
    raise last_exc

def post_json_with_retry(url, json_payload, timeout=30, attempts=3, base_sleep=1.0):
    """
    POST JSON con retry/backoff per errori temporanei di rete/DNS.
    attempts=3 -> wait ~1s, ~2s, ~4s (+ jitter)
    """
    last_exc = None
    for n in range(1, attempts + 1):
        try:
            return requests.post(url, json=json_payload, timeout=timeout)
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            retryable = (
                "temporary failure in name resolution" in msg
                or "name resolution" in msg
                or "failed to establish a new connection" in msg
                or "connection refused" in msg
                or "timed out" in msg
                or "timeout" in msg
            )
            if not retryable or n == attempts:
                raise
            sleep_s = (base_sleep * (2 ** (n - 1))) + random.uniform(0, 0.25)
            print(f"        ⏳ Retry {n}/{attempts} POST {url} dopo errore rete/DNS: {e} (sleep {sleep_s:.2f}s)")
            time.sleep(sleep_s)
    raise last_exc


def save_monitoring_decision(positions_count: int, max_positions: int, positions_details: list, reason: str):
    """Salva la decisione di monitoraggio per la dashboard"""
    try:
        decisions = []
        if os.path.exists(AI_DECISIONS_FILE):
            with open(AI_DECISIONS_FILE, 'r') as f:
                decisions = json.load(f)
        
        # Crea un summary delle posizioni
        positions_summary = []
        for p in positions_details:
            pnl_pct = (p.get('pnl', 0) / (p.get('entry_price', 1) * p.get('size', 1))) * 100 if p.get('entry_price') else 0
            positions_summary.append({
                'symbol': p.get('symbol'),
                'side': p.get('side'),
                'pnl': p.get('pnl'),
                'pnl_pct': round(pnl_pct, 2)
            })
        
        decisions.append({
            'timestamp': datetime.now().isoformat(),
            'symbol': 'PORTFOLIO',
            'action': 'HOLD',
            'leverage': 0,
            'size_pct': 0,
            'rationale': reason,
            'analysis_summary': f"Monitoraggio: {positions_count}/{max_positions} posizioni attive",
            'positions': positions_summary
        })
        
        # Mantieni solo le ultime 100 decisioni
        decisions = decisions[-100:]
        
        os.makedirs(os.path.dirname(AI_DECISIONS_FILE), exist_ok=True)
        with open(AI_DECISIONS_FILE, 'w') as f:
            json.dump(decisions, f, indent=2)
            
    except Exception as e:
        print(f"⚠️ Error saving monitoring decision: {e}")


def append_ai_decision_event(event: dict) -> None:
    """Append a single event to /data/ai_decisions.json (list), creating the file if needed.

    The dashboard reads this file to show the AI Decision Log. We must log also CRITICAL cycles.
    """
    import json
    from datetime import datetime
    
    event = dict(event or {})
    event.setdefault("timestamp", datetime.utcnow().isoformat())

    try:
        try:
            with open(AI_DECISIONS_FILE, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except FileNotFoundError:
            data = []
        except Exception:
            # If file is corrupted, start a new log rather than blocking the bot
            data = []

        data.append(event)
        # Keep last N to avoid unbounded growth
        data = data[-500:]

        with open(AI_DECISIONS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"        ⚠️ Failed to write AI decision log: {e}")


def check_critical_close_confirmation(symbol: str, action_type: str) -> bool:
    """
    Implements 2-cycle confirmation for CRITICAL CLOSE actions.
    
    Returns True if action should be executed (second consecutive CLOSE).
    Returns False if action should be pending (first CLOSE).
    
    Updates pending_critical_closes state.
    """
    global pending_critical_closes
    
    if action_type == "CLOSE":
        # Check if this symbol already has a pending CLOSE
        if symbol in pending_critical_closes:
            # Second consecutive CLOSE - execute it
            print(f"        ✅ CRITICAL CLOSE confirmed for {symbol} (2nd cycle)")
            # Remove from pending after execution
            del pending_critical_closes[symbol]
            return True
        else:
            # First CLOSE - mark as pending
            print(f"        ⏸️ CRITICAL CLOSE pending for {symbol} (1st cycle, need confirmation)")
            pending_critical_closes[symbol] = datetime.now().isoformat()
            return False
    else:
        # If action is not CLOSE, reset any pending CLOSE for this symbol
        if symbol in pending_critical_closes:
            print(f"        🔄 CRITICAL CLOSE reset for {symbol} (no CLOSE in this cycle)")
            del pending_critical_closes[symbol]
        return False  # Not a CLOSE action


async def manage_cycle():
    """
    Manages active positions by calling position manager.
    Increased timeout to 60s to allow trailing stop + reverse + AI calls to complete.
    Added retry logic and error logging instead of silent failure.
    """
    async with httpx.AsyncClient() as c:
        learning_params = await fetch_learning_params(c)
        # Retry up to 3 times with exponential backoff
        for attempt in range(1, 4):
            try:
                await c.post(f"{URLS['pos']}/manage_active_positions", timeout=60)
                break  # Success - exit retry loop
            except Exception as e:
                error_msg = str(e).lower()
                # Check if it's a retryable error
                is_retryable = any(x in error_msg for x in ["timeout", "connection", "temporary"])
                
                if attempt == 3 or not is_retryable:
                    # Last attempt or non-retryable error - log and continue
                    print(f"        ⚠️ manage_active_positions error (attempt {attempt}/3): {e}")
                    break
                else:
                    # Retryable error - wait and retry
                    wait_time = 2 ** (attempt - 1)  # 1s, 2s exponential backoff
                    print(f"        ⏳ manage_active_positions retry {attempt}/3 after {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)

async def analysis_cycle():
    async with httpx.AsyncClient(timeout=60) as c:
        learning_params = await fetch_learning_params(c)
        # Manage existing positions (trailing, reverse, time-exit)
                # Manage existing positions (trailing, reverse, time-exit)
        try:
            await c.post(f"{URLS['pos']}/manage_active_positions", timeout=60)
        except Exception as e:
            print(f"        ⚠️ manage_active_positions error: {e}")


        
        # 1. DATA COLLECTION
        portfolio = {}
        position_details = []
        active_symbols = []
        try:
            # Fetch parallelo
            r_bal, r_pos = await asyncio.gather(
                c.get(f"{URLS['pos']}/get_wallet_balance"),
                c.get(f"{URLS['pos']}/get_open_positions"),
                return_exceptions=True
            )
            if hasattr(r_bal, 'json'): portfolio = r_bal.json()
            if hasattr(r_pos, 'json'): 
                d = r_pos.json()
                active_symbols = d.get('active', []) if isinstance(d, dict) else []
                position_details = d.get('details', []) if isinstance(d, dict) else []

        except Exception as e:
            print(f"⚠️ Data Error: {e}")
            return

        num_positions = len(active_symbols)
        print(f"\n[{datetime.now().strftime('%H:%M')}] 📊 Position check: {num_positions}/{MAX_POSITIONS} posizioni aperte")
        
        # 2. LOGICA OTTIMIZZAZIONE
        # Inizializza positions_losing prima di usarla
        positions_losing = []
        
        # Controlla posizioni in perdita oltre la soglia
        for pos in position_details:
            entry = pos.get('entry_price', 0)
            mark = pos.get('mark_price', 0)
            side = pos.get('side', '').lower()
            symbol = pos.get('symbol', '')
            leverage = float(pos.get('leverage', 1))
            
            if entry > 0 and mark > 0:
                # Calcola perdita % CON LEVA (come mostrato su Bybit)
                if side in ['long', 'buy']:
                    loss_pct = ((mark - entry) / entry) * leverage * 100
                else:  # short - loss when mark > entry, profit when mark < entry
                    loss_pct = -((mark - entry) / entry) * leverage * 100  # Negative sign because direction is reversed
                
                if loss_pct < -CRITICAL_LOSS_PCT_LEV:
                    positions_losing.append({
                        'symbol': symbol,
                        'loss_pct': loss_pct,
                        'side': side,
                        'entry_price': entry,
                        'mark_price': mark,
                        'leverage': leverage,
                        'size': pos.get('size', 0),
                        'pnl': pos.get('pnl', 0)
                    })

        # GESTIONE CRITICA POSIZIONI IN PERDITA
        if positions_losing:
            print(f"        🔥 CRITICAL: {len(positions_losing)} posizioni in perdita oltre soglia ({CRITICAL_LOSS_PCT_LEV:.2f}% lev)!")
            for pos_loss in positions_losing:
                print(f"        ⚠️ {pos_loss['symbol']} {pos_loss['side']}: {pos_loss['loss_pct']:.2f}%")
            
            # Chiama Master AI per gestione critica
            try:
                mgmt_start = datetime.now()
                print(f"        📞 Calling Master AI /manage_critical_positions...")
                
                # Prepara richiesta per Master AI
                critical_positions = []
                for pl in positions_losing:
                    critical_positions.append({
                        "symbol": pl['symbol'],
                        "side": pl['side'],
                        "entry_price": pl['entry_price'],
                        "mark_price": pl['mark_price'],
                        "leverage": pl['leverage'],
                        "size": pl.get('size', 0),
                        "pnl": pl.get('pnl', 0),
                        "is_disabled": pl['symbol'] in DISABLED_SYMBOLS
                    })
                
                mgmt_resp = await async_post_with_retry(c, f"{URLS['ai']}/manage_critical_positions", json_payload={
                        "positions": critical_positions,
                        "portfolio_snapshot": portfolio,
                        "learning_params": learning_params,
                    },
                    timeout=60.0
                )
                
                mgmt_elapsed = (datetime.now() - mgmt_start).total_seconds()
                
                if mgmt_resp.status_code == 200:
                    mgmt_data = mgmt_resp.json()
                    actions = mgmt_data.get('actions', [])
                    meta = mgmt_data.get('meta', {})
                    
                    print(f"        ✅ MGMT Response: {len(actions)} actions, {meta.get('processing_time_ms', 0)}ms")
                    append_ai_decision_event({"type": "CRITICAL_MANAGEMENT", "status": "MGMT_RESPONSE", "details": {"note": "manage_critical_positions executed"}})
                    
                    # Log azioni
                    for act in actions:
                        action_type = act.get('action')
                        symbol = act.get('symbol')
                        loss_pct = act.get('loss_pct_with_leverage', 0)
                        confidence = act.get('confidence', 0)
                        print(f"        🎯 ACTION: {symbol} → {action_type} (loss={loss_pct:.2f}%, conf={confidence}%)")
                    
                    # Esegui azioni (se non DRY_RUN)
                    if DRY_RUN:
                        print(f"        🔍 DRY_RUN mode: azioni non eseguite")
                    else:
                        for act in actions:
                            action_type = act.get('action')
                            symbol = act.get('symbol')
                            
                            if action_type == "CLOSE":
                                # Implement 2-cycle confirmation for CRITICAL CLOSE
                                should_execute = check_critical_close_confirmation(symbol, action_type)
                                
                                if should_execute:
                                    print(f"        🔒 Closing {symbol}...")
                                    try:
                                        close_resp = await c.post(
                                            f"{URLS['pos']}/close_position",
                                            json={"symbol": symbol, "exit_reason": "critical_mgmt_close"},
                                            timeout=20.0
                                        )
                                        close_json = close_resp.json()
                                        print(f"        ✅ Close result: {close_json}")
                                        # Registra cooldown per evitare re-entry immediato
                                        last_close_times[symbol] = datetime.now()
                                        print(f"        ⏳ Cooldown attivato per {symbol}: {COOLDOWN_AFTER_CLOSE_SEC}s")

                                        if close_json.get("status") not in ("executed", "no_position"):
                                            print(f"        ⚠️ Close returned status={close_json.get('status')}, retrying once...")
                                            close_resp2 = await c.post(
                                                f"{URLS['pos']}/close_position",
                                                json={"symbol": symbol, "exit_reason": "critical_mgmt_close"},
                                                timeout=20.0
                                            )
                                            close_json2 = close_resp2.json()
                                            print(f"        ✅ Close retry result: {close_json2}")
                                    except Exception as e:
                                        print(f"        ❌ Close error: {e}")
                                # else: should_execute is False - already logged in check_critical_close_confirmation
                            
                            elif action_type == "REVERSE":
                                # REVERSE is disabled for scalping mode by default
                                # Skip REVERSE action - only CLOSE/HOLD allowed
                                print(f"        ⏸️ REVERSE action requested for {symbol} but disabled for scalping mode")
                                print(f"           Treating as CLOSE instead")
                                
                                # Convert REVERSE to CLOSE for scalping mode
                                should_execute = check_critical_close_confirmation(symbol, "CLOSE")
                                
                                if should_execute:
                                    print(f"        🔒 Closing {symbol} (converted from REVERSE)...")
                                    try:
                                        close_resp = await c.post(
                                            f"{URLS['pos']}/close_position",
                                            json={"symbol": symbol, "exit_reason": "critical_mgmt_close"},
                                            timeout=20.0
                                        )
                                        close_json = close_resp.json()
                                        print(f"        ✅ Close result: {close_json}")
                                    except Exception as e:
                                        print(f"        ❌ Close error: {e}")
                                # else: should_execute is False - already logged in check_critical_close_confirmation

                            elif action_type == "HOLD":
                                # Reset pending close for HOLD
                                check_critical_close_confirmation(symbol, "HOLD")
                                print(f"        ⏸️ Holding {symbol} (no action)")
                    
                    # Salta apertura nuove posizioni in questo ciclo
                    append_ai_decision_event({"type": "CRITICAL_MANAGEMENT", "status": "COMPLETED", "rationale": "Critical management cycle completed; new position logic skipped."})
                    print(f"        🛑 Critical management ran, skipping new position logic this cycle")
                    return
                    
                else:
                    print(f"        ❌ MGMT failed: {mgmt_resp.status_code}")
                    
            except Exception as e:
                print(f"        ❌ Critical management error: {e}")
                # Continua con logica normale se gestione critica fallisce

        # CASO 1: Tutte le posizioni occupate (3/3) MA senza posizioni critiche
        if num_positions >= MAX_POSITIONS:
            # Controlla se tutte le posizioni sono realmente in profitto o se ci sono perdite minori
            all_positions_status = []
            all_in_profit = True
            
            for pos in position_details:
                entry = pos.get('entry_price', 0)
                mark = pos.get('mark_price', 0)
                side = pos.get('side', '').lower()
                symbol = pos.get('symbol', '').replace('USDT', '')
                leverage = float(pos.get('leverage', 1))
                
                if entry > 0 and mark > 0:
                    # Calcola P&L % con leva
                    if side in ['long', 'buy']:
                        pnl_pct = ((mark - entry) / entry) * leverage * 100
                    else:  # short
                        pnl_pct = -((mark - entry) / entry) * leverage * 100
                    
                    all_positions_status.append(f"{symbol}: {pnl_pct:+.2f}%")
                    if pnl_pct < 0:
                        all_in_profit = False
            
            # Genera rationale in base allo stato reale
            positions_str = " | ".join(all_positions_status)
            if all_in_profit:
                rationale = f"Tutte le posizioni in profitto. {positions_str}. Nessuna azione richiesta. Continuo monitoraggio trailing stop."
            else:
                rationale = f"Posizioni miste. {positions_str}. Nessuna in perdita critica. Continuo monitoraggio trailing stop."
            
            print(f"        ✅ Nessun allarme perdita - Skip analisi DeepSeek")
            save_monitoring_decision(
                positions_count=len(position_details),
                max_positions=MAX_POSITIONS,
                positions_details=position_details,
                reason=rationale
            )
            return

        # CASO 2: Almeno uno slot libero (< 3 posizioni)
        print(f"        🔍 Slot libero - Chiamo DeepSeek per nuove opportunità")
        
        # 3. FILTER - Solo asset senza posizione aperta
        scan_list = [s for s in SYMBOLS if s not in active_symbols]
        
        # 3b. FILTER - Rimuovi asset in cooldown (recentemente chiusi)
        now = datetime.now()
        for sym in list(scan_list):
            if sym in last_close_times: 
                elapsed = (now - last_close_times[sym]).total_seconds()
                if elapsed < COOLDOWN_AFTER_CLOSE_SEC:
                    remaining = int(COOLDOWN_AFTER_CLOSE_SEC - elapsed)
                    print(f"        ⏳ {sym} in cooldown:  {remaining}s rimanenti")
                    scan_list.remove(sym)
                else:
                    del last_close_times[sym]  # Cooldown scaduto, rimuovi
        if not scan_list:
            print("        ⚠️ Nessun asset disponibile per scan")
            return

        # 4. TECH ANALYSIS
        assets_data = {}
        for s in scan_list:
            try:
                t = (await c.post(f"{URLS['tech']}/analyze_multi_tf_full", json={"symbol": s})).json()
                assets_data[s] = {"tech": t}
            except: pass
        
        if not assets_data: 
            print("        ⚠️ Nessun dato tecnico disponibile")
            save_monitoring_decision(
                positions_count=0,
                max_positions=MAX_POSITIONS,
                positions_details=[],
                reason="Impossibile ottenere dati tecnico dagli analizzatori. Riprovo al prossimo ciclo."
            )
            return
        
        # 4b. ADVANCED PREPROCESSING - Compute enhanced fields
        print(f"        🔬 Preprocessing: Computing regime, confluence, and correlation risk...")
        from regime import detect_regime_with_hysteresis, calculate_volatility_bucket
        from confluence import calculate_confluence_score
        from correlation import calculate_portfolio_correlation_risk
        
        for symbol, asset_dict in assets_data.items():
            try:
                tech = asset_dict.get("tech", {})
                timeframes = tech.get("timeframes", {})
                tf_15m = timeframes.get("15m", {})
                
                # Extract data from 15m timeframe
                adx = tf_15m.get("adx", 20.0)
                atr = tf_15m.get("atr", 0.0)
                price = tf_15m.get("price", 0.0)
                trend = tf_15m.get("trend")
                ema_20 = tf_15m.get("ema_20")
                ema_50 = tf_15m.get("ema_50")
                
                # Compute regime with hysteresis
                regime, regime_meta = detect_regime_with_hysteresis(
                    symbol=symbol,
                    adx=adx,
                    atr=atr,
                    price=price,
                    trend=trend,
                    ema_20=ema_20,
                    ema_50=ema_50
                )
                
                # Compute volatility bucket
                volatility_bucket = calculate_volatility_bucket(atr, price)
                
                # Compute confluence scores for both directions
                long_confluence, long_breakdown = calculate_confluence_score("LONG", timeframes)
                short_confluence, short_breakdown = calculate_confluence_score("SHORT", timeframes)
                
                # Compute correlation risk (placeholder for forward compatibility)
                corr_risk_long, corr_breakdown_long = calculate_portfolio_correlation_risk(
                    position_details, symbol, "long"
                )
                corr_risk_short, corr_breakdown_short = calculate_portfolio_correlation_risk(
                    position_details, symbol, "short"
                )
                
                # Add enhanced fields to asset data
                asset_dict["enhanced"] = {
                    "regime": regime,
                    "regime_metadata": regime_meta,
                    "volatility_bucket": volatility_bucket,
                    "confluence": {
                        "long": {
                            "score": long_confluence,
                            "breakdown": long_breakdown
                        },
                        "short": {
                            "score": short_confluence,
                            "breakdown": short_breakdown
                        }
                    },
                    "correlation_risk": {
                        "long": corr_risk_long,
                        "short": corr_risk_short,
                        "breakdown_long": corr_breakdown_long,
                        "breakdown_short": corr_breakdown_short
                    }
                }
                
                # Log computed fields in debug mode
                print(f"          {symbol}: regime={regime}, vol={volatility_bucket}, "
                      f"confluence(L/S)={long_confluence}/{short_confluence}")
                
            except Exception as e:
                print(f"        ⚠️ Preprocessing error for {symbol}: {e}")
                # Add default enhanced fields on error (fail-safe)
                asset_dict["enhanced"] = {
                    "regime": "UNKNOWN",
                    "volatility_bucket": "MEDIUM",
                    "confluence": {
                        "long": {"score": 50, "breakdown": {}},
                        "short": {"score": 50, "breakdown": {}}
                    },
                    "correlation_risk": {
                        "long": 0.0,
                        "short": 0.0
                    },
                    "error": str(e)
                }

        # 5. AI DECISION - FAST PATH
        print(f"        🤖 DeepSeek Fast: Analizzando {list(assets_data.keys())}...")
        try:
            # Garantisce che portfolio abbia tutti i campi necessari
            # Se available_for_new_trades manca, calcola fallback sicuro
            if "available_for_new_trades" not in portfolio:
                available = portfolio.get('available', 0)
                portfolio["available_for_new_trades"] = max(0.0, available * 0.95) if available > 0 else 0.0
                portfolio["available_source"] = "orchestrator_fallback"
            
            # Prepara payload con portfolio contenente tutti i campi necessari
            enhanced_global_data = {
                "portfolio": portfolio,  # Contiene: equity, available, available_for_new_trades, available_source
                "already_open": active_symbols,
                "max_positions": MAX_POSITIONS,
                "positions_open_count": num_positions,
            }
            
            # Calcola drawdown se abbiamo dati sufficienti
            if position_details:
                total_pnl = sum(p.get('pnl', 0) for p in position_details)
                equity = portfolio.get('equity', 1)
                if equity > 0:
                    drawdown_pct = (total_pnl / equity) * 100
                    enhanced_global_data['drawdown_pct'] = drawdown_pct
            
            # Call FAST endpoint with configurable timeout (reduced from 120s)
            resp = await async_post_with_retry(c, f"{URLS['ai']}/decide_batch_fast", json_payload={
                    "learning_params": learning_params,
                "global_data": enhanced_global_data,
                "assets_data": assets_data
            }, timeout=FAST_DECISION_CALL_TIMEOUT_SEC)  # Configurable timeout (default 35s)
            
            dec_data = resp.json()
            decisions_list = dec_data.get('decisions', [])
            meta = dec_data.get('meta', {})
            
            print(f"        ⚡ Fast response: {len(decisions_list)} decisions in {meta.get('processing_time_ms', 0)}ms")
            
            # Log fast response event
            append_ai_decision_event({
                "type": "AI_BATCH_FAST_RESPONSE",
                "status": "success",
                "details": {
                    "decisions_count": len(decisions_list),
                    "processing_time_ms": meta.get('processing_time_ms', 0),
                    "symbols": [d.get('symbol') for d in decisions_list]
                }
            })
            
            # Optional: Fetch verbose explanations asynchronously (best-effort, non-blocking)
            # Only if we have valid decisions and not in tight loop
            if decisions_list and len(decisions_list) > 0:
                try:
                    # Fire and forget - don't wait for explanation
                    async def fetch_explanations():
                        try:
                            exp_resp = await c.post(
                                f"{URLS['ai']}/explain_batch",
                                json={
                                    "fast_decisions": decisions_list,
                                    "global_data": enhanced_global_data,
                                    "assets_data": assets_data,
                                    "context_ref": f"cycle_{datetime.now().isoformat()}"
                                },
                                timeout=60.0
                            )
                            if exp_resp.status_code == 200:
                                exp_data = exp_resp.json()
                                print(f"        📝 Explanations fetched: {len(exp_data.get('explanations', []))} items")
                                append_ai_decision_event({
                                    "type": "AI_BATCH_EXPLANATION_RESPONSE",
                                    "status": "success",
                                    "details": exp_data
                                })
                        except Exception as exp_err:
                            print(f"        ⚠️ Explanation fetch failed (non-critical): {exp_err}")
                            append_ai_decision_event({
                                "type": "AI_BATCH_EXPLANATION_ERROR",
                                "status": "error",
                                "error": str(exp_err)
                            })
                    
                    # Start explanation fetch in background (don't await)
                    asyncio.create_task(fetch_explanations())
                except Exception as bg_err:
                    print(f"        ⚠️ Could not start background explanation task: {bg_err}")

            if not decisions_list:
                print("        ℹ️ AI non ha generato ordini")
                return

            # 6. EXECUTION
            for d in decisions_list:
                sym = d['symbol']
                action = d['action']
                reason_code = d.get('reason_code', '')
                
                if action == "CLOSE":
                    print(f"        🛡️ Ignorato CLOSE su {sym} (Auto-Close Disabled)")
                    continue
                
                # === OPPORTUNISTIC LIMIT HANDLING ===
                # Note: Fast endpoint doesn't support opportunistic_limit (kept for backward compat with full endpoint)
                # Check for opportunistic_limit when action=HOLD (from legacy /decide_batch calls if any)
                if action == "HOLD":
                    opportunistic_limit = d.get('opportunistic_limit')
                    if opportunistic_limit and isinstance(opportunistic_limit, dict):
                        print(f"        🎯 HOLD with opportunistic_limit for {sym}")
                        
                        # Extract opportunistic LIMIT parameters
                        opp_side = opportunistic_limit.get('side', 'LONG')
                        opp_entry_price = opportunistic_limit.get('entry_price')
                        opp_entry_expires_sec = opportunistic_limit.get('entry_expires_sec', 180)
                        opp_tp_pct = opportunistic_limit.get('tp_pct')
                        opp_sl_pct = opportunistic_limit.get('sl_pct')
                        opp_leverage = opportunistic_limit.get('leverage', 3.5)
                        opp_size_pct = opportunistic_limit.get('size_pct', 0.10)
                        opp_rr = opportunistic_limit.get('rr', 1.5)
                        opp_edge_score = opportunistic_limit.get('edge_score', 70)
                        opp_reasoning = opportunistic_limit.get('reasoning_bullets', [])
                        
                        print(f"           Opportunistic {opp_side}: entry={opp_entry_price}, rr={opp_rr:.2f}, edge={opp_edge_score}")
                        print(f"           Reasoning: {', '.join(opp_reasoning[:3])}")
                        
                        # Map to OPEN action for position manager
                        opp_action = "OPEN_LONG" if opp_side == "LONG" else "OPEN_SHORT"
                        
                        # Check if we can execute opportunistic LIMIT (reuse existing guardrails)
                        # Always fetch open positions before opening (fail-closed)
                        open_positions = []
                        try:
                            _rpos = await c.get(f"{URLS['pos']}/get_open_positions")
                            _pos_data = _rpos.json() or {}
                            open_positions = _pos_data.get('details') or []
                        except Exception as _e:
                            print(f"        ⚠️ Cannot fetch open positions for opportunistic; skipping: {_e}")
                            continue
                        
                        # Check if symbol already has open position
                        desired_side = "long" if opp_side == "LONG" else "short"
                        existing = None
                        for p0 in (open_positions or []):
                            if (p0.get('symbol') or '').upper() != sym.upper():
                                continue
                            qty = 0.0
                            for k in ('contracts','size','positionAmt','qty'):
                                try:
                                    v = p0.get(k)
                                    if v is None:
                                        continue
                                    qty = float(v)
                                    break
                                except Exception:
                                    pass
                            if abs(qty) > 0:
                                existing = p0
                                break
                        
                        if existing is not None:
                            print(f"        🧯 SKIP opportunistic {opp_side} on {sym}: existing open position detected")
                            continue
                        
                        # Generate intent_id for idempotency
                        import uuid
                        intent_id = str(uuid.uuid4())
                        
                        print(f"        🔥 EXECUTING opportunistic LIMIT {opp_side} on {sym} [intent:{intent_id[:8]}]...")
                        
                        # Build payload for position manager
                        payload = {
                            "symbol": sym,
                            "side": opp_action,
                            "leverage": opp_leverage,
                            "size_pct": opp_size_pct,
                            "intent_id": intent_id,
                            "entry_type": "LIMIT",
                            "entry_price": opp_entry_price,
                            "entry_ttl_sec": opp_entry_expires_sec,
                            "features": {
                                "opportunistic": True,
                                "rr": opp_rr,
                                "edge_score": opp_edge_score,
                                "reasoning": opp_reasoning,
                                "original_action": "HOLD"
                            }
                        }
                        
                        # Add optional params if present
                        if opp_tp_pct is not None:
                            payload["tp_pct"] = opp_tp_pct
                        if opp_sl_pct is not None:
                            payload["sl_pct"] = opp_sl_pct
                        
                        try:
                            res = await c.post(f"{URLS['pos']}/open_position", json=payload)
                            print(f"        ✅ Opportunistic LIMIT result: {res.json()}")
                        except Exception as opp_exec_err:
                            print(f"        ❌ Opportunistic LIMIT execution error: {opp_exec_err}")
                        
                        continue  # Skip further processing for this HOLD decision
                    
                    # Log HOLD based on reason_code (fast response uses reason_code instead of rationale)
                    if reason_code and reason_code in ["NO_MARGIN", "INSUFFICIENT_MARGIN"]:
                        available_for_new = portfolio.get('available_for_new_trades', portfolio.get('available', 0))
                        available_source = portfolio.get('available_source', 'unknown')
                        print(f"        🚫 HOLD on {sym}: {reason_code}")
                        print(f"           Wallet: available={available_for_new:.2f} USDT (source: {available_source})")
                        continue
                    
                    # Regular HOLD without opportunistic_limit
                    continue
                
                if action in ["OPEN_LONG", "OPEN_SHORT"]:
                    # HARD GATE: do not trade if AI itself flagged blockers / low confidence
                    confidence = float(d.get("confidence", 0) or 0)
                    blocked_by = d.get("blocked_by") or []
                    if blocked_by:
                        print(f"        🧱 SKIP {action} on {sym}: blocked_by={blocked_by}")
                        continue
                    if confidence < 70:
                        print(f"        🧱 SKIP {action} on {sym}: low confidence ({confidence} < 70)")
                        continue                    # Always fetch open positions before opening (fail-closed).
                    open_positions = []  # default to avoid NameError if fetch fails
                    try:
                        _rpos = await c.get(f"{URLS['pos']}/get_open_positions")
                        _pos_data = _rpos.json() or {}
                        open_positions = _pos_data.get('details') or []
                    except Exception as _e:
                        print(f"        ⚠️ Cannot fetch open positions; skipping open to prevent churn: {_e}")
                        continue

                    # Guardrail: in one-way mode (HedgeMode False) do NOT open another position on the same symbol.
                    desired_side = "long" if action == "OPEN_LONG" else "short"
                    
                    # Cancel+replace logic for pending LIMIT orders
                    # Check if there's a pending LIMIT entry for this symbol+direction
                    entry_type = d.get('entry_type', 'MARKET')
                    entry_price = d.get('entry_price')
                    entry_expires_sec = d.get('entry_expires_sec', 240)
                    
                    if entry_type == 'LIMIT' and entry_price:
                        try:
                            # Query pending intents from position manager
                            pending_resp = await c.get(f"{URLS['pos']}/get_pending_intents")
                            if pending_resp.status_code == 200:
                                pending_data = pending_resp.json()
                                pending_intents = pending_data.get('intents', [])
                                
                                # Look for existing PENDING LIMIT intent for same symbol+side
                                existing_limit = None
                                for intent in pending_intents:
                                    if (intent.get('symbol', '').upper() == sym.upper() and
                                        intent.get('side', '').lower() == desired_side and
                                        intent.get('entry_type') == 'LIMIT' and
                                        intent.get('status') == 'PENDING'):
                                        existing_limit = intent
                                        break
                                
                                # If found and price changed, cancel old and place new
                                if existing_limit:
                                    old_price = existing_limit.get('entry_price')
                                    old_intent_id = existing_limit.get('intent_id')
                                    
                                    # Check if price or expires changed significantly
                                    # Guard against division by zero
                                    if old_price and old_price > 0:
                                        price_changed = abs(float(old_price) - float(entry_price)) / float(old_price) > PRICE_CHANGE_THRESHOLD_FOR_REPLACE
                                    else:
                                        # If old_price is invalid, always replace
                                        price_changed = True
                                    
                                    if price_changed:
                                        print(f"        🔄 Cancel+Replace LIMIT order for {sym}: old_price={old_price} → new_price={entry_price}")
                                        
                                        # Cancel existing order
                                        try:
                                            cancel_resp = await c.post(
                                                f"{URLS['pos']}/cancel_intent",
                                                json={"intent_id": old_intent_id},
                                                timeout=10.0
                                            )
                                            if cancel_resp.status_code == 200:
                                                print(f"        ✅ Cancelled old LIMIT order: {old_intent_id[:8]}")
                                            else:
                                                print(f"        ⚠️ Failed to cancel old order: {cancel_resp.text}")
                                        except Exception as cancel_err:
                                            print(f"        ⚠️ Cancel error: {cancel_err}")
                                    else:
                                        # Price hasn't changed much, skip duplicate submission
                                        print(f"        ⏭️ SKIP: pending LIMIT order already exists for {sym} at similar price")
                                        continue
                        except Exception as pending_err:
                            print(f"        ⚠️ Error checking pending intents: {pending_err}")
                            # Continue anyway - fail open


                    # === SHORT_MOMENTUM_15M_GATE ===
                    # Non elimina gli SHORT: li rende coerenti col timeframe 15m.
                    # Se non troviamo la feature nel payload AI, non blocchiamo (fail-open).
                    try:
                        if action == "OPEN_SHORT":
                            gate_min_conf = float(os.getenv("SHORT_GATE_MIN_CONFIDENCE", "75"))
                            gate_allow_if_missing = os.getenv("SHORT_GATE_ALLOW_IF_MISSING_15M", "true").lower() == "true"

                            # Prova a recuperare una metrica 15m (nomi possibili)
                            v15 = None
                            for k in ("return_15m", "ret_15m", "momentum_15m", "mom_15m", "chg_15m"):
                                if k in d and d.get(k) is not None:
                                    try:
                                        v15 = float(d.get(k))
                                        break
                                    except Exception:
                                        pass

                            conf = float(d.get("confidence", 0) or 0)

                            # Se abbiamo v15: richiedi v15 < 0 per SHORT "normale"
                            if v15 is not None and v15 >= 0:
                                if conf < gate_min_conf:
                                    print(f"        🧭 GATE SHORT {sym}: 15m not bearish (v15={v15:+.4f}) and confidence {conf:.1f} < {gate_min_conf} → HOLD")
                                    continue
                            # Se NON abbiamo v15, opzionalmente blocca gli short a conf bassa
                            if v15 is None and not gate_allow_if_missing and conf < gate_min_conf:
                                print(f"        🧭 GATE SHORT {sym}: missing 15m momentum and confidence {conf:.1f} < {gate_min_conf} → HOLD")
                                continue
                    except Exception as _gate_e:
                        print(f"        ⚠️ SHORT gate error (non-blocking): {_gate_e}")
                    # Guardrail: respect AI blocked_by if present (prevents pointless opens)
                    blocked_by = d.get("blocked_by") or []
                    if blocked_by:
                        print(f"        🧯 SKIP {action} on {sym}: blocked_by={blocked_by}")
                        continue

                    # Guardrail: local backoff to prevent spam retries when PM reports cooldown
                    bk_key = (sym.upper(), desired_side)
                    until = OPEN_BACKOFF_UNTIL.get(bk_key)
                    now = datetime.now()
                    if until and now < until:
                        remaining = int((until - now).total_seconds())
                        print(f"        🧯 SKIP {action} on {sym}: local backoff active for {remaining}s")
                        continue
                    try:
                        existing = None
                        for p0 in (open_positions or []):
                            if (p0.get('symbol') or '').upper() != sym.upper():
                                continue
                            qty = 0.0
                            for k in ('contracts','size','positionAmt','qty'):
                                try:
                                    v = p0.get(k)
                                    if v is None:
                                        continue
                                    qty = float(v)
                                    break
                                except Exception:
                                    pass
                            if abs(qty) > 0:
                                existing = p0
                                break
                        
                        if existing is not None:
                            ex_side = (existing.get('side') or '').lower()
                            
                            if not HEDGE_MODE and not ALLOW_SCALE_IN:
                                # Default: block any new position on same symbol (one-way mode, no scale-in)
                                print(
                                    f"        🧯 SKIP {action} on {sym}: existing open position detected in one-way mode "
                                    f"(existing_side={ex_side or 'unknown'}). Preventing flip/churn."
                                )
                                continue
                            elif ALLOW_SCALE_IN and ex_side == desired_side:
                                # Scale-in allowed: check if we're at max pending entries for this symbol+side
                                try:
                                    pending_resp = await c.get(f"{URLS['pos']}/get_pending_intents")
                                    if pending_resp.status_code == 200:
                                        pending_data = pending_resp.json()
                                        pending_intents = pending_data.get('intents', [])
                                        
                                        # Count pending entries for this symbol+side
                                        count = sum(1 for intent in pending_intents 
                                                   if intent.get('symbol', '').upper() == sym.upper() 
                                                   and intent.get('side', '').lower() == desired_side
                                                   and intent.get('status') == 'PENDING')
                                        
                                        if count >= MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE:
                                            print(f"        🧯 SKIP {action} on {sym}: max pending entries ({count}/{MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE}) reached for scale-in")
                                            continue
                                        else:
                                            print(f"        ✅ Scale-in allowed: {count}/{MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE} pending entries for {sym} {desired_side}")
                                except Exception as scale_err:
                                    print(f"        ⚠️ Could not check scale-in limit: {scale_err}, proceeding conservatively")
                                    continue
                            elif not HEDGE_MODE and ex_side != desired_side:
                                # One-way mode: block opposite direction
                                print(
                                    f"        🧯 SKIP {action} on {sym}: existing {ex_side} position in one-way mode "
                                    f"(cannot flip to {desired_side})"
                                )
                                continue
                    except Exception as e:
                        print(f"        ⚠️ Could not evaluate existing position for {sym}: {e}")

                    # Get AI-provided params with fallback to conservative defaults
                    leverage = d.get('leverage', MIN_LEVERAGE)
                    size_pct = d.get('size_pct', MIN_SIZE_PCT)
                    
                    # Validate params (warns but does NOT modify - trusts AI)
                    leverage, size_pct, had_warnings = validate_ai_params(leverage, size_pct, sym)
                    
                    # Extract scalping parameters from AI decision
                    tp_pct = d.get('tp_pct')  # Optional
                    sl_pct = d.get('sl_pct')  # Optional
                    time_in_trade_limit_sec = d.get('time_in_trade_limit_sec')  # Optional
                    cooldown_sec = d.get('cooldown_sec')  # Optional
                    trail_activation_roi = d.get('trail_activation_roi')  # Optional
                    
                    # --- Anti-churn floors (ETH/SOL) ---
                    # Many losses come from frequent time-exit cycles on SOL/ETH.
                    # Enforce minimum holding time + cooldown so we don't fee-grind.
                    sym_u = sym.upper()
                    if sym_u == "ETHUSDT":
                        min_time = int(os.getenv("MIN_TIME_IN_TRADE_SEC_ETH", "2400"))
                        min_cd = int(os.getenv("MIN_COOLDOWN_SEC_ETH", "1200"))
                        if time_in_trade_limit_sec is None or int(time_in_trade_limit_sec) < min_time:
                            time_in_trade_limit_sec = min_time
                        if cooldown_sec is None or int(cooldown_sec) < min_cd:
                            cooldown_sec = min_cd
                    elif sym_u == "SOLUSDT":
                        min_time = int(os.getenv("MIN_TIME_IN_TRADE_SEC_SOL", "3000"))
                        min_cd = int(os.getenv("MIN_COOLDOWN_SEC_SOL", "1800"))
                        if time_in_trade_limit_sec is None or int(time_in_trade_limit_sec) < min_time:
                            time_in_trade_limit_sec = min_time
                        if cooldown_sec is None or int(cooldown_sec) < min_cd:
                            cooldown_sec = min_cd
                    
                    # === VERIFICATION SAFETY GATES ===
                    # Apply deterministic safety checks before executing OPEN
                    from verification import verify_decision
                    
                    # Build decision dict for verification
                    decision_to_verify = {
                        "symbol": sym,
                        "action": action,
                        "leverage": leverage,
                        "size_pct": size_pct,
                        "entry_type": d.get('entry_type', 'MARKET'),
                        "entry_price": d.get('entry_price'),
                        "entry_ttl_sec": d.get('entry_expires_sec', 240),
                        "tp_pct": tp_pct,
                        "sl_pct": sl_pct
                    }
                    
                    # Get enhanced data for this symbol
                    enhanced_data = assets_data.get(sym, {}).get("enhanced", {})
                    direction = "LONG" if action == "OPEN_LONG" else "SHORT"
                    confluence_data = enhanced_data.get("confluence", {}).get(direction.lower(), {})
                    
                    verification_enhanced = {
                        "confluence_score": confluence_data.get("score", 50),
                        "volatility_bucket": enhanced_data.get("volatility_bucket", "MEDIUM"),
                        "regime": enhanced_data.get("regime", "UNKNOWN")
                    }
                    
                    # Get tech data for verification
                    tech_data_for_verification = assets_data.get(sym, {}).get("tech", {})
                    
                    # Run verification
                    verification_result = verify_decision(
                        decision_to_verify,
                        tech_data_for_verification,
                        verification_enhanced
                    )
                    
                    # Handle verification outcome
                    if verification_result.action == "BLOCK":
                        print(f"        🚫 BLOCKED {action} on {sym}: {'; '.join(verification_result.reasons)}")
                        continue  # Skip this decision
                    elif verification_result.action == "DEGRADE":
                        print(f"        ⚠️ DEGRADE {action} on {sym}:")
                        for reason in verification_result.reasons:
                            print(f"           - {reason}")
                        # Apply modified parameters
                        modified = verification_result.modified_params
                        leverage = modified.get("leverage", leverage)
                        size_pct = modified.get("size_pct", size_pct)
                        entry_type = modified.get("entry_type", entry_type)
                        entry_price = modified.get("entry_price", entry_price)
                        entry_expires_sec = modified.get("entry_ttl_sec", entry_expires_sec)
                        print(f"           Modified params: leverage={leverage:.1f}x, size_pct={size_pct:.3f}")
                    else:  # ALLOW
                        print(f"        ✅ Safety gates passed for {action} on {sym}")
                    
                    # Generate intent_id for idempotency
                    intent_id = str(uuid.uuid4())
                    
                    print(f"        🔥 EXECUTING {action} on {sym} [intent:{intent_id[:8]}]...")
                    if tp_pct:
                        print(f"           Scalping: TP={tp_pct*100:.1f}%, SL={sl_pct*100:.1f}%, MaxTime={time_in_trade_limit_sec}s")
                    
                    # Extract LIMIT entry parameters if present
                    entry_type = d.get('entry_type', 'MARKET')
                    entry_price = d.get('entry_price')
                    entry_expires_sec = d.get('entry_expires_sec', 240)
                    
                    if entry_type == 'LIMIT':
                        if entry_price and entry_price > 0:
                            print(f"           LIMIT entry: price={entry_price}, expires={entry_expires_sec}s")
                        else:
                            print(f"           ⚠️ LIMIT entry requested but no valid price, will use MARKET")
                    
                    # Build payload with scalping params
                    payload = {
                        "symbol": sym,
                        "side": action,
                        "leverage": leverage,
                        "size_pct": size_pct,
                        "intent_id": intent_id,
                        "features": d  # telemetria: snapshot decision/indicatori
                          # For idempotency
                    }
                    
                    # Add optional scalping params if present
                    if tp_pct is not None:
                        payload["tp_pct"] = tp_pct
                    if sl_pct is not None:
                        payload["sl_pct"] = sl_pct
                    if time_in_trade_limit_sec is not None:
                        payload["time_in_trade_limit_sec"] = time_in_trade_limit_sec
                    if cooldown_sec is not None:
                        payload["cooldown_sec"] = cooldown_sec
                    if trail_activation_roi is not None:
                        payload["trail_activation_roi"] = trail_activation_roi
                    
                    # Add LIMIT entry params if present
                    if entry_type and entry_type != "MARKET":
                        payload["entry_type"] = entry_type
                    if entry_price is not None:
                        payload["entry_price"] = entry_price
                    if entry_expires_sec is not None:
                        payload["entry_ttl_sec"] = entry_expires_sec  # Note: position manager uses entry_ttl_sec
                    
                    res = await c.post(f"{URLS['pos']}/open_position", json=payload)
                    print(f"        ✅ Result: {res.json()}")

        except Exception as e: 
            print(f"        ❌ AI/Exec Error: {e}")

async def main_loop():
    # Startup logging
    print("\n" + "="*80)
    print(" TRADING ORCHESTRATOR - STARTUP CONFIGURATION")
    print("="*80)
    print(f"📊 Symbol Universe: {len(SYMBOLS)} symbols")
    print(f"   Active symbols: {', '.join(SYMBOLS)}")
    if DISABLED_SYMBOLS:
        print(f"   Disabled symbols: {', '.join(DISABLED_SYMBOLS)}")
    print(f"\n🎯 Max Open Positions: {MAX_POSITIONS}")
    print(f"⏱️  Cycle Interval: {CYCLE_INTERVAL}s")
    print(f"🔄 Hedge Mode: {'Enabled' if HEDGE_MODE else 'Disabled'}")
    print(f"📈 Scale-in: {'Enabled' if ALLOW_SCALE_IN else 'Disabled'}")
    if DRY_RUN:
        print(f"🔍 DRY RUN MODE: Actions will be logged but not executed")
    print("="*80 + "\n")
    
    while True:
        await manage_cycle()
        await analysis_cycle()
        await asyncio.sleep(CYCLE_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main_loop())
