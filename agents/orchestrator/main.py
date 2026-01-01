import asyncio, httpx, json, os, uuid
from datetime import datetime
URLS = {
    "tech": "http://01_technical_analyzer:8000",
    "pos": "http://07_position_manager:8000",
    "ai": "http://04_master_ai_agent:8000",
    "learning": "http://10_learning_agent:8000"
}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DISABLED_SYMBOLS = os.getenv("DISABLED_SYMBOLS", "").split(",")  # Comma-separated list of disabled symbols
DISABLED_SYMBOLS = [s.strip() for s in DISABLED_SYMBOLS if s.strip()]  # Clean up empty strings

# --- CONFIGURAZIONE OTTIMIZZAZIONE ---
MAX_POSITIONS = 3  # Numero massimo posizioni contemporanee
REVERSE_THRESHOLD = float(os.getenv("REVERSE_THRESHOLD", "2.0"))  # Percentuale perdita per trigger reverse analysis
CRITICAL_LOSS_PCT_LEV = float(os.getenv("CRITICAL_LOSS_PCT_LEV", "12.0"))  # % perdita (con leva) per trigger gestione critica
CYCLE_INTERVAL = 60  # Secondi tra ogni ciclo di controllo (era 900)
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"  # Se true, logga solo azioni senza eseguirle
CRITICAL_LOSS_PCT_LEV = float(os.getenv("CRITICAL_LOSS_PCT_LEV", "12.0"))  # Soglia perdita % con leva per CRITICAL

# --- CRITICAL CLOSE CONFIRMATION STATE ---
# Tracks pending CLOSE requests per symbol. Format: {symbol: cycle_count}
# Requires 2 consecutive cycles with CLOSE action to execute
pending_critical_closes = {}

# --- COOLDOWN AFTER CLOSE (prevent immediate re-entry) ---
# Tracks last close time per symbol. Format: {symbol: datetime}
last_close_times = {}
COOLDOWN_AFTER_CLOSE_SEC = 300  # 5 minuti di cooldown dopo chiusura
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
                                            json={"symbol": symbol},
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
                                                json={"symbol": symbol},
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
                                            json={"symbol": symbol},
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
                reason="Impossibile ottenere dati tecnici dagli analizzatori. Riprovo al prossimo ciclo."
            )
            return

        # 5. AI DECISION
        print(f"        🤖 DeepSeek: Analizzando {list(assets_data.keys())}...")
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
            
            resp = await async_post_with_retry(c, f"{URLS['ai']}/decide_batch", json_payload={
                    "learning_params": learning_params,
                "global_data": enhanced_global_data,
                "assets_data": assets_data
            }, timeout=120.0)
            
            dec_data = resp.json()
            analysis_text = dec_data.get('analysis', 'No text')
            decisions_list = dec_data.get('decisions', [])

            print(f"        📝 AI Says: {analysis_text}")

            if not decisions_list:
                print("        ℹ️ AI non ha generato ordini")
                return

            # 6. EXECUTION
            for d in decisions_list:
                sym = d['symbol']
                action = d['action']
                rationale = d.get('rationale', '')
                
                if action == "CLOSE":
                    print(f"        🛡️ Ignorato CLOSE su {sym} (Auto-Close Disabled)")
                    continue
                
                # Log HOLD dovuto a margine insufficiente
                if action == "HOLD" and "insufficient" in rationale.lower() and "margin" in rationale.lower():
                    available_for_new = portfolio.get('available_for_new_trades', portfolio.get('available', 0))
                    available_source = portfolio.get('available_source', 'unknown')
                    print(f"        🚫 HOLD on {sym}: {rationale}")
                    print(f"           Wallet: available={available_for_new:.2f} USDT (source: {available_source})")
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
                        if existing is not None and not HEDGE_MODE:
                            ex_side = (existing.get('side') or '').lower()
                            print(
                                f"        🧯 SKIP {action} on {sym}: existing open position detected in one-way mode "
                                f"(existing_side={ex_side or 'unknown'}). Preventing flip/churn."
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
                    
                    # Generate intent_id for idempotency
                    intent_id = str(uuid.uuid4())
                    
                    print(f"        🔥 EXECUTING {action} on {sym} [intent:{intent_id[:8]}]...")
                    if tp_pct:
                        print(f"           Scalping: TP={tp_pct*100:.1f}%, SL={sl_pct*100:.1f}%, MaxTime={time_in_trade_limit_sec}s")
                    
                    # Build payload with scalping params
                    payload = {
                        "symbol": sym,
                        "side": action,
                        "leverage": leverage,
                        "size_pct": size_pct,
                        "intent_id": intent_id  # For idempotency
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
                    
                    res = await c.post(f"{URLS['pos']}/open_position", json=payload)
                    print(f"        ✅ Result: {res.json()}")

        except Exception as e: 
            print(f"        ❌ AI/Exec Error: {e}")

async def main_loop():
    while True:
        await manage_cycle()
        await analysis_cycle()
        await asyncio.sleep(CYCLE_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main_loop())
