import os
import ccxt
import json
import time
import requests
import httpx
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from typing import Optional, Any, Dict, Tuple
from fastapi import FastAPI
from pydantic import BaseModel
from threading import Thread, Lock

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
TRAILING_ACTIVATION_PCT = float(os.getenv("TRAILING_ACTIVATION_PCT", "0.018"))  # 1.8% (leveraged ROI fraction)
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

WARNING_THRESHOLD = float(os.getenv("WARNING_THRESHOLD", "-0.08"))
AI_REVIEW_THRESHOLD = float(os.getenv("AI_REVIEW_THRESHOLD", "-0.12"))
REVERSE_THRESHOLD = float(os.getenv("REVERSE_THRESHOLD", "-0.15"))
HARD_STOP_THRESHOLD = float(os.getenv("HARD_STOP_THRESHOLD", "-0.20"))

REVERSE_COOLDOWN_MINUTES = int(os.getenv("REVERSE_COOLDOWN_MINUTES", "30"))
REVERSE_LEVERAGE = float(os.getenv("REVERSE_LEVERAGE", "5.0"))
reverse_cooldown_tracker: Dict[str, float] = {}

# --- COOLDOWN CONFIGURATION ---
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "5"))
COOLDOWN_FILE = os.getenv("COOLDOWN_FILE", "/data/closed_cooldown.json")

# --- AI DECISIONS FILE ---
AI_DECISIONS_FILE = os.getenv("AI_DECISIONS_FILE", "/data/ai_decisions.json")

# --- LEARNING AGENT ---
LEARNING_AGENT_URL = os.getenv("LEARNING_AGENT_URL", "http://10_learning_agent:8000").strip()
DEFAULT_SIZE_PCT = float(os.getenv("DEFAULT_SIZE_PCT", "0.15"))

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
# MODELS
# =========================================================
class OrderRequest(BaseModel):
    symbol: str
    side: str = "buy"          # buy/sell/long/short
    leverage: float = 1.0
    size_pct: float = 0.0      # frazione del free USDT (es. 0.15)
    sl_pct: float = 0.0        # frazione (es. 0.04)

class CloseRequest(BaseModel):
    symbol: str

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

def get_trailing_distance_pct(symbol: str, mark_price: float) -> float:
    atr, price = get_atr_for_symbol(symbol)
    if atr and price and price > 0:
        base = symbol_base(symbol)
        mult = float(ATR_MULTIPLIERS.get(base, ATR_MULTIPLIER_DEFAULT))
        pct = min(0.08, max(0.01, (atr * mult) / price))
        print(f"📊 ATR {symbol}: {atr:.6f}, mult={mult}, trailing={pct*100:.2f}%")
        return pct

    print(f"⚠️ ATR unavailable for {symbol}, using fallback {FALLBACK_TRAILING_PCT*100:.2f}%")
    return FALLBACK_TRAILING_PCT

