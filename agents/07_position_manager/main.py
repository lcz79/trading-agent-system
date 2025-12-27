import os
import ccxt
import json
import time
import requests
import httpx
import uuid
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from typing import Optional, Any, Dict, Tuple
from fastapi import FastAPI
from pydantic import BaseModel
from threading import Thread, Lock
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from shared.trading_state import get_trading_state, OrderIntent, OrderStatus, PositionMetadata, Cooldown
app = FastAPI()
# =========================================================
# CONFIG
# =========================================================
HISTORY_FILE = os.getenv("HISTORY_FILE", "equity_history.json")
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
IS_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
# Se usi Hedge Mode su Bybit (posizioni long/short contemporanee),
# metti BYBIT_HEDGE_MODE=true. Se non sei sicuro, lascialo false.
HEDGE_MODE = os.getenv("BYBIT_HEDGE_MODE", "false").lower() == "true"
# --- PARAMETRI TRAILING STOP DINAMICO (ATR-BASED) ---
TRAILING_ACTIVATION_PCT = float(os.getenv("TRAILING_ACTIVATION_PCT", "0.01"))  # 1% (leveraged ROI fraction) - more aggressive
ATR_MULTIPLIER_DEFAULT = float(os.getenv("ATR_MULTIPLIER_DEFAULT", "2.5"))
ATR_MULTIPLIERS = {
    "BTC": 2.0,
    "ETH": 2.0,
    "SOL": 3.0,
    "DOGE": 3.5,
    "PEPE": 4.0,
}
TECHNICAL_ANALYZER_URL = os.getenv("TECHNICAL_ANALYZER_URL", "http://01_technical_analyzer:8000").strip()
FALLBACK_TRAILING_PCT = float(os.getenv("FALLBACK_TRAILING_PCT", "0.025"))  # 2.5%
DEFAULT_INITIAL_SL_PCT = float(os.getenv("DEFAULT_INITIAL_SL_PCT", "0.04"))  # 4%
# --- BREAK-EVEN PROTECTION ---
BREAKEVEN_ACTIVATION_PCT = float(os.getenv("BREAKEVEN_ACTIVATION_PCT", "0.02"))  # 2% ROI
BREAKEVEN_MARGIN_PCT = float(os.getenv("BREAKEVEN_MARGIN_PCT", "0.001"))  # 0.1% margin
# --- PARAMETRI AI REVIEW / REVERSE ---
ENABLE_AI_REVIEW = os.getenv("ENABLE_AI_REVIEW", "true").lower() == "true"
MASTER_AI_URL = os.getenv("MASTER_AI_URL", "http://04_master_ai_agent:8000").strip()
WARNING_THRESHOLD = float(os.getenv("WARNING_THRESHOLD", "-0.10"))
AI_REVIEW_THRESHOLD = float(os.getenv("AI_REVIEW_THRESHOLD", "-0.10"))  # -8% triggers AI review
REVERSE_THRESHOLD = float(os.getenv("REVERSE_THRESHOLD", "-0.15"))  # -10% triggers reverse consideration
HARD_STOP_THRESHOLD = float(os.getenv("HARD_STOP_THRESHOLD", "-0.25"))  # -20% triggers immediate close
REVERSE_COOLDOWN_MINUTES = int(os.getenv("REVERSE_COOLDOWN_MINUTES", "30"))
REVERSE_LEVERAGE = float(os.getenv("REVERSE_LEVERAGE", "5.0"))
reverse_cooldown_tracker: Dict[str, float] = {}
# --- COOLDOWN CONFIGURATION ---
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "5"))
COOLDOWN_FILE = os.getenv("COOLDOWN_FILE", "/data/closed_cooldown.json")
# --- SCALPING CONFIGURATION ---
# Default time in trade limit for scalping mode (20-60 minutes)
DEFAULT_TIME_IN_TRADE_LIMIT_SEC = int(os.getenv("DEFAULT_TIME_IN_TRADE_LIMIT_SEC", "2400"))  # 40 minutes default
# --- AI DECISIONS FILE ---
AI_DECISIONS_FILE = os.getenv("AI_DECISIONS_FILE", "/data/ai_decisions.json")
# --- TRAILING STATE FILE (prevents SL regression) ---
TRAILING_STATE_FILE = os.getenv("TRAILING_STATE_FILE", "/data/trailing_state.json")
# --- LEARNING AGENT ---
LEARNING_AGENT_URL = os.getenv("LEARNING_AGENT_URL", "http://10_learning_agent:8000").strip()
DEFAULT_SIZE_PCT = float(os.getenv("DEFAULT_SIZE_PCT", "0.15"))
# --- DEBUG CONFIGURATION ---
# Comma-separated list of symbols to show detailed debug logs (e.g., "BTCUSDT,ETHUSDT")
DEBUG_SYMBOLS = [s.strip() for s in os.getenv("DEBUG_SYMBOLS", "BTCUSDT").split(",") if s.strip()]
file_lock = Lock()
# =========================================================
# HELPERS
# =========================================================
def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
def to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "" or s.lower() == "none":
            return default
        return float(s)
    except Exception:
        return default
def extract_usdt_coin_data_from_bybit(balance_response: dict) -> Optional[dict]:
    """
    Estrae i dati coin-level USDT dalla risposta raw Bybit.
    Per account UNIFIED, parse info.result.list[0].coin per trovare USDT.
    
    Returns dict con: walletBalance, equity, totalPositionIM, totalOrderIM, locked, availableToWithdraw
    o None se non trovato.
    """
    try:
        info = balance_response.get("info", {})
        if not info:
            return None
        
        result = info.get("result", {})
        if not result:
            return None
        
        # In UNIFIED account: result.list[0] contiene l'account, poi result.list[0].coin[] contiene le coin
        account_list = result.get("list", [])
        if not account_list or not isinstance(account_list, list):
            return None
        
        # Primo account (dovrebbe essere l'account UNIFIED)
        account = account_list[0] if len(account_list) > 0 else {}
        
        # Cerca coin USDT
        coins = account.get("coin", [])
        if not coins or not isinstance(coins, list):
            return None
        
        for coin in coins:
            if coin.get("coin") == "USDT":
                return {
                    "walletBalance": to_float(coin.get("walletBalance"), 0.0),
                    "equity": to_float(coin.get("equity"), 0.0),
                    "totalPositionIM": to_float(coin.get("totalPositionIM"), 0.0),
                    "totalOrderIM": to_float(coin.get("totalOrderIM"), 0.0),
                    "locked": to_float(coin.get("locked"), 0.0),
                    "availableToWithdraw": to_float(coin.get("availableToWithdraw"), 0.0),
                }
        
        return None
    except Exception as e:
        print(f"⚠️ Errore parsing Bybit raw data: {e}")
        return None
def symbol_base(symbol: str) -> str:
    """
    Estrae l'asset base: "BTC" da:
    - "BTC/USDT:USDT"
    - "BTC/USDT"
    - "BTCUSDT"
    """
    s = str(symbol).strip()
    if ":" in s:
        s = s.split(":")[0]
    s = s.replace("/", "")
    s = s.replace("USDT", "")
    return s.upper()
def bybit_symbol_id(symbol: str) -> str:
    """
    Converte in formato Bybit id: "BTCUSDT"
    """
    s = str(symbol).strip()
    if ":" in s:
        s = s.split(":")[0]
    s = s.replace("/", "")
    s = s.upper()
    if not s.endswith("USDT"):
        # se ci arriva "BTC", aggiungiamo USDT
        s = f"{s}USDT"
    return s
def ccxt_symbol_from_id(exchange_obj, sym_id: str) -> Optional[str]:
    """
    Trova il simbolo CCXT (tipo "BTC/USDT:USDT") a partire dall'id (tipo "BTCUSDT")
    """
    try:
        for m in exchange_obj.markets.values():
            if m.get("id") == sym_id and m.get("linear", False):
                return m.get("symbol")
    except Exception:
        pass
    return None
def normalize_position_side(side_raw: str) -> Optional[str]:
    """
    Normalizza verso 'long' / 'short'
    """
    s = (side_raw or "").lower().strip()
    if s in ("long", "buy"):
        return "long"
    if s in ("short", "sell"):
        return "short"
    return None
def side_to_order_side(direction: str) -> str:
    """
    'long' -> 'buy'
    'short' -> 'sell'
    """
    return "buy" if direction == "long" else "sell"
def direction_to_position_idx(direction: str) -> int:
    """
    Bybit Hedge Mode:
      long  -> positionIdx 1
      short -> positionIdx 2
    One-way:
      0
    """
    if not HEDGE_MODE:
        return 0
    return 1 if direction == "long" else 2
def get_position_idx_from_position(p: dict) -> int:
    """
    Se Bybit/CCXT riporta positionIdx in info, usalo.
    Altrimenti usa la modalità HEDGE_MODE.
    """
    info = p.get("info", {}) or {}
    idx = info.get("positionIdx", None)
    idx_f = int(to_float(idx, 0))
    if idx_f in (0, 1, 2):
        return idx_f
    side_dir = normalize_position_side(p.get("side", ""))
    if side_dir:
        return direction_to_position_idx(side_dir)
    return 0
# =========================================================
# JSON MEMORY (thread-safe)
# =========================================================
def load_json(path: str, default=None):
    if default is None:
        default = []
    with file_lock:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                return default
        return default
def save_json(path: str, data):
    ensure_parent_dir(path)
    with file_lock:
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
def _load_trailing_state() -> dict:
    s = load_json(TRAILING_STATE_FILE, default={})
    return s if isinstance(s, dict) else {}
def _save_trailing_state(state: dict) -> None:
    if isinstance(state, dict):
        save_json(TRAILING_STATE_FILE, state)