# =========================================================
# TRAILING LOGIC (ATR-BASED)
# =========================================================
def check_and_update_trailing_stops():
    if not exchange:
        return

    try:
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

            if roi < TRAILING_ACTIVATION_PCT:
                continue

            trailing_distance = get_trailing_distance_pct(symbol, mark_price)
            new_sl_price = None

            if side_dir == "long":
                target_sl = mark_price * (1 - trailing_distance)
                
                # BREAK-EVEN PROTECTION: se in profitto sufficiente, SL minimo = entry + margine
                if roi >= BREAKEVEN_ACTIVATION_PCT:
                    min_sl = entry_price * (1 + BREAKEVEN_MARGIN_PCT)
                    if target_sl < min_sl:
                        target_sl = min_sl
                        print(f"🛡️ BREAK-EVEN PROTECTION {symbol}: SL alzato a {target_sl:.2f} (entry+margin)")
                
                if sl_current == 0.0 or target_sl > sl_current:
                    new_sl_price = target_sl
            else:  # short
                target_sl = mark_price * (1 + trailing_distance)
                
                # BREAK-EVEN PROTECTION per short
                if roi >= BREAKEVEN_ACTIVATION_PCT:
                    max_sl = entry_price * (1 - BREAKEVEN_MARGIN_PCT)
                    if target_sl > max_sl:
                        target_sl = max_sl
                        print(f"🛡️ BREAK-EVEN PROTECTION {symbol}: SL abbassato a {target_sl:.2f} (entry-margin)")
                
                if sl_current == 0.0 or target_sl < sl_current:
                    new_sl_price = target_sl

            if not new_sl_price:
                continue

            price_str = exchange.price_to_precision(symbol, new_sl_price)
            position_idx = get_position_idx_from_position(p)

            print(
                f"🏃 TRAILING STOP {symbol} ROI={roi*100:.2f}% "
                f"SL {sl_current} -> {price_str} (dist={trailing_distance*100:.2f}%) idx={position_idx}"
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

    except Exception as e:
        print(f"⚠️ Trailing logic error: {e}")

# =========================================================
# AI DECISIONS PERSISTENCE
# =========================================================
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

        # Cooldown
        try:
            ensure_parent_dir(COOLDOWN_FILE)
            cooldowns = load_json(COOLDOWN_FILE, default={})

            direction_key = f"{sym_id}_{side_dir}"  # long/short
            now_ts = time.time()
            cooldowns[direction_key] = now_ts
            cooldowns[sym_id] = now_ts

            save_json(COOLDOWN_FILE, cooldowns)
            print(f"💾 Cooldown salvato per {direction_key}")
        except Exception as e:
            print(f"⚠️ Errore salvataggio cooldown: {e}")

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
                    print(f"⚠️ Analisi AI fallita per {symbol} - Mantengo posizione")

                continue

            if roi <= AI_REVIEW_THRESHOLD:
                print(f"🔍 AI REVIEW: {symbol} {side_dir.upper()} ROI={roi*100:.2f}% - Chiedo consiglio AI...")

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
                        "rationale":  rationale,
                        "analysis_summary": f"AI REVIEW | ROI:  {roi*100:.2f}% | Confidence: {confidence:.0f}%",
                        "roi_pct":  roi * 100,
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
        # order.symbol può essere id (BTCUSDT) o symbol CCXT (BTC/USDT:USDT)
        raw_sym = str(order.symbol).strip()
        sym_id = bybit_symbol_id(raw_sym)
        sym_ccxt = ccxt_symbol_from_id(exchange, sym_id) or raw_sym

        # Decide side richiesta
        is_long_request = ("buy" in order.side.lower()) or ("long" in order.side.lower())
        requested_dir = "long" if is_long_request else "short"
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
                        return {
                            "status": "skipped",
                            "msg": f"Posizione {existing_dir} già aperta su {sym_ccxt}",
                            "existing_side": existing_dir,
                        }
                    else:
                        print(f"🔄 REVERSE PERMESSO: {existing_dir} → {requested_dir} su {sym_ccxt}")
        except Exception as e:
            print(f"⚠️ Errore check posizioni esistenti: {e}")

        # Cooldown check
        try:
            ensure_parent_dir(COOLDOWN_FILE)
            cooldowns = load_json(COOLDOWN_FILE, default={})
            cooldown_key = f"{symbol_key}_{requested_dir}"  # BTCUSDT_long
            last_close_time = to_float(cooldowns.get(cooldown_key), 0.0)
            elapsed = time.time() - last_close_time

            if elapsed < (COOLDOWN_MINUTES * 60):
                minutes_left = COOLDOWN_MINUTES - (elapsed / 60)
                print(f"⏳ COOLDOWN: {sym_ccxt} {requested_dir} - ancora {minutes_left:.1f} minuti")
                return {
                    "status": "cooldown",
                    "msg": f"Cooldown attivo per {sym_ccxt} {requested_dir}",
                    "minutes_left": round(minutes_left, 1),
                }
        except Exception as e:
            print(f"⚠️ Errore check cooldown: {e}")

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
            return {"status": "error", "msg": "Invalid price"}

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

        sl_pct = float(order.sl_pct) if float(order.sl_pct) > 0 else DEFAULT_INITIAL_SL_PCT
        sl_price = price * (1 - sl_pct) if requested_dir == "long" else price * (1 + sl_pct)
        sl_str = exchange.price_to_precision(sym_ccxt, sl_price)

        pos_idx = direction_to_position_idx(requested_dir)

        print(f"🚀 ORDER {sym_ccxt}: side={requested_side} qty={final_qty} SL={sl_str} idx={pos_idx}")

        params = {"category": "linear", "stopLoss": sl_str}
        if HEDGE_MODE:
            params["positionIdx"] = pos_idx

        res = exchange.create_order(sym_ccxt, "market", requested_side, final_qty, params=params)
        return {"status": "executed", "id": res.get("id")}

    except Exception as e:
        print(f"❌ Order Error: {e}")
        return {"status": "error", "msg": str(e)}

@app.post("/close_position")
def close_position(req: CloseRequest):
    # se vuoi abilitarlo manualmente, puoi chiamare execute_close_position(req.symbol)
    return {"status": "manual_only"}

@app.post("/manage_active_positions")
def manage():
    check_recent_closes_and_save_cooldown()
    check_and_update_trailing_stops()
    check_smart_reverse()
    return {"status": "ok"}