# =========================================================
# PROFIT-LOCK (AGGRESSIVE TRAILING AFTER STABILITY)
# =========================================================
PROFIT_LOCK_STATE_FILE = os.getenv("PROFIT_LOCK_STATE_FILE", "/data/profit_lock_state.json")
PROFIT_LOCK_CONFIRM_SECONDS = int(os.getenv("PROFIT_LOCK_CONFIRM_SECONDS", "90"))
# ROI values here are "leveraged ROI fraction" (e.g. 0.018 = 1.8% lev ROI)
PROFIT_LOCK_ARM_ROI = float(os.getenv("PROFIT_LOCK_ARM_ROI", "0.018"))
PROFIT_LOCK_MAX_BACKSTEP_ROI = float(os.getenv("PROFIT_LOCK_MAX_BACKSTEP_ROI", "0.003"))
# When profit-lock is confirmed, tighten the ATR multiplier to protect more profit
ATR_MULTIPLIER_AGGRESSIVE = float(os.getenv("ATR_MULTIPLIER_AGGRESSIVE", "1.2"))
def _load_profit_lock_state() -> dict:
    try:
        if os.path.exists(PROFIT_LOCK_STATE_FILE):
            with open(PROFIT_LOCK_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ Could not load profit-lock state: {e}")
    return {}
def _save_profit_lock_state(state: dict) -> None:
    try:
        ensure_parent_dir(PROFIT_LOCK_STATE_FILE)
        with open(PROFIT_LOCK_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
    except Exception as e:
        print(f"⚠️ Could not save profit-lock state: {e}")
def _trailing_key(symbol: str, side_dir: str, position_idx: int) -> str:
    return f"{bybit_symbol_id(symbol)}|{side_dir}|{int(position_idx)}"
# =========================================================
# EXCHANGE SETUP
# =========================================================
exchange = None
if API_KEY and API_SECRET:
    try:
        exchange = ccxt.bybit({
            "apiKey": API_KEY,
            "secret": API_SECRET,
            "options": {
                "defaultType": "swap",
                "adjustForTimeDifference": True,
            },
        })
        if IS_TESTNET:
            exchange.set_sandbox_mode(True)
        exchange.load_markets()
        print(f"🔌 Position Manager: Connesso (Testnet: {IS_TESTNET}) | HedgeMode: {HEDGE_MODE}")
    except Exception as e:
        print(f"⚠️ Errore Connessione: {e}")
else:
    print("⚠️ BYBIT_API_KEY/BYBIT_API_SECRET mancanti: exchange non inizializzato")
# =========================================================
# BACKGROUND: STATE CLEANUP LOOP
# =========================================================
def state_cleanup_loop():
    """
    Background loop that cleans up old intents and expired cooldowns every hour.
    This prevents unbounded growth of trading_state.json.
    """
    # Wait 5 minutes on startup
    time.sleep(300)
    print("🧹 State cleanup loop started - cleaning every hour")
    
    while True:
        try:
            trading_state = get_trading_state()
            
            # Clean up intents older than 6 hours (TTL)
            trading_state.cleanup_old_intents(days=0.25)  # 6 hours = 0.25 days
            
            # Clean up expired cooldowns
            trading_state.cleanup_expired_cooldowns()
            
            print("🧹 State cleanup completed")
        except Exception as e:
            print(f"⚠️ State cleanup error: {e}")
        
        # Run every hour
        time.sleep(3600)
Thread(target=state_cleanup_loop, daemon=True).start()
# =========================================================
# BACKGROUND: EQUITY HISTORY LOOP
# =========================================================
def record_equity_loop():
    while True:
        if exchange:
            try:
                bal = exchange.fetch_balance(params={"type": "swap"})
                usdt = bal.get("USDT", {}) or {}
                real_bal = to_float(usdt.get("total", 0), 0.0)
                pos = exchange.fetch_positions(None, params={"category": "linear"})
                upnl = sum([to_float(p.get("unrealizedPnl"), 0.0) for p in pos])
                hist = load_json(HISTORY_FILE, default=[])
                hist.append({
                    "timestamp": datetime.now().isoformat(),
                    "real_balance": real_bal,
                    "live_equity": real_bal + upnl,
                })
                if len(hist) > 4000:
                    hist = hist[-4000:]
                save_json(HISTORY_FILE, hist)
            except Exception:
                pass
        time.sleep(60)
Thread(target=record_equity_loop, daemon=True).start()
# =========================================================
# BACKGROUND: POSITION MONITORING LOOP (TRAILING + REVERSE + TIME-BASED EXIT)
# =========================================================
def check_time_based_exits():
    """
    Check for positions that have exceeded their time_in_trade_limit and close them.
    This implements the scalping time-based exit feature.
    """
    try:
        trading_state = get_trading_state()
        expired_positions = trading_state.get_expired_positions()
        
        if not expired_positions:
            return
        
        print(f"⏰ Found {len(expired_positions)} expired positions")
        
        for pos_metadata in expired_positions:
            symbol = pos_metadata.symbol
            direction = pos_metadata.direction
            time_in_trade = pos_metadata.time_in_trade_seconds()
            limit_sec = pos_metadata.time_in_trade_limit_sec
            
            print(f"⏰ TIME-BASED EXIT: {symbol} {direction} - in trade for {time_in_trade}s (limit: {limit_sec}s)")
            
            # Close the position
            success = execute_close_position(symbol)
            
            if success:
                print(f"✅ Time-based exit executed for {symbol} {direction}")
                # Record this to learning agent with specific reason
                try:
                    requests.post(
                        f"{LEARNING_AGENT_URL}/record_event",
                        json={
                            "event_type": "time_based_exit",
                            "symbol": symbol,
                            "direction": direction,
                            "time_in_trade_sec": time_in_trade,
                            "limit_sec": limit_sec,
                            "reason": "Position exceeded max holding time (scalping mode)"
                        },
                        timeout=5.0
                    )
                except Exception as e:
                    print(f"⚠️ Failed to record time-based exit to learning agent: {e}")
            else:
                print(f"❌ Failed to execute time-based exit for {symbol} {direction}")
                
    except Exception as e:
        print(f"⚠️ Error in check_time_based_exits: {e}")
def position_monitor_loop():
    """
    Background loop that monitors positions every 30 seconds.
    This ensures trailing stops, reverse logic, and time-based exits run independently
    of orchestrator calls, preventing issues with timeouts or failures.
    """
    # Wait 10 seconds on startup to allow exchange to initialize
    time.sleep(10)
    print("🔄 Position monitor loop started - checking every 30s")
    
    while True:
        if exchange:
            try:
                check_recent_closes_and_save_cooldown()
                check_and_update_trailing_stops()
                check_smart_reverse()
                check_time_based_exits()  # NEW: Check for time-based exits
            except Exception as e:
                print(f"⚠️ Position monitor loop error: {e}")
        
        time.sleep(30)
Thread(target=position_monitor_loop, daemon=True).start()
# =========================================================
# MODELS
# =========================================================
class OrderRequest(BaseModel):
    symbol: str
    side: str = "buy"          # buy/sell/long/short
    leverage: float = 1.0
    size_pct: float = 0.0      # frazione del free USDT (es. 0.15)
    sl_pct: float = 0.0        # frazione (es. 0.04)
    # Scalping parameters (optional)
    intent_id: Optional[str] = None  # For idempotency
    tp_pct: Optional[float] = None   # Take profit percentage
    time_in_trade_limit_sec: Optional[int] = None  # Max holding time
    cooldown_sec: Optional[int] = None  # Cooldown after close
    trail_activation_roi: Optional[float] = None  # ROI threshold for trailing
class CloseRequest(BaseModel):
    symbol: str
class ReverseRequest(BaseModel):
    symbol: str
    recovery_size_pct: float = 0.25
# =========================================================
# LEARNING AGENT
# =========================================================
def record_closed_trade(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    pnl_pct: float,
    leverage: float,
    size_pct: float,
    duration_minutes: int,
    market_conditions: Optional[dict] = None
):
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(
                f"{LEARNING_AGENT_URL}/record_trade",
                json={
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol,
                    "side": side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "leverage": leverage,
                    "size_pct": size_pct,
                    "duration_minutes": duration_minutes,
                    "market_conditions": market_conditions or {},
                },
            )
            if r.status_code == 200:
                print(f"📚 Trade recorded for learning: {symbol} {side} PnL={pnl_pct:.2f}%")
    except Exception as e:
        print(f"⚠️ Failed to record trade for learning: {e}")
def record_trade_for_learning(
    symbol: str,
    side_raw: str,
    entry_price: float,
    exit_price: float,
    leverage: float,
    duration_minutes: int,
    market_conditions: Optional[dict] = None
):
    try:
        side_dir = normalize_position_side(side_raw) or "long"
        asset = symbol_base(symbol)
        pnl_raw = 0.0
        if entry_price > 0:
            if side_dir == "long":
                pnl_raw = (exit_price - entry_price) / entry_price
            else:
                pnl_raw = (entry_price - exit_price) / entry_price
        pnl_pct = pnl_raw * leverage * 100.0
        record_closed_trade(
            symbol=asset,
            side=side_dir,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=pnl_pct,
            leverage=leverage,
            size_pct=DEFAULT_SIZE_PCT,
            duration_minutes=duration_minutes,
            market_conditions=market_conditions or {},
        )
    except Exception as e:
        print(f"⚠️ Errore in record_trade_for_learning: {e}")
# =========================================================
# ATR FUNCTIONS
# =========================================================
def get_atr_for_symbol(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    try:
        clean_id = bybit_symbol_id(symbol)  # BTCUSDT
        with httpx.Client(timeout=5.0) as client:
            r = client.post(f"{TECHNICAL_ANALYZER_URL}/analyze_multi_tf", json={"symbol": clean_id})
            if r.status_code == 200:
                d = r.json()
                # FIX: estrarre da timeframes.15m
                tf_15m = d.get("timeframes", {}).get("15m", {})
                atr = tf_15m.get("atr")
                price = tf_15m.get("price")
                if atr and price:
                    return float(atr), float(price)
    except Exception:
        pass
    return None, None
def get_trailing_distance_pct(symbol: str, mark_price: float, aggressive: bool = False) -> float:
    atr, price = get_atr_for_symbol(symbol)
    if atr and price and price > 0:
        base = symbol_base(symbol)
        if aggressive:
            mult = float(ATR_MULTIPLIER_AGGRESSIVE)
        else:
            mult = float(ATR_MULTIPLIERS.get(base, ATR_MULTIPLIER_DEFAULT))
        pct = min(0.08, max(0.01, (atr * mult) / price))
        mode = "AGGR" if aggressive else "NORM"
        print(f"📊 ATR {symbol}: {atr:.6f}, mult={mult} ({mode}), trailing={pct*100:.2f}%")
        return pct
    print(f"⚠️ ATR unavailable for {symbol}, using fallback {FALLBACK_TRAILING_PCT*100:.2f}%")
    return FALLBACK_TRAILING_PCT
def check_and_update_trailing_stops():
    if not exchange:
        return
    try:
        trailing_state = _load_trailing_state()
        profit_lock_state = _load_profit_lock_state()
        positions = exchange.fetch_positions(None, params={"category": "linear"})
        for p in positions:
            qty = to_float(p.get("contracts"), 0.0)
            if qty == 0:
                continue
            symbol = p.get("symbol", "")
            if not symbol:
                continue
            try:
                market_id = exchange.market(symbol).get("id") or bybit_symbol_id(symbol)
            except Exception:
                market_id = bybit_symbol_id(symbol)
            side_dir = normalize_position_side(p.get("side", ""))
            if not side_dir:
                continue
            entry_price = to_float(p.get("entryPrice"), 0.0)
            mark_price = to_float(p.get("markPrice"), 0.0)
            if entry_price <= 0 or mark_price <= 0:
                continue
            info = p.get("info", {}) or {}
            sl_current = to_float(info.get("stopLoss") or p.get("stopLoss"), 0.0)
            leverage = max(1.0, to_float(p.get("leverage"), 1.0))
            if side_dir == "long":
                roi_raw = (mark_price - entry_price) / entry_price
            else:
                roi_raw = (entry_price - mark_price) / entry_price
            roi = roi_raw * leverage
            # DEBUG: stampa ROI anche quando non scatta (solo BTC)
            try:
                sym_id_dbg = bybit_symbol_id(symbol)
            except Exception:
                sym_id_dbg = str(symbol)
            if sym_id_dbg in DEBUG_SYMBOLS:
                print(
                    f"🧾 TRAIL DEBUG {sym_id_dbg} side={side_dir} "
                    f"entry={entry_price:.2f} mark={mark_price:.2f} lev={leverage:.1f} "
                    f"roi_raw={roi_raw*100:.3f}% roi_lev={roi*100:.3f}% "
                    f"need>={TRAILING_ACTIVATION_PCT*100:.3f}% (lev)"
                )
            position_idx = get_position_idx_from_position(p)
            k_pl = _trailing_key(symbol, side_dir, position_idx)
            # Activation gate
            if roi < TRAILING_ACTIVATION_PCT:
                profit_lock_state.pop(k_pl, None)
                # Log why trailing is not active for debugging
                if sym_id_dbg in DEBUG_SYMBOLS:
                    print(f"   ⏸️ Trailing NOT active: ROI {roi*100:.3f}% < activation threshold {TRAILING_ACTIVATION_PCT*100:.3f}%")
                continue
            # Profit-lock stage logic (B: confirm 90s, max backstep 0.3%, aggressive mult 1.2)
            stage = 1
            if roi >= PROFIT_LOCK_ARM_ROI:
                st_pl = profit_lock_state.get(k_pl, {}) if isinstance(profit_lock_state.get(k_pl, {}), dict) else {}
                armed_at_iso = st_pl.get("armed_at")
                best_roi = to_float(st_pl.get("best_roi"), roi)
                now = datetime.utcnow()
                if not armed_at_iso:
                    st_pl = {
                        "armed_at": now.isoformat(),
                        "best_roi": float(roi),
                        "stage": 1,
                        "updated_at": now.isoformat(),
                    }
                else:
                    best_roi = max(best_roi, roi)
                    try:
                        armed_at = datetime.fromisoformat(armed_at_iso)
                    except Exception:
                        armed_at = now
                    elapsed = (now - armed_at).total_seconds()
                    backstep = max(0.0, best_roi - roi)
                    if elapsed >= PROFIT_LOCK_CONFIRM_SECONDS and backstep <= PROFIT_LOCK_MAX_BACKSTEP_ROI:
                        st_pl["stage"] = 2
                    else:
                        st_pl["stage"] = 1
                    st_pl["best_roi"] = float(best_roi)
                    st_pl["updated_at"] = now.isoformat()
                profit_lock_state[k_pl] = st_pl
                stage = int(to_float(st_pl.get("stage"), 1))
            else:
                profit_lock_state.pop(k_pl, None)
                stage = 1
            if stage == 2:
                print(
                    f"🔒 PROFIT LOCK STAGE 2 {symbol} side={side_dir} "
                    f"roi={roi*100:.2f}% (arm>={PROFIT_LOCK_ARM_ROI*100:.2f}%) "
                    f"confirm={PROFIT_LOCK_CONFIRM_SECONDS}s backstep<={PROFIT_LOCK_MAX_BACKSTEP_ROI*100:.2f}%"
                )
            trailing_distance = get_trailing_distance_pct(symbol, mark_price, aggressive=(stage == 2))
            new_sl_price = None
            if side_dir == "long":
                k = _trailing_key(symbol, side_dir, position_idx)
                st = trailing_state.get(k, {}) if isinstance(trailing_state.get(k, {}), dict) else {}
                peak = to_float(st.get("peak_mark"), 0.0)
                if peak <= 0:
                    peak = mark_price
                peak = max(peak, mark_price)
                trailing_state[k] = {**st, "peak_mark": peak, "updated_at": datetime.utcnow().isoformat()}
                target_sl = peak * (1 - trailing_distance)
                # PROTEZIONE CRITICA: per LONG, SL non deve MAI essere <= entry
                # altrimenti chiuderemmo in perdita o breakeven!
                if target_sl <= entry_price:
                    if sym_id_dbg in DEBUG_SYMBOLS:
                        print(f"⚠️ LONG {symbol}: SL calcolato {target_sl:.2f} <= entry {entry_price:.2f}, skip")
                    continue
                # BREAK-EVEN PROTECTION: se in profitto sufficiente, SL minimo = entry + margine
                if roi >= BREAKEVEN_ACTIVATION_PCT:
                    min_sl = entry_price * (1 + BREAKEVEN_MARGIN_PCT)
                    if target_sl < min_sl:
                        target_sl = min_sl
                        print(f"🛡️ BREAK-EVEN PROTECTION {symbol}: SL alzato a {target_sl:.2f} (entry+margin)")
                last_sl = to_float(st.get("last_sl"), 0.0)
                baseline = max([v for v in (sl_current, last_sl) if v > 0.0], default=0.0)
                hardened = max(target_sl, baseline)
                if baseline == 0.0 or hardened > baseline:
                    new_sl_price = hardened
                    if baseline > 0.0 and hardened > baseline and sym_id_dbg in DEBUG_SYMBOLS:
                        print(f"🔼 LONG SL raising: {baseline:.2f} -> {hardened:.2f} (protecting profit)")
                else:
                    # hardened <= baseline, don't lower SL (would reduce protection)
                    if sym_id_dbg in DEBUG_SYMBOLS:
                        print(f"   ⏸️ LONG SL NOT updated: hardened {hardened:.2f} <= baseline {baseline:.2f} (would reduce protection)")
            else:  # short
                k = _trailing_key(symbol, side_dir, position_idx)
                st = trailing_state.get(k, {}) if isinstance(trailing_state.get(k, {}), dict) else {}
                trough = to_float(st.get("trough_mark"), 0.0)
                if trough <= 0:
                    trough = mark_price
                trough = min(trough, mark_price)
                trailing_state[k] = {**st, "trough_mark": trough, "updated_at": datetime.utcnow().isoformat()}
                target_sl = trough * (1 + trailing_distance)
                # PROTEZIONE CRITICA:  per SHORT, SL non deve MAI essere >= entry
                # altrimenti chiuderemmo in perdita o breakeven!
                if target_sl >= entry_price:
                    if sym_id_dbg in DEBUG_SYMBOLS:
                        print(f"⚠️ SHORT {symbol}: SL calcolato {target_sl:.2f} >= entry {entry_price:.2f}, skip")
                    continue
                # BREAK-EVEN PROTECTION per short
                if roi >= BREAKEVEN_ACTIVATION_PCT:
                    max_sl = entry_price * (1 - BREAKEVEN_MARGIN_PCT)
                    if target_sl > max_sl:
                        target_sl = max_sl
                        print(f"🛡️ BREAK-EVEN PROTECTION {symbol}: SL abbassato a {target_sl:.2f} (entry-margin)")
                last_sl = to_float(st.get("last_sl"), 0.0)
                baseline = min([v for v in (sl_current, last_sl) if v > 0.0], default=0.0)
                
                # For SHORT: SL must be able to LOWER (numerically decrease) to protect profit
                # when price drops. Only update if target_sl is lower than current baseline.
                if baseline == 0.0:
                    # No existing SL - set initial
                    new_sl_price = target_sl
                elif target_sl < baseline:
                    # Price dropped, SL can lower to protect more profit
                    new_sl_price = target_sl
                    if sym_id_dbg in DEBUG_SYMBOLS:
                        print(f"🔽 SHORT SL lowering: {baseline:.2f} -> {target_sl:.2f} (protecting profit)")
                else:
                    # target_sl >= baseline, don't raise SL (would reduce protection)
                    if sym_id_dbg in DEBUG_SYMBOLS:
                        print(f"   ⏸️ SHORT SL NOT updated: target_sl {target_sl:.2f} >= baseline {baseline:.2f} (would reduce protection)")
            if not new_sl_price:
                continue
            price_str = exchange.price_to_precision(symbol, new_sl_price)
            k = _trailing_key(symbol, side_dir, position_idx)
            st = trailing_state.get(k, {}) if isinstance(trailing_state.get(k, {}), dict) else {}
            trailing_state[k] = {**st, "last_sl": float(new_sl_price), "updated_at": datetime.utcnow().isoformat()}
            print(
                f"🏃 TRAILING STOP {symbol} side={side_dir} ROI={roi*100:.2f}% "
                f"entry={entry_price:.4f} mark={mark_price:.4f} "
                f"SL(cur={sl_current}) -> {price_str} (dist={trailing_distance*100:.2f}%) idx={position_idx}"
            )
            try:
                req = {
                    "category": "linear",
                    "symbol": market_id,
                    "tpslMode": "Full",
                    "stopLoss": price_str,
                    "positionIdx": position_idx,
                }
                exchange.private_post_v5_position_trading_stop(req)
                print("✅ SL Aggiornato con successo su Bybit")
            except Exception as api_err:
                print(f"❌ Errore API Bybit (trading_stop): {api_err}")
        _save_trailing_state(trailing_state)
        _save_profit_lock_state(profit_lock_state)
    except Exception as e:
        print(f"⚠️ Trailing logic error: {e}")
def save_ai_decision(decision_data: dict):
    try:
        ensure_parent_dir(AI_DECISIONS_FILE)
        decisions = load_json(AI_DECISIONS_FILE, default=[])
        decisions.append({
            "timestamp": datetime.now().isoformat(),
            "symbol": decision_data.get("symbol"),
            "action": decision_data.get("action"),
            "leverage": decision_data.get("leverage", 0),
            "size_pct": decision_data.get("size_pct", 0),
            "rationale": decision_data.get("rationale", ""),
            "analysis_summary": decision_data.get("analysis_summary", ""),
            "roi_pct": decision_data.get("roi_pct", 0),
            "source": "position_manager",
        })
        decisions = decisions[-100:]
        save_json(AI_DECISIONS_FILE, decisions)
    except Exception as e:
        print(f"⚠️ Error saving AI decision: {e}")
def request_reverse_analysis(symbol: str, position_data: dict) -> Optional[dict]:
    try:
        sym_id = bybit_symbol_id(symbol)
        response = requests.post(
            f"{MASTER_AI_URL}/analyze_reverse",
            json={
                "symbol": sym_id,
                "current_position": position_data,
            },
            timeout=30,
        )
        if response.status_code == 200:
            return response.json()
        print(f"⚠️ Reverse analysis failed: HTTP {response.status_code}")
        return None
    except requests.exceptions.Timeout:
        print(f"⚠️ Reverse analysis timeout for {symbol}")
        return None
    except Exception as e:
        print(f"⚠️ Reverse analysis error: {e}")
        return None
# =========================================================
# CLOSE / REVERSE EXECUTION
# =========================================================
def execute_close_position(symbol: str) -> bool:
    if not exchange:
        return False
    try:
        # accetta sia CCXT symbol sia id
        sym_id = bybit_symbol_id(symbol)
        sym_ccxt = ccxt_symbol_from_id(exchange, sym_id) or symbol
        positions = exchange.fetch_positions([sym_ccxt], params={"category": "linear"})
        position = None
        for p in positions:
            if to_float(p.get("contracts"), 0.0) > 0:
                position = p
                break
        if not position:
            print(f"⚠️ Nessuna posizione aperta per {symbol}")
            return False
        entry_price = to_float(position.get("entryPrice"), 0.0)
        mark_price = to_float(position.get("markPrice"), entry_price)
        leverage = max(1.0, to_float(position.get("leverage"), 1.0))
        side_dir = normalize_position_side(position.get("side", "")) or "long"
        position_idx = get_position_idx_from_position(position)
        if entry_price > 0:
            pnl_raw = (mark_price - entry_price) / entry_price if side_dir == "long" else (entry_price - mark_price) / entry_price
        else:
            pnl_raw = 0.0
        pnl_pct = pnl_raw * leverage * 100.0
        size = to_float(position.get("contracts"), 0.0)
        close_side = "sell" if side_dir == "long" else "buy"
        print(f"🔒 Chiudo posizione {sym_ccxt}: {side_dir} size={size} idx={position_idx}")
        params = {"category": "linear", "reduceOnly": True}
        if HEDGE_MODE:
            params["positionIdx"] = position_idx
        exchange.create_order(sym_ccxt, "market", close_side, size, params=params)
        record_trade_for_learning(
            symbol=sym_id,
            side_raw=side_dir,
            entry_price=entry_price,
            exit_price=mark_price,
            leverage=leverage,
            duration_minutes=0,
            market_conditions={},
        )
        # Use trading_state for cooldown management
        try:
            trading_state = get_trading_state()
            
            # Get position metadata to determine cooldown duration
            pos_metadata = trading_state.get_position(sym_id, side_dir)
            # Use cooldown from metadata if available, otherwise use default
            if pos_metadata and pos_metadata.cooldown_sec:
                cooldown_sec = pos_metadata.cooldown_sec
            else:
                cooldown_sec = COOLDOWN_MINUTES * 60
            
            # Add cooldown to trading_state
            cooldown = Cooldown(
                symbol=sym_id,
                direction=side_dir,
                closed_at=datetime.now().isoformat(),
                reason="Position closed",
                cooldown_sec=cooldown_sec
            )
            trading_state.add_cooldown(cooldown)
            
            # Remove position metadata
            trading_state.remove_position(sym_id, side_dir)
            
            # Also remove trailing stop state if exists
            trading_state.remove_trailing_stop(sym_id, side_dir)
            
            print(f"💾 Cooldown saved for {sym_id} {side_dir} ({cooldown_sec}s)")
        except Exception as e:
            print(f"⚠️ Errore aggiornamento trading_state: {e}")
            # Fallback to old cooldown file for backwards compatibility
            try:
                ensure_parent_dir(COOLDOWN_FILE)
                cooldowns = load_json(COOLDOWN_FILE, default={})
                direction_key = f"{sym_id}_{side_dir}"
                now_ts = time.time()
                cooldowns[direction_key] = now_ts
                cooldowns[sym_id] = now_ts
                save_json(COOLDOWN_FILE, cooldowns)
            except Exception as e2:
                print(f"⚠️ Errore salvataggio cooldown fallback: {e2}")
        print(f"✅ Posizione {sym_ccxt} chiusa con successo | PnL={pnl_pct:.2f}%")
        return True
    except Exception as e:
        print(f"❌ Errore chiusura posizione {symbol}: {e}")
        return False
def execute_reverse(symbol: str, current_side_raw: str, recovery_size_pct: float) -> bool:
    if not exchange:
        return False
    try:
        sym_id = bybit_symbol_id(symbol)
        sym_ccxt = ccxt_symbol_from_id(exchange, sym_id) or symbol
        current_dir = normalize_position_side(current_side_raw) or "long"
        new_dir = "short" if current_dir == "long" else "long"
        new_side = side_to_order_side(new_dir)
        # chiudi prima
        if not execute_close_position(sym_ccxt):
            return False
        time.sleep(1)
        bal = exchange.fetch_balance(params={"type": "swap"})
        free_balance = to_float((bal.get("USDT", {}) or {}).get("free", 0.0), 0.0)
        price = to_float(exchange.fetch_ticker(sym_ccxt).get("last"), 0.0)
        if price <= 0:
            print("❌ Prezzo non valido per reverse")
            return False
        cost = max(free_balance * recovery_size_pct, 10.0)
        leverage = REVERSE_LEVERAGE
        target_market = exchange.market(sym_ccxt)
        info = target_market.get("info", {}) or {}
        lot_filter = info.get("lotSizeFilter", {}) or {}
        qty_step = to_float(lot_filter.get("qtyStep") or (target_market.get("limits", {}).get("amount", {}) or {}).get("min"), 0.001)
        min_qty = to_float(lot_filter.get("minOrderQty") or qty_step, qty_step)
        qty_raw = (cost * leverage) / price
        d_qty = Decimal(str(qty_raw))
        d_step = Decimal(str(qty_step))
        steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
        final_qty_d = steps * d_step
        if final_qty_d < Decimal(str(min_qty)):
            final_qty_d = Decimal(str(min_qty))
        final_qty = float("{:f}".format(final_qty_d.normalize()))
        # set leverage
        try:
            exchange.set_leverage(int(leverage), sym_ccxt, params={"category": "linear"})
        except Exception as e:
            print(f"⚠️ Impossibile impostare leva (ccxt): {e}")
        # SL iniziale
        sl_pct = DEFAULT_INITIAL_SL_PCT
        sl_price = price * (1 - sl_pct) if new_dir == "long" else price * (1 + sl_pct)
        sl_str = exchange.price_to_precision(sym_ccxt, sl_price)
        pos_idx = direction_to_position_idx(new_dir)
        print(
            f"🔄 REVERSE {sym_ccxt}: {current_dir} -> {new_dir}, "
            f"size={recovery_size_pct*100:.1f}%, qty={final_qty}, idx={pos_idx}"
        )
        params = {"category": "linear", "stopLoss": sl_str}
        if HEDGE_MODE:
            params["positionIdx"] = pos_idx
        res = exchange.create_order(sym_ccxt, "market", new_side, final_qty, params=params)
        print(f"✅ Reverse eseguito con successo: {res.get('id')}")
        return True
    except Exception as e:
        print(f"❌ Errore durante reverse: {e}")
        return False
# =========================================================
# AUTO-COOLDOWN FROM CLOSED PNL
# =========================================================
def check_recent_closes_and_save_cooldown():
    if not exchange:
        return
    try:
        res = exchange.private_get_v5_position_closed_pnl({
            "category": "linear",
            "limit": 20,
        })
        if not res or res.get("retCode") != 0:
            return
        items = (res.get("result", {}) or {}).get("list", []) or []
        current_time = time.time()
        ensure_parent_dir(COOLDOWN_FILE)
        cooldowns = load_json(COOLDOWN_FILE, default={})
        changed = False
        for item in items:
            close_time_ms = int(to_float(item.get("updatedTime"), 0))
            close_time_sec = close_time_ms / 1000.0
            if (current_time - close_time_sec) > 600:
                continue
            symbol_raw = (item.get("symbol") or "").upper()  # es: BTCUSDT
            side = (item.get("side") or "").lower()          # buy/sell
            direction = "long" if side == "buy" else "short"
            direction_key = f"{symbol_raw}_{direction}"
            existing_time = to_float(cooldowns.get(direction_key), 0.0)
            if close_time_sec > existing_time:
                cooldowns[direction_key] = close_time_sec
                cooldowns[symbol_raw] = close_time_sec
                changed = True
                print(f"💾 Cooldown auto-salvato per {direction_key} (chiusura Bybit)")
                # learning record
                try:
                    entry_price = to_float(item.get("avgEntryPrice"), 0.0)
                    exit_price = to_float(item.get("avgExitPrice"), 0.0)
                    leverage = max(1.0, to_float(item.get("leverage"), 1.0))
                    created_time_ms = int(to_float(item.get("createdTime"), close_time_ms))
                    duration_minutes = int((close_time_ms - created_time_ms) / 1000 / 60)
                    record_trade_for_learning(
                        symbol=symbol_raw,
                        side_raw=direction,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        leverage=leverage,
                        duration_minutes=duration_minutes,
                        market_conditions={"closed_by": "bybit_sl_tp"},
                    )
                except Exception as e:
                    print(f"⚠️ Errore recording auto-closed trade: {e}")
        if changed:
            save_json(COOLDOWN_FILE, cooldowns)
    except Exception as e:
        print(f"⚠️ Errore check chiusure recenti: {e}")
# =========================================================
# SMART REVERSE SYSTEM
# =========================================================
def check_smart_reverse():
    if not ENABLE_AI_REVIEW or not exchange:
        return
    try:
        trailing_state = _load_trailing_state()
        positions = exchange.fetch_positions(None, params={"category": "linear"})
        wallet_bal = exchange.fetch_balance(params={"type": "swap"})
        wallet_balance = to_float((wallet_bal.get("USDT", {}) or {}).get("total", 0.0), 0.0)
        if wallet_balance <= 0:
            return
        for p in positions:
            size = to_float(p.get("contracts"), 0.0)
            if size == 0:
                continue
            symbol = p.get("symbol", "")
            entry_price = to_float(p.get("entryPrice"), 0.0)
            mark_price = to_float(p.get("markPrice"), 0.0)
            side_dir = normalize_position_side(p.get("side", ""))  # long/short
            pnl_dollars = to_float(p.get("unrealizedPnl"), 0.0)
            if not symbol or entry_price <= 0 or mark_price <= 0 or not side_dir:
                continue
            leverage = max(1.0, to_float(p.get("leverage"), 1.0))
            roi_raw = (mark_price - entry_price) / entry_price if side_dir == "long" else (entry_price - mark_price) / entry_price
            roi = roi_raw * leverage  # fraction (e.g. -0.12 => -12%)
            sym_id = bybit_symbol_id(symbol)
            if roi <= HARD_STOP_THRESHOLD:
                print(f"🛑 HARD STOP: {symbol} {side_dir.upper()} ROI={roi*100:.2f}% - Chiusura immediata!")
                execute_close_position(symbol)
                continue
            if roi <= REVERSE_THRESHOLD:
                print(f"⚠️ REVERSE THRESHOLD REACHED: {symbol} {side_dir.upper()} ROI={roi*100:.2f}% <= {REVERSE_THRESHOLD*100:.2f}%")
                last_reverse_time = reverse_cooldown_tracker.get(sym_id, 0.0)
                now = time.time()
                if (now - last_reverse_time) < (REVERSE_COOLDOWN_MINUTES * 60):
                    minutes_left = int((REVERSE_COOLDOWN_MINUTES * 60 - (now - last_reverse_time)) / 60)
                    print(f"⏳ Reverse cooldown attivo per {symbol}: {minutes_left} minuti rimanenti")
                    continue
                print(f"⚠️ REVERSE TRIGGER: {symbol} {side_dir.upper()} ROI={roi*100:.2f}% - Chiedo conferma AI...")
                position_data = {
                    "side": side_dir,
                    "entry_price": entry_price,
                    "mark_price": mark_price,
                    "roi_pct": roi,
                    "size": size,
                    "pnl_dollars": pnl_dollars,
                    "leverage": leverage,
                    "wallet_balance": wallet_balance,
                }
                analysis = request_reverse_analysis(symbol, position_data)
                if analysis:
                    action = (analysis.get("action") or "HOLD").upper()
                    rationale = analysis.get("rationale", "No rationale")
                    confidence = to_float(analysis.get("confidence"), 0.0)
                    recovery_size_pct = to_float(analysis.get("recovery_size_pct"), 0.15)
                    print(f"🤖 AI REVERSE DECISION for {symbol}: {action} (confidence: {confidence:.0f}%)")
                    print(f"   Rationale: {rationale}")
                    save_ai_decision({
                        "symbol": sym_id,
                        "action": action,
                        "rationale": rationale,
                        "analysis_summary": f"REVERSE TRIGGER | ROI: {roi*100:.2f}% | Confidence: {confidence:.0f}%",
                        "roi_pct": roi * 100,
                        "leverage": leverage,
                        "size_pct": (recovery_size_pct * 100) if action == "REVERSE" else 0,
                    })
                    if action == "REVERSE":
                        print(f"🔄 Eseguo REVERSE per {symbol} con size {recovery_size_pct*100:.1f}%")
                        if execute_reverse(symbol, side_dir, recovery_size_pct):
                            reverse_cooldown_tracker[sym_id] = now
                    elif action == "CLOSE":
                        print(f"🔒 Eseguo CLOSE per {symbol}")
                        execute_close_position(symbol)
                    else:
                        print(f"✋ HOLD - Mantengo posizione {symbol}")
                else:
                    # FALLBACK: AI non disponibile - implementa sicurezza
                    if roi <= HARD_STOP_THRESHOLD:
                        print(f"🛑 AI non disponibile + perdita critica ({roi*100:.2f}% <= {HARD_STOP_THRESHOLD*100:.2f}%) - CHIUSURA DI SICUREZZA per {symbol}")
                        execute_close_position(symbol)
                    else:
                        print(f"⚠️ AI non disponibile per {symbol} (ROI: {roi*100:.2f}%) - Mantengo posizione ma continuo monitoraggio")
                continue
            if roi <= AI_REVIEW_THRESHOLD:
                print(f"🔍 AI REVIEW: {symbol} {side_dir.upper()} ROI={roi*100:.2f}% <= {AI_REVIEW_THRESHOLD*100:.2f}% - Chiedo consiglio AI...")
                position_data = {
                    "side": side_dir,
                    "entry_price": entry_price,
                    "mark_price": mark_price,
                    "roi_pct": roi,
                    "size": size,
                    "pnl_dollars": pnl_dollars,
                    "leverage": leverage,
                    "wallet_balance": wallet_balance,
                }
                analysis = request_reverse_analysis(symbol, position_data)
                if analysis:
                    action = (analysis.get("action") or "HOLD").upper()
                    rationale = analysis.get("rationale", "No rationale")
                    confidence = to_float(analysis.get("confidence"), 0.0)
                    print(f"📊 AI RACCOMANDA: {action}")
                    print(f"   Rationale: {rationale}")
                    save_ai_decision({
                        "symbol": sym_id,
                        "action": action,
                        "rationale": rationale,
                        "analysis_summary": f"AI REVIEW | ROI: {roi*100:.2f}% | Confidence: {confidence:.0f}%",
                        "roi_pct": roi * 100,
                        "leverage": leverage,
                        "size_pct": 0,
                    })
                    # Esegui l'azione raccomandata dall'AI
                    if action == "REVERSE":
                        recovery_size_pct = to_float(analysis.get("size_pct"), 0.5)
                        print(f"🔄 Eseguo REVERSE per {symbol} con size {recovery_size_pct*100:.1f}%")
                        if execute_reverse(symbol, side_dir, recovery_size_pct):
                            reverse_cooldown_tracker[sym_id] = now
                    elif action == "CLOSE": 
                        print(f"🔒 Eseguo CLOSE per {symbol}")
                        execute_close_position(symbol)
                    else:
                        print(f"✋ HOLD - Mantengo posizione {symbol}")
                else:
                    print(f"⚠️ Analisi AI fallita per {symbol}")
                continue
            if roi <= WARNING_THRESHOLD:
                print(f"⚠️ WARNING: {symbol} {side_dir.upper()} ROI={roi*100:.2f}% - Perdita moderata")
    except Exception as e:
        print(f"⚠️ Smart Reverse system error: {e}")
# =========================================================
# API ENDPOINTS
# =========================================================
@app.get("/get_wallet_balance")
def get_balance():
    """
    Ritorna bilancio wallet con supporto Bybit UNIFIED accounts.
    
    Quando USDT.free è None/missing (tipico in UNIFIED), calcola available_for_new_trades
    usando i dati raw Bybit: walletBalance - totalPositionIM - totalOrderIM - locked - buffer.
    """
    if not exchange:
        return {
            "equity": 0,
            "available": 0,
            "available_for_new_trades": 0,
            "available_source": "no_exchange",
            "components": {}
        }
    
    try:
        bal = exchange.fetch_balance(params={"type": "swap"})
        u = bal.get("USDT", {}) or {}
        
        equity = to_float(u.get("total"), 0.0)
        available = to_float(u.get("free"), 0.0)
        
        # Buffer per sicurezza (evita margin call)
        buffer = 10.0
        
        # Caso normale: USDT.free è disponibile e valido
        if available > 0:
            available_for_new_trades = max(0.0, available - buffer)
            return {
                "equity": equity,
                "available": available,
                "available_for_new_trades": available_for_new_trades,
                "available_source": "ccxt_free",
                "components": {
                    "buffer": buffer,
                    "free": available
                }
            }
        
        # Caso UNIFIED: USDT.free è None/0 ma total > 0
        # Proviamo a estrarre dati raw Bybit
        if equity > 0:
            usdt_coin_data = extract_usdt_coin_data_from_bybit(bal)
            
            if usdt_coin_data:
                wallet_balance = usdt_coin_data.get("walletBalance", 0.0)
                total_position_im = usdt_coin_data.get("totalPositionIM", 0.0)
                total_order_im = usdt_coin_data.get("totalOrderIM", 0.0)
                locked = usdt_coin_data.get("locked", 0.0)
                
                # Calcola disponibile per nuovi trade
                # Formula: walletBalance - totalPositionIM - totalOrderIM - locked - buffer
                derived_available = wallet_balance - total_position_im - total_order_im - locked - buffer
                available_for_new_trades = max(0.0, derived_available)
                
                print(f"💰 UNIFIED wallet: equity={equity:.2f}, derived_available={derived_available:.2f}")
                
                return {
                    "equity": equity,
                    "available": available,  # Keep original (may be 0 or None)
                    "available_for_new_trades": available_for_new_trades,
                    "available_source": "bybit_unified_im_derived",
                    "components": {
                        "walletBalance": wallet_balance,
                        "totalPositionIM": total_position_im,
                        "totalOrderIM": total_order_im,
                        "locked": locked,
                        "buffer": buffer,
                        "derived_available": derived_available
                    }
                }
        
        # Fallback: nessun dato disponibile
        return {
            "equity": equity,
            "available": available,
            "available_for_new_trades": 0.0,
            "available_source": "insufficient_data",
            "components": {}
        }
        
    except Exception as e:
        print(f"❌ Errore get_wallet_balance: {e}")
        return {
            "equity": 0,
            "available": 0,
            "available_for_new_trades": 0,
            "available_source": "error",
            "components": {}
        }
@app.get("/get_open_positions")
def get_positions():
    if not exchange:
        return {"active": [], "details": []}
    try:
        raw = exchange.fetch_positions(None, params={"category": "linear"})
        active = []
        details = []
        for p in raw:
            contracts = to_float(p.get("contracts"), 0.0)
            if contracts <= 0:
                continue
            sym_ccxt = p.get("symbol", "")
            sym_id = bybit_symbol_id(sym_ccxt)
            entry_price = to_float(p.get("entryPrice"), 0.0)
            mark_price = to_float(p.get("markPrice"), entry_price)
            leverage = max(1.0, to_float(p.get("leverage"), 1.0))
            side_dir = normalize_position_side(p.get("side", "")) or "long"
            pnl_pct = 0.0
            if entry_price > 0:
                if side_dir == "short":
                    pnl_pct = ((entry_price - mark_price) / entry_price) * leverage * 100.0
                else:
                    pnl_pct = ((mark_price - entry_price) / entry_price) * leverage * 100.0
            details.append({
                "symbol": sym_id,
                "side": side_dir,
                "size": contracts,
                "entry_price": entry_price,
                "mark_price": mark_price,
                "pnl": to_float(p.get("unrealizedPnl"), 0.0),
                "pnl_pct": round(pnl_pct, 2),
                "leverage": leverage,
                "positionIdx": get_position_idx_from_position(p),
            })
            active.append(sym_id)
        return {"active": active, "details": details}
    except Exception:
        return {"active": [], "details": []}
@app.get("/get_history")
def get_hist():
    return load_json(HISTORY_FILE, default=[])
@app.get("/get_closed_positions")
def get_closed():
    if not exchange:
        return []
    try:
        res = exchange.private_get_v5_position_closed_pnl({"category": "linear", "limit": 20})
        if res and res.get("retCode") == 0:
            items = (res.get("result", {}) or {}).get("list", []) or []
            clean = []
            for i in items:
                ts = int(to_float(i.get("updatedTime"), 0))
                clean.append({
                    "datetime": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M"),
                    "symbol": (i.get("symbol") or "").upper(),
                    "side": (i.get("side") or "").lower(),
                    "price": to_float(i.get("avgExitPrice"), 0.0),
                    "closedPnl": to_float(i.get("closedPnl"), 0.0),
                })
            return clean
        return []
    except Exception:
        return []
@app.post("/open_position")
def open_position(order: OrderRequest):
    if not exchange:
        return {"status": "error", "msg": "No Exchange"}
    try:
        # === IDEMPOTENCY CHECK ===
        # If intent_id is provided, check if already processed
        trading_state = get_trading_state()
        intent_id = order.intent_id or str(uuid.uuid4())  # Generate if not provided
        
        existing_intent = trading_state.get_intent(intent_id)
        if existing_intent:
            print(f"💾 IDEMPOTENT: intent_id={intent_id[:8]} already processed")
            return {
                "status": existing_intent.status,
                "msg": "Order already processed (idempotent)",
                "intent_id": intent_id,
                "exchange_order_id": existing_intent.exchange_order_id
            }
        
        # Store intent as PENDING
        raw_sym = str(order.symbol).strip()
        sym_id = bybit_symbol_id(raw_sym)
        is_long_request = ("buy" in order.side.lower()) or ("long" in order.side.lower())
        requested_dir = "long" if is_long_request else "short"
        
        new_intent = OrderIntent(
            intent_id=intent_id,
            symbol=sym_id,
            side=requested_dir,
            action=order.side,
            leverage=order.leverage,
            size_pct=order.size_pct,
            tp_pct=order.tp_pct,
            sl_pct=order.sl_pct,
            time_in_trade_limit_sec=order.time_in_trade_limit_sec,
            cooldown_sec=order.cooldown_sec
        )
        trading_state.add_intent(new_intent)
        print(f"📝 Intent registered: {intent_id[:8]} for {sym_id} {requested_dir}")
        
        # === CONTINUE WITH ORDER EXECUTION ===
        sym_ccxt = ccxt_symbol_from_id(exchange, sym_id) or raw_sym
        requested_side = side_to_order_side(requested_dir)  # buy/sell
        symbol_key = sym_id
        # Check existing position
        try:
            positions = exchange.fetch_positions([sym_ccxt], params={"category": "linear"})
            for p in positions:
                contracts = to_float(p.get("contracts"), 0.0)
                if contracts > 0:
                    existing_dir = normalize_position_side(p.get("side", "")) or "long"
                    if existing_dir == requested_dir:
                        print(f"⚠️ SKIP: già esiste posizione {existing_dir.upper()} su {sym_ccxt}")
                        trading_state.update_intent_status(intent_id, OrderStatus.CANCELLED, 
                                                          error_message="Position already exists")
                        return {
                            "status": "skipped",
                            "msg": f"Posizione {existing_dir} già aperta su {sym_ccxt}",
                            "existing_side": existing_dir,
                            "intent_id": intent_id
                        }
                    else:
                        # Opposite direction requested
                        if not HEDGE_MODE:
                            # In One-Way mode, cannot have opposite direction - must close first
                            print(f"⚠️ ONE-WAY MODE: Cannot open {requested_dir} while {existing_dir} position exists on {sym_ccxt}")
                            trading_state.update_intent_status(intent_id, OrderStatus.CANCELLED, 
                                                              error_message="One-Way mode: close existing position first")
                            return {
                                "status": "rejected",
                                "msg": f"One-Way mode: Cannot open {requested_dir} while {existing_dir} position exists. Close first.",
                                "existing_side": existing_dir,
                                "requested_side": requested_dir,
                                "intent_id": intent_id
                            }
                        else:
                            # Hedge mode: REVERSE is allowed
                            print(f"🔄 HEDGE MODE: REVERSE allowed: {existing_dir} → {requested_dir} su {sym_ccxt}")
        except Exception as e:
            print(f"⚠️ Errore check posizioni esistenti: {e}")
        # Cooldown check using trading_state
        if trading_state.is_in_cooldown(sym_id, requested_dir):
            print(f"⏳ COOLDOWN: {sym_ccxt} {requested_dir} is in cooldown")
            trading_state.update_intent_status(intent_id, OrderStatus.CANCELLED, 
                                              error_message="Cooldown active")
            return {
                "status": "cooldown",
                "msg": f"Cooldown attivo per {sym_ccxt} {requested_dir}",
                "intent_id": intent_id
            }
        # set leverage
        try:
            exchange.set_leverage(int(order.leverage), sym_ccxt, params={"category": "linear"})
        except Exception as e:
            print(f"⚠️ set_leverage fallito (ccxt): {e}")
        bal = exchange.fetch_balance(params={"type": "swap"})
        free_usdt = to_float((bal.get("USDT", {}) or {}).get("free", 0.0), 0.0)
        cost = max(free_usdt * float(order.size_pct), 10.0)
        price = to_float(exchange.fetch_ticker(sym_ccxt).get("last"), 0.0)
        if price <= 0:
            trading_state.update_intent_status(intent_id, OrderStatus.FAILED, 
                                              error_message="Invalid price")
            return {"status": "error", "msg": "Invalid price", "intent_id": intent_id}
        target_market = exchange.market(sym_ccxt)
        info = target_market.get("info", {}) or {}
        lot_filter = info.get("lotSizeFilter", {}) or {}
        qty_step = to_float(lot_filter.get("qtyStep") or (target_market.get("limits", {}).get("amount", {}) or {}).get("min"), 0.001)
        min_qty = to_float(lot_filter.get("minOrderQty") or qty_step, qty_step)
        qty_raw = (cost * float(order.leverage)) / price
        d_qty = Decimal(str(qty_raw))
        d_step = Decimal(str(qty_step))
        steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
        final_qty_d = steps * d_step
        if final_qty_d < Decimal(str(min_qty)):
            final_qty_d = Decimal(str(min_qty))
        final_qty = float("{:f}".format(final_qty_d.normalize()))
        # Use tp_pct if provided, otherwise use sl_pct for SL
        sl_pct = float(order.sl_pct) if order.sl_pct and float(order.sl_pct) > 0 else DEFAULT_INITIAL_SL_PCT
        sl_price = price * (1 - sl_pct) if requested_dir == "long" else price * (1 + sl_pct)
        sl_str = exchange.price_to_precision(sym_ccxt, sl_price)
        
        # Handle tp_pct if provided
        tp_str = None
        if order.tp_pct and float(order.tp_pct) > 0:
            tp_price = price * (1 + order.tp_pct) if requested_dir == "long" else price * (1 - order.tp_pct)
            tp_str = exchange.price_to_precision(sym_ccxt, tp_price)
        pos_idx = direction_to_position_idx(requested_dir)
        # Log scalping parameters
        scalping_info = ""
        if order.time_in_trade_limit_sec:
            scalping_info = f" MaxTime={order.time_in_trade_limit_sec}s"
        print(f"🚀 ORDER {sym_ccxt}: side={requested_side} qty={final_qty} SL={sl_str}" + 
              (f" TP={tp_str}" if tp_str else "") + f" idx={pos_idx}{scalping_info}")
        params = {"category": "linear", "stopLoss": sl_str}
        if tp_str:
            params["takeProfit"] = tp_str
        if HEDGE_MODE:
            params["positionIdx"] = pos_idx
        # Mark intent as EXECUTING
        trading_state.update_intent_status(intent_id, OrderStatus.EXECUTING)
        
        res = exchange.create_order(sym_ccxt, "market", requested_side, final_qty, params=params)
        exchange_order_id = res.get("id")
        
        # Mark intent as EXECUTED
        trading_state.update_intent_status(intent_id, OrderStatus.EXECUTED, 
                                          exchange_order_id=exchange_order_id)
        
        # Store position metadata for time-based exit
        position_metadata = PositionMetadata(
            symbol=sym_id,
            direction=requested_dir,
            opened_at=datetime.now().isoformat(),
            intent_id=intent_id,
            time_in_trade_limit_sec=order.time_in_trade_limit_sec,
            entry_price=price,
            size=final_qty,
            leverage=order.leverage,
            cooldown_sec=order.cooldown_sec
        )
        trading_state.add_position(position_metadata)
        
        print(f"✅ Position opened: {sym_id} {requested_dir} [intent:{intent_id[:8]}]")
        
        return {
            "status": "executed", 
            "id": exchange_order_id,
            "intent_id": intent_id,
            "symbol": sym_id,
            "direction": requested_dir
        }
    except Exception as e:
        print(f"❌ Order Error: {e}")
        # Update intent status to FAILED if we have intent_id
        if 'intent_id' in locals():
            try:
                trading_state = get_trading_state()
                trading_state.update_intent_status(intent_id, OrderStatus.FAILED, 
                                                  error_message=str(e))
            except:
                pass
        return {"status": "error", "msg": str(e), "intent_id": intent_id if 'intent_id' in locals() else None}
@app.post("/close_position")
def close_position(req: CloseRequest):
    # Default SAFE: manual-only. Set POSITION_MANAGER_MANUAL_ONLY=false to allow auto-close.
    manual_only = os.getenv("POSITION_MANAGER_MANUAL_ONLY", "true").lower() == "true"
    if manual_only:
        return {"status": "manual_only"}
    try:
        ok = execute_close_position(req.symbol)
        if ok:
            return {"status": "executed"}
        # execute_close_position ritorna False anche quando NON esiste una posizione.
        # Double-check per distinguere "no_position" da "error".
        sym = req.symbol
        try:
            sym_id = bybit_symbol_id(sym)
            sym_ccxt = ccxt_symbol_from_id(exchange, sym_id) or sym
            positions = exchange.fetch_positions([sym_ccxt], params={"category": "linear"})
            has_pos = any(to_float(p.get("contracts"), 0.0) > 0 for p in positions)
            if not has_pos:
                return {"status": "no_position", "symbol": sym_id}
        except Exception:
            pass
        return {"status": "error", "msg": "close_failed_or_unknown_state"}
    except Exception as e:
        print(f"❌ Close Error: {e}")
        return {"status": "error", "msg": str(e)}
@app.post("/reverse_position")
def reverse_position(req: ReverseRequest):
    # Reverse è opzionale e va abilitato esplicitamente
    enable_reverse = os.getenv("POSITION_MANAGER_ENABLE_REVERSE", "false").lower() == "true"
    if not enable_reverse:
        return {"status": "disabled"}
    manual_only = os.getenv("POSITION_MANAGER_MANUAL_ONLY", "true").lower() == "true"
    if manual_only:
        return {"status": "manual_only"}
    try:
        # Ricava il lato corrente dalla posizione aperta
        sym = req.symbol
        sym_id = bybit_symbol_id(sym)
        sym_ccxt = ccxt_symbol_from_id(exchange, sym_id) or sym
        positions = exchange.fetch_positions([sym_ccxt], params={"category": "linear"})
        position = None
        for p in positions:
            if to_float(p.get("contracts"), 0.0) > 0:
                position = p
                break
        if not position:
            return {"status": "no_position", "symbol": sym_id}
        current_side_raw = position.get("side", "")
        ok = execute_reverse(sym_ccxt, current_side_raw=current_side_raw, recovery_size_pct=float(req.recovery_size_pct))
        if ok:
            return {"status": "executed", "symbol": sym_id}
        return {"status": "error", "msg": "reverse_failed", "symbol": sym_id}
    except Exception as e:
        print(f"❌ Reverse Error: {e}")
        return {"status": "error", "msg": str(e)}
@app.post("/manage_active_positions")
def manage():
    check_recent_closes_and_save_cooldown()
    check_and_update_trailing_stops()
    check_smart_reverse()
    return {"status": "ok"}
