import os
import ccxt
import json
import time
import requests
import httpx
import uuid
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, Tuple
from fastapi import FastAPI
from pydantic import BaseModel
from threading import Thread, Lock
import sys
from shared.trading_state import get_trading_state, OrderIntent, OrderStatus, PositionMetadata, Cooldown
app = FastAPI()
# =========================================================
# CONFIG
# =========================================================
HISTORY_FILE = os.getenv("HISTORY_FILE", "equity_history.json")

# Exchange Configuration
EXCHANGE_PROVIDER = os.getenv("EXCHANGE", "bybit").lower()
SUPPORTED_EXCHANGES = ["bybit", "hyperliquid"]

# Bybit API Configuration
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
IS_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

# Hyperliquid API Configuration
HYPERLIQUID_API_KEY = os.getenv("HYPERLIQUID_API_KEY")
HYPERLIQUID_API_SECRET = os.getenv("HYPERLIQUID_API_SECRET")
HYPERLIQUID_TESTNET = os.getenv("HYPERLIQUID_TESTNET", "false").lower() == "true"
# Se usi Hedge Mode su Bybit (posizioni long/short contemporanee),
# metti BYBIT_HEDGE_MODE=true. Se non sei sicuro, lascialo false.
HEDGE_MODE = os.getenv("BYBIT_HEDGE_MODE", "false").lower() == "true"
# --- PARAMETRI TRAILING STOP DINAMICO (ATR-BASED) ---
TRAILING_ACTIVATION_RAW_PCT = float(os.getenv("TRAILING_ACTIVATION_RAW_PCT", "0.0010"))  # 0.10% raw (scalping default)
ATR_MULTIPLIER_DEFAULT = float(os.getenv("ATR_MULTIPLIER_DEFAULT", "2.5"))
ATR_MULTIPLIERS = {
    "BTC": 2.6,
    "ETH": 2.8,
    "SOL": 3.4,
    "DOGE": 3.5,
    "PEPE": 4.0,
}
TECHNICAL_ANALYZER_URL = os.getenv("TECHNICAL_ANALYZER_URL", "http://01_technical_analyzer:8000").strip()
FALLBACK_TRAILING_PCT = float(os.getenv("FALLBACK_TRAILING_PCT", "0.0040"))  # 0.40% raw fallback (scalping)
DEFAULT_INITIAL_SL_PCT = float(os.getenv("DEFAULT_INITIAL_SL_PCT", "0.04"))  # 4%

# --- MIN STEP (avoid Bybit "not modified" spam) ---
MIN_SL_MOVE_BTC = float(os.getenv("MIN_SL_MOVE_BTC", "15.0"))
MIN_SL_MOVE_ETH = float(os.getenv("MIN_SL_MOVE_ETH", "0.8"))
MIN_SL_MOVE_SOL = float(os.getenv("MIN_SL_MOVE_SOL", "0.05"))
MIN_SL_MOVE_DEFAULT = float(os.getenv("MIN_SL_MOVE_DEFAULT", "0.001"))
# --- BREAK-EVEN PROTECTION ---
BREAKEVEN_ACTIVATION_RAW_PCT = float(os.getenv("BREAKEVEN_ACTIVATION_RAW_PCT", "0.015"))  # 1.5% ROI (leveraged)
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
# --- STRICT ENTRY TYPE MODE ---
# When enabled, reject orders without explicit entry_type instead of defaulting to MARKET
STRICT_ENTRY_TYPE = os.getenv("STRICT_ENTRY_TYPE", "0") == "1"
# --- SCALPING CONFIGURATION ---
# Default time in trade limit for scalping mode (20-60 minutes)
DEFAULT_TIME_IN_TRADE_LIMIT_SEC = int(os.getenv("DEFAULT_TIME_IN_TRADE_LIMIT_SEC", "7200"))  # 2 hours default - let trades develop
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


def _symbol_base_simple(symbol: str) -> str:
    try:
        sid = bybit_symbol_id(symbol)
    except Exception:
        sid = str(symbol or "")
    sid = sid.upper().replace("/", "").replace(":USDT", "")
    for base in ("BTC", "ETH", "SOL"):
        if sid.startswith(base):
            return base
    return sid.replace("USDT", "").replace("USDC", "")[:10] or sid

def min_sl_move_for_symbol(symbol: str) -> float:
    base = _symbol_base_simple(symbol)
    if base == "BTC":
        return MIN_SL_MOVE_BTC
    if base == "ETH":
        return MIN_SL_MOVE_ETH
    if base == "SOL":
        return MIN_SL_MOVE_SOL
    return MIN_SL_MOVE_DEFAULT

def _truncate_id(id_str: str, length: int = 8) -> str:
    """Safely truncate ID string for logging (handles None and short strings)."""
    if not id_str:
        return "None"
    return id_str[:min(length, len(id_str))]

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
def side_to_order_side(side: str) -> str:
    """
    'long' -> 'buy'
    'short' -> 'sell'
    """
    return "buy" if side == "long" else "sell"
def side_to_position_idx(side: str) -> int:
    """
    Bybit Hedge Mode:
      long  -> positionIdx 1
      short -> positionIdx 2
    One-way:
      0
    """
    if not HEDGE_MODE:
        return 0
    return 1 if side == "long" else 2
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
        return side_to_position_idx(side_dir)
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
# ROI values here are "leveraged ROI fraction" (e.g. 0.06 = 6% lev ROI)
PROFIT_LOCK_ARM_ROI = float(os.getenv("PROFIT_LOCK_ARM_ROI", "0.06"))  # 6% - avoid closing too early
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
# EXCHANGE FACTORY
# =========================================================
def create_exchange(provider: str = None):
    """
    Factory function to create exchange instance based on provider.
    
    Args:
        provider: Exchange provider name (bybit, hyperliquid). 
                  If None, uses EXCHANGE_PROVIDER from env.
    
    Returns:
        ccxt exchange instance or None if configuration is invalid
    
    Raises:
        ValueError: If exchange provider is not supported
    """
    if provider is None:
        provider = EXCHANGE_PROVIDER
    
    provider = provider.lower()
    
    if provider not in SUPPORTED_EXCHANGES:
        raise ValueError(
            f"Unsupported exchange: {provider}. "
            f"Supported exchanges: {', '.join(SUPPORTED_EXCHANGES)}"
        )
    
    try:
        if provider == "bybit":
            if not API_KEY or not API_SECRET:
                print("⚠️ BYBIT_API_KEY/BYBIT_API_SECRET missing: exchange not initialized")
                return None
            
            exchange_instance = ccxt.bybit({
                "apiKey": API_KEY,
                "secret": API_SECRET,
                "options": {
                    "defaultType": "swap",
                    "adjustForTimeDifference": True,
                },
            })
            
            if IS_TESTNET:
                exchange_instance.set_sandbox_mode(True)
            
            exchange_instance.load_markets()
            print(f"🔌 Position Manager: Connected to Bybit (Testnet: {IS_TESTNET}) | HedgeMode: {HEDGE_MODE}")
            return exchange_instance
            
        elif provider == "hyperliquid":
            if not HYPERLIQUID_API_KEY or not HYPERLIQUID_API_SECRET:
                print("⚠️ HYPERLIQUID_API_KEY/HYPERLIQUID_API_SECRET missing: exchange not initialized")
                return None
            
            # TODO: Verify Hyperliquid ccxt integration
            # Note: ccxt.hyperliquid may have different initialization parameters
            # This is a placeholder implementation that should be verified with ccxt documentation
            # before production use. Specifically check:
            # 1. Correct API parameter names (apiKey vs api_key)
            # 2. Testnet/sandbox mode configuration
            # 3. Market loading and symbol format
            exchange_instance = ccxt.hyperliquid({
                "apiKey": HYPERLIQUID_API_KEY,
                "secret": HYPERLIQUID_API_SECRET,
            })
            
            # Hyperliquid may not support sandbox mode the same way
            # Check ccxt documentation for proper testnet setup
            if HYPERLIQUID_TESTNET:
                print("⚠️ Note: Hyperliquid testnet configuration may differ from production")
            
            exchange_instance.load_markets()
            print(f"🔌 Position Manager: Connected to Hyperliquid (Testnet: {HYPERLIQUID_TESTNET})")
            return exchange_instance
            
    except Exception as e:
        print(f"⚠️ Exchange connection error ({provider}): {e}")
        return None

# =========================================================
# EXCHANGE SETUP
# =========================================================
exchange = create_exchange(EXCHANGE_PROVIDER)

if exchange:
    print(f"✅ Exchange initialized: {EXCHANGE_PROVIDER.upper()}")
else:
    print(f"⚠️ Failed to initialize exchange: {EXCHANGE_PROVIDER}")
# =========================================================
# PENDING ENTRY ORDER MANAGEMENT
# =========================================================
def check_pending_entry_orders():
    """
    Check pending LIMIT entry orders and handle their lifecycle:
    - Detect fills and set SL post-fill
    - Cancel expired orders (TTL)
    - Handle cancelled/rejected states
    - Ignore non-entry orders (StopLoss/TP/conditional)
    """
    if not exchange:
        return
    
    try:
        trading_state = get_trading_state()
        
        # Find all pending LIMIT intents
        pending_intents = []
        for intent_id, intent_data in trading_state._state.get("intents", {}).items():
            intent = OrderIntent.from_dict(intent_data)
            if intent.status == OrderStatus.PENDING and intent.entry_type == "LIMIT":
                pending_intents.append(intent)
        
        if not pending_intents:
            return
        
        print(f"📋 Checking {len(pending_intents)} pending LIMIT entry orders")
        
        for intent in pending_intents:
            try:
                sym_id = intent.symbol
                intent_id = intent.intent_id
                
                # Query Bybit v5 for the specific order
                # Try by orderLinkId first (most reliable), fallback to orderId
                order_data = None
                
                # Method 1: Query by orderLinkId (intent_id)
                try:
                    if intent.exchange_order_link_id or intent_id:
                        link_id = intent.exchange_order_link_id or intent_id
                        resp = exchange.private_get_v5_order_realtime({
                            "category": "linear",
                            "orderLinkId": link_id,
                        })
                        
                        if resp and str(resp.get("retCode")) == "0":
                            result = resp.get("result", {}) or {}
                            order_list = result.get("list", [])
                            if order_list:
                                order_data = order_list[0]
                                print(f"   🔍 Found order by orderLinkId: {link_id[:8]}")
                except Exception as e:
                    print(f"   ⚠️ Query by orderLinkId failed for {_truncate_id(intent_id)}: {e}")
                
                # Method 2: Query by orderId if available
                if not order_data and intent.exchange_order_id:
                    try:
                        resp = exchange.private_get_v5_order_realtime({
                            "category": "linear",
                            "orderId": intent.exchange_order_id,
                        })
                        
                        if resp and str(resp.get("retCode")) == "0":
                            result = resp.get("result", {}) or {}
                            order_list = result.get("list", [])
                            if order_list:
                                order_data = order_list[0]
                                print(f"   🔍 Found order by orderId: {intent.exchange_order_id}")
                    except Exception as e:
                        print(f"   ⚠️ Query by orderId failed for {_truncate_id(intent_id)}: {e}")
                
                if not order_data:
                    # === FALLBACK: order not found, but position may be open (Bybit realtime order can disappear) ===
                    try:
                        sym_ccxt_f = ccxt_symbol_from_id(exchange, sym_id) or sym_id
                        pos_list = exchange.fetch_positions([sym_ccxt_f], params={"category": "linear"})
                        # Find matching position with contracts > 0
                        for p in pos_list or []:
                            contracts = to_float(p.get("contracts"), 0.0)
                            if contracts <= 0:
                                continue
                            p_side = normalize_position_side(p.get("side", "")) or "long"
                            if p_side != intent.side:
                                continue
                            entry = to_float(p.get("entryPrice") or (p.get("info", {}) or {}).get("avgPrice"), 0.0)
                            if entry <= 0:
                                entry = to_float(exchange.fetch_ticker(sym_ccxt_f).get("last"), 0.0)
                            sl_pct = intent.sl_pct or compute_entry_sl_pct(sym_id, intent)
                            sl_price = entry * (1 - sl_pct) if p_side == "long" else entry * (1 + sl_pct)
                            sl_str = exchange.price_to_precision(sym_ccxt_f, sl_price)
                            pos_idx = side_to_position_idx(p_side)
                            req = {
                                "category": "linear",
                                "symbol": sym_id,
                                "tpslMode": "Full",
                                "stopLoss": sl_str,
                                "slTriggerBy": "MarkPrice",
                            }
                            if HEDGE_MODE:
                                req["positionIdx"] = pos_idx
                            resp = exchange.private_post_v5_position_trading_stop(req)
                            if isinstance(resp, dict) and str(resp.get("retCode")) == "0":
                                print(f"   ✅ Fallback SL set (order not found): {sym_id} {p_side} SL={sl_str} trigger=MarkPrice")
                                trading_state.update_intent_status(intent_id, OrderStatus.EXECUTED, exchange_order_id=intent.exchange_order_id)
                                position_metadata = PositionMetadata(
                                    symbol=sym_id,
                                    side=p_side,
                                    opened_at=datetime.now().isoformat(),
                                    intent_id=intent_id,
                                    features=intent.features or {},
                                    time_in_trade_limit_sec=intent.time_in_trade_limit_sec,
                                    entry_price=entry,
                                    size=contracts,
                                    leverage=intent.leverage,
                                    cooldown_sec=intent.cooldown_sec,
                                    entry_type=intent.entry_type,
                                )
                                trading_state.add_position(position_metadata)
                            else:
                                print(f"   ⚠️ Fallback SL not set (order not found): resp={resp}")
                            break
                    except Exception as _e:
                        print(f"   ⚠️ Fallback position-check failed for {_truncate_id(intent_id)}: {_e}")

                    print(f"   ⚠️ Order not found for intent {_truncate_id(intent_id)}, may have been filled/cancelled")
                    # Check if expired based on TTL
                    if intent.entry_expires_at:
                        try:
                            expires_at = datetime.fromisoformat(intent.entry_expires_at)
                            if datetime.now() > expires_at:
                                print(f"   ⏰ LIMIT entry expired: {_truncate_id(intent_id)}")
                                trading_state.update_intent_status(
                                    intent_id, 
                                    OrderStatus.CANCELLED,
                                    error_message="LIMIT entry expired (TTL)"
                                )
                        except Exception:
                            pass
                    continue
                
                # Filter out non-entry orders (StopLoss/TP/conditional)
                stop_order_type = order_data.get("stopOrderType", "")
                create_type = order_data.get("createType", "")
                reduce_only = order_data.get("reduceOnly", False)
                
                # Skip if this is a stop-loss or take-profit order
                if stop_order_type and stop_order_type != "":
                    print(f"   ⏭️ Skipping non-entry order (stopOrderType={stop_order_type})")
                    continue
                
                if create_type and "StopLoss" in create_type:
                    print(f"   ⏭️ Skipping SL/TP order (createType={create_type})")
                    continue
                
                if reduce_only:
                    print(f"   ⏭️ Skipping reduceOnly order")
                    continue
                
                # Check order status
                order_status = order_data.get("orderStatus", "")
                
                print(f"   📊 ENTRY ORDER {_truncate_id(intent_id)}: status={order_status}")
                
                # Handle cancelled/rejected/deactivated
                if order_status in ("Cancelled", "Rejected", "Deactivated"):
                    print(f"   ❌ Order {order_status}: {_truncate_id(intent_id)}")
                    trading_state.update_intent_status(
                        intent_id,
                        OrderStatus.CANCELLED,
                        error_message=f"Order {order_status} by exchange"
                    )
                    continue
                
                # Check TTL expiry
                if intent.entry_expires_at:
                    try:
                        expires_at = datetime.fromisoformat(intent.entry_expires_at)
                        if datetime.now() > expires_at:
                            print(f"   ⏰ LIMIT entry expired, cancelling: {_truncate_id(intent_id)}")
                            
                            # Cancel the order
                            try:
                                # Prefer cancel by orderLinkId for reliability
                                cancel_params = {
                                    "category": "linear",
                                    "symbol": sym_id,
                                }
                                
                                if intent.exchange_order_link_id or intent_id:
                                    cancel_params["orderLinkId"] = intent.exchange_order_link_id or intent_id
                                elif intent.exchange_order_id:
                                    cancel_params["orderId"] = intent.exchange_order_id
                                
                                cancel_resp = exchange.private_post_v5_order_cancel(cancel_params)
                                
                                if cancel_resp and str(cancel_resp.get("retCode")) == "0":
                                    print(f"   ✅ Order cancelled successfully: {_truncate_id(intent_id)}")
                                else:
                                    print(f"   ⚠️ Order cancel response: {cancel_resp}")
                            except Exception as e:
                                print(f"   ⚠️ Order cancel failed: {e}")
                            
                            trading_state.update_intent_status(
                                intent_id,
                                OrderStatus.CANCELLED,
                                error_message="LIMIT entry expired (TTL)"
                            )
                            continue
                    except Exception as e:
                        print(f"   ⚠️ TTL check failed: {e}")
                
                # Handle filled order
                if order_status == "Filled":
                    print(f"   ✅ ENTRY ORDER FILLED: {_truncate_id(intent_id)}")
                    
                    # Get fill details
                    avg_price = to_float(order_data.get("avgPrice"), 0.0)
                    cum_exec_qty = to_float(order_data.get("cumExecQty"), 0.0)
                    side = order_data.get("side", "")
                    
                    # Determine position side
                    side_dir = "long" if side.lower() == "buy" else "short"
                    
                    # Now set SL via trading_stop using MarkPrice trigger
                    sl_pct = intent.sl_pct or compute_entry_sl_pct(sym_id, intent)
                    sl_price = avg_price * (1 - sl_pct) if side_dir == "long" else avg_price * (1 + sl_pct)
                    
                    sym_ccxt = ccxt_symbol_from_id(exchange, sym_id) or sym_id
                    sl_str = exchange.price_to_precision(sym_ccxt, sl_price)
                    
                    pos_idx = side_to_position_idx(side_dir)
                    
                    req = {
                        "category": "linear",
                        "symbol": sym_id,
                        "tpslMode": "Full",
                        "stopLoss": sl_str,
                        "slTriggerBy": "MarkPrice",
                    }
                    if HEDGE_MODE:
                        req["positionIdx"] = pos_idx
                    
                    _sl_ok = False
                    _last_err = None
                    for _i, _sleep in enumerate([0.4, 0.8, 1.2, 2.0, 3.0], start=1):
                        try:
                            resp = exchange.private_post_v5_position_trading_stop(req)
                            if isinstance(resp, dict) and str(resp.get("retCode")) == "0":
                                print(f"   ✅ Post-fill SL set: {sym_id} SL={sl_str} trigger=MarkPrice")
                                _sl_ok = True
                                break
                            if isinstance(resp, dict):
                                _last_err = f"retCode={resp.get('retCode')} retMsg={resp.get('retMsg')}"
                            else:
                                _last_err = f"unexpected_response={type(resp).__name__}"
                            print(f"   ⚠️ Post-fill SL rejected (try={_i}): {_last_err}")
                        except Exception as e:
                            _last_err = repr(e)
                            print(f"   ⚠️ Post-fill SL error (try={_i}): {e}")
                        time.sleep(_sleep)
                    
                    if not _sl_ok:
                        print(f"   ❌ CRITICAL: Post-fill SL NOT set for {sym_id}. LastErr={_last_err}")
                        # Emergency close
                        execute_close_position(sym_id, exit_reason="emergency")
                    
                    # Mark intent as EXECUTED
                    trading_state.update_intent_status(
                        intent_id,
                        OrderStatus.EXECUTED,
                        exchange_order_id=intent.exchange_order_id
                    )
                    
                    # Store position metadata
                    position_metadata = PositionMetadata(
                        symbol=sym_id,
                        side=side_dir,
                        opened_at=datetime.now().isoformat(),
                        intent_id=intent_id,
                        features=intent.features or {},
                        time_in_trade_limit_sec=intent.time_in_trade_limit_sec,
                        entry_price=avg_price,
                        size=cum_exec_qty,
                        leverage=intent.leverage,
                        cooldown_sec=intent.cooldown_sec,
                        entry_type=intent.entry_type  # Persist entry_type from intent
                    )
                    trading_state.add_position(position_metadata)
                    
                    print(f"   ✅ Position metadata stored for {sym_id} {side_dir}")
                    continue
                
                # Still pending (New, PartiallyFilled)
                if order_status in ("New", "PartiallyFilled"):
                    print(f"   ⏳ Order still pending: {order_status}")
                    continue
                
            except Exception as e:
                print(f"   ⚠️ Error checking pending intent {intent._truncate_id(intent_id)}: {e}")
                
    except Exception as e:
        print(f"⚠️ Error in check_pending_entry_orders: {e}")

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
            # Prune stale positions from local state (e.g. positions closed on exchange but left in trading_state.json)
            try:
                active_keys = set()
                if exchange:
                    live = exchange.fetch_positions(None, params={"category": "linear"})
                    for p in live:
                        contracts = to_float(p.get("contracts"), 0.0)
                        if contracts <= 0:
                            continue
                        sym = p.get("symbol") or ""
                        side = (p.get("side") or "").lower()
                        if sym and side in ("long", "short"):
                            active_keys.add(f"{sym}_{side}")
                
                # prune_positions now returns dict with removed_keys and removed_positions
                prune_result = trading_state.prune_positions(active_keys)
                removed_keys = prune_result.get("removed_keys", [])
                removed_positions = prune_result.get("removed_positions", [])
                
                if removed_keys:
                    print(f"🧹 Pruned stale positions from trading_state: {removed_keys}")
                    
                    # Persist closed trades before discarding position metadata
                    for pos_data in removed_positions:
                        try:
                            # Create closed trade record
                            closed_trade_record = {
                                "symbol": pos_data.get("symbol"),
                                "side": pos_data.get("side"),
                                "entry_price": pos_data.get("entry_price"),
                                "entry_type": pos_data.get("entry_type"),
                                "opened_at": pos_data.get("opened_at"),
                                "closed_at": datetime.now().isoformat(),
                                "exit_reason": "stale_prune",
                                "intent_id": pos_data.get("intent_id"),
                                "leverage": pos_data.get("leverage"),
                                "size": pos_data.get("size")
                            }
                            
                            # Add to closed_trades
                            trading_state.add_closed_trade(closed_trade_record)
                            print(f"   💾 Persisted closed trade: {pos_data.get('symbol')} {pos_data.get('side')}")
                        except Exception as e:
                            print(f"   ⚠️ Failed to persist closed trade: {e}")
                    
                    # Apply cooldown for each removed position
                    try:
                        for key in removed_keys:
                            if "_" in key:
                                sym, side = key.split("_", 1)
                                if side in ("long", "short"):
                                    _save_cooldown(sym.upper(), side)
                    except Exception as e:
                        print(f"⚠️ Failed to apply cooldown on stale prune: {e}")

            except Exception as e:
                print(f"⚠️ Failed to prune stale positions: {e}")

            
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
    This implements the scalping time-based exit feature with ADX-aware extension.
    
    FASE 2: If ADX > threshold at timeout, extend the position by additional time.
    """
    try:
        trading_state = get_trading_state()
        # NOTE:
        # Do NOT prune positions here before evaluating time-based exits.
        # Pruning here can remove still-open exchange positions from local state, causing desync.
        # Stale position pruning is handled by state_cleanup_loop() using exchange truth.

        expired_positions = trading_state.get_expired_positions()
        
        if not expired_positions:
            return
        
        print(f"⏰ Found {len(expired_positions)} expired positions")
        
        # FASE 2 configuration
        adx_threshold = float(os.getenv("TIME_EXIT_ADX_THRESHOLD", "25.0"))
        extension_time_sec = int(os.getenv("TIME_EXIT_EXTENSION_SEC", "1200"))  # 20 minutes
        
        for pos_metadata in expired_positions:
            symbol = pos_metadata.symbol
            side = pos_metadata.side
            if hasattr(pos_metadata, "time_in_trade_seconds") and callable(getattr(pos_metadata, "time_in_trade_seconds")):
                time_in_trade = int(pos_metadata.time_in_trade_seconds())
            else:
                # Backward compatible: compute from opened_at
                try:
                    opened = datetime.fromisoformat(pos_metadata.opened_at)
                    time_in_trade = int((datetime.utcnow() - opened).total_seconds())
                except Exception:
                    time_in_trade = 0
            limit_sec = pos_metadata.time_in_trade_limit_sec
            
            print(f"⏰ TIME-BASED EXIT CHECK: {symbol} {side} - in trade for {time_in_trade}s (limit: {limit_sec}s)")
            
            # FASE 2: Check ADX to determine if we should extend
            should_extend = False
            adx_value = None
            
            try:
                # Fetch ADX from technical analyzer
                sym_id = bybit_symbol_id(symbol)
                with httpx.Client(timeout=5.0) as client:
                    r = client.post(f"{TECHNICAL_ANALYZER_URL}/analyze_multi_tf", json={"symbol": sym_id})
                    if r.status_code == 200:
                        data = r.json()
                        tf_15m = data.get("timeframes", {}).get("15m", {})
                        adx_value = tf_15m.get("adx")
                        
                        if adx_value is not None and adx_value > adx_threshold:
                            should_extend = True
                            print(f"   📊 ADX={adx_value:.1f} > {adx_threshold} - TREND detected, extending position")
            except Exception as e:
                print(f"   ⚠️ Failed to fetch ADX for {symbol}: {e}")
            
            if should_extend:
                # Extend the position time limit
                try:
                    # Update position metadata with extended time
                    new_limit = limit_sec + extension_time_sec
                    pos_metadata.time_in_trade_limit_sec = new_limit
                    trading_state.add_position(pos_metadata)  # Re-save with updated limit
                    
                    print(f"   ⏱️ Position extended: new limit = {new_limit}s (added {extension_time_sec}s)")
                    
                    # Record extension event
                    try:
                        requests.post(
                            f"{LEARNING_AGENT_URL}/record_event",
                            json={
                                "event_type": "time_exit_extended",
                                "symbol": symbol,
                                "side": side,
                                "time_in_trade_sec": time_in_trade,
                                "original_limit_sec": limit_sec,
                                "new_limit_sec": new_limit,
                                "adx": adx_value,
                                "reason": f"Strong trend (ADX={adx_value:.1f}), extended by {extension_time_sec}s"
                            },
                            timeout=5.0
                        )
                    except Exception as e:
                        print(f"   ⚠️ Failed to record extension event: {e}")
                    
                    # Skip closing this position
                    continue
                    
                except Exception as e:
                    print(f"   ⚠️ Failed to extend position: {e}")
                    # Continue with close if extension fails
            
            # Close the position (either no extension or extension failed)
            # NEW STRATEGY: avoid closing 'flat' (fees kill).
            # At time limit, close ONLY if leveraged ROI is sufficiently positive or sufficiently negative.
            min_profit_lev_pct = float(os.getenv("TIME_EXIT_MIN_PROFIT_ROI_LEV_PCT", "0.8"))
            max_loss_lev_pct = float(os.getenv("TIME_EXIT_MAX_LOSS_ROI_LEV_PCT", "-3.0"))
            max_extensions = int(os.getenv("TIME_EXIT_MAX_EXTENSIONS", "3"))

            # Track extensions on metadata (best-effort)
            extensions_used = int(getattr(pos_metadata, "time_exit_extensions", 0) or 0)
            print(f"   🔁 TIME-EXIT EXTENSIONS {symbol} {side}: used={extensions_used}/{max_extensions} limit_sec={limit_sec}")

            roi_lev_pct = None
            try:
                if exchange:
                    sym_id = bybit_symbol_id(symbol)
                    sym_ccxt = ccxt_symbol_from_id(exchange, sym_id) or symbol
                    positions = exchange.fetch_positions([sym_ccxt], params={"category": "linear"})
                    pos = None
                    for p0 in positions:
                        if to_float(p0.get("contracts"), 0.0) > 0:
                            pos = p0
                            break
                    if pos:
                        entry_price = to_float(pos.get("entryPrice"), 0.0)
                        mark_price = to_float(pos.get("markPrice"), entry_price)
                        leverage = max(1.0, to_float(pos.get("leverage"), 1.0))
                        side_dir = normalize_position_side(pos.get("side", "")) or side
                        if entry_price > 0:
                            roi_raw = (mark_price - entry_price) / entry_price if side_dir == "long" else (entry_price - mark_price) / entry_price
                            roi_lev_pct = roi_raw * leverage * 100.0
            except Exception as e:
                print(f"   ⚠️ Failed to compute ROI for time-exit decision on {symbol}: {e}")

            if roi_lev_pct is not None:
                print(f"   📈 TIME-EXIT ROI CHECK {symbol} {side}: roi_lev={roi_lev_pct:.3f}% (min_profit={min_profit_lev_pct:.3f}%, max_loss={max_loss_lev_pct:.3f}%)")

            # Decide close/extend/hold
            if roi_lev_pct is not None and roi_lev_pct >= min_profit_lev_pct:
                exit_reason = "time_exit_profit"
            elif roi_lev_pct is not None and roi_lev_pct <= max_loss_lev_pct:
                exit_reason = "time_exit_loss"
            else:
                # Not enough profit/loss to justify closing. Prefer extend (once) to avoid fee-driven flat exits.
                if extensions_used < max_extensions:
                    try:
                        new_limit = limit_sec + extension_time_sec
                        pos_metadata.time_in_trade_limit_sec = new_limit
                        setattr(pos_metadata, "time_exit_extensions", extensions_used + 1)
                        trading_state.add_position(pos_metadata)
                        print(f"   ⏱️ Flat ROI - extending position: new limit={new_limit}s (extensions {extensions_used+1}/{max_extensions})")
                        # Record extension event
                        try:
                            requests.post(
                                f"{LEARNING_AGENT_URL}/record_event",
                                json={
                                    "event_type": "time_exit_extended_flat_roi",
                                    "symbol": symbol,
                                    "side": side,
                                    "time_in_trade_sec": time_in_trade,
                                    "original_limit_sec": limit_sec,
                                    "new_limit_sec": new_limit,
                                    "adx": adx_value,
                                    "roi_lev_pct": roi_lev_pct,
                                    "reason": "Flat ROI at time limit; extended to avoid fee-driven exit"
                                },
                                timeout=5.0
                            )
                        except Exception as e:
                            print(f"   ⚠️ Failed to record flat-roi extension event: {e}")
                        continue
                    except Exception as e:
                        print(f"   ⚠️ Failed to extend position on flat ROI: {e}")
                print(f"   🧊 TIME-EXIT HOLD {symbol} {side}: flat ROI and max extensions reached; holding position")
                # Do not close flat
                continue

            print(f"   🔒 Closing position: reason={exit_reason}, ADX={adx_value}, roi_lev_pct={roi_lev_pct}")
            success = execute_close_position(symbol, exit_reason=exit_reason)
            if success:
                print(f"✅ Time-based exit executed for {symbol} {side}")
                try:
                    requests.post(
                        f"{LEARNING_AGENT_URL}/record_event",
                        json={
                            "event_type": "time_based_exit",
                            "symbol": symbol,
                            "side": side,
                            "time_in_trade_sec": time_in_trade,
                            "limit_sec": limit_sec,
                            "exit_reason": exit_reason,
                            "adx": adx_value,
                            "roi_lev_pct": roi_lev_pct,
                            "reason": f"Position exceeded max holding time ({exit_reason})"
                        },
                        timeout=5.0
                    )
                except Exception as e:
                    print(f"⚠️ Failed to record time-based exit to learning agent: {e}")
            else:
                print(f"❌ Failed to execute time-based exit for {symbol} {side}")
                
    except Exception as e:
        print(f"⚠️ Error in check_time_based_exits: {e}")
def position_monitor_loop():
    """
    Background loop that monitors positions every 30 seconds.
    This ensures trailing stops, reverse logic, time-based exits, and pending entry orders
    run independently of orchestrator calls, preventing issues with timeouts or failures.
    """
    # Wait 10 seconds on startup to allow exchange to initialize
    time.sleep(10)
    print("🔄 Position monitor loop started - checking every 30s")
    
    while True:
        if exchange:
            try:
                check_pending_entry_orders()  # Check LIMIT entry orders first
                check_recent_closes_and_save_cooldown()
                check_and_update_trailing_stops()
                check_smart_reverse()
                check_time_based_exits()  # Check for time-based exits
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
    # Entry type configuration
    entry_type: Optional[str] = "MARKET"  # MARKET or LIMIT
    entry_price: Optional[float] = None   # Required for LIMIT orders
    entry_ttl_sec: Optional[int] = None   # Time-to-live for LIMIT orders (default 3600)
    # Scalping parameters (optional)
    intent_id: Optional[str] = None  # For idempotency
    tp_pct: Optional[float] = None   # Take profit percentage
    time_in_trade_limit_sec: Optional[int] = None  # Max holding time
    cooldown_sec: Optional[int] = None  # Cooldown after close
    trail_activation_roi: Optional[float] = None  # ROI threshold for trailing
    features: Optional[dict] = None  # Market features snapshot
class CloseRequest(BaseModel):
    symbol: str
    exit_reason: str = "manual"
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
    market_conditions: Optional[dict] = None,
    intent_id: Optional[str] = None,
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
                    "intent_id": intent_id,
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
    market_conditions: Optional[dict] = None,
    intent_id: Optional[str] = None,
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
            intent_id=intent_id,
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
                # Prefer 4h ATR for less noise (intra-day), fallback to 15m
                tfs = d.get("timeframes", {}) or {}
                tf_4h = tfs.get("4h", {}) or {}
                tf_15m = tfs.get("15m", {}) or {}
                src = tf_4h if (tf_4h.get("atr") and tf_4h.get("price")) else tf_15m
                atr = src.get("atr")
                price = src.get("price")
                if atr and price:
                    return float(atr), float(price)
    except Exception:
        pass
    return None, None
def get_trailing_distance_pct(symbol: str, mark_price: float, leverage: float, aggressive: bool = False) -> float:
    """Return trailing distance as RAW fraction of price (e.g. 0.002 = 0.2%).
    Leverage-aware clamps for scalping: higher leverage => tighter raw trailing.
    """
    atr, price = get_atr_for_symbol(symbol)
    if atr and price and price > 0:
        base = symbol_base(symbol)
        mult = float(ATR_MULTIPLIER_AGGRESSIVE) if aggressive else float(ATR_MULTIPLIERS.get(base, ATR_MULTIPLIER_DEFAULT))
        pct_atr = (float(atr) * float(mult)) / float(price)

        lev = max(1.0, float(leverage))
        if lev <= 3:
            min_pct = float(os.getenv("TRAIL_MIN_PCT_LEV_LE_3", "0.0020"))
            max_pct = float(os.getenv("TRAIL_MAX_PCT_LEV_LE_3", "0.0060"))
        elif lev <= 5:
            min_pct = float(os.getenv("TRAIL_MIN_PCT_LEV_LE_5", "0.0015"))
            max_pct = float(os.getenv("TRAIL_MAX_PCT_LEV_LE_5", "0.0045"))
        elif lev <= 8:
            min_pct = float(os.getenv("TRAIL_MIN_PCT_LEV_LE_8", "0.0012"))
            max_pct = float(os.getenv("TRAIL_MAX_PCT_LEV_LE_8", "0.0035"))
        else:
            min_pct = float(os.getenv("TRAIL_MIN_PCT_LEV_GE_9", "0.0010"))
            max_pct = float(os.getenv("TRAIL_MAX_PCT_LEV_GE_9", "0.0025"))

        if aggressive:
            max_pct *= float(os.getenv("TRAIL_STAGE2_MAX_FACTOR", "0.80"))
            min_pct *= float(os.getenv("TRAIL_STAGE2_MIN_FACTOR", "0.90"))

        pct = min(float(max_pct), max(float(min_pct), float(pct_atr)))
        mode = "AGGR" if aggressive else "NORM"
        print(
            f"📊 ATR {symbol}: atr={atr:.6f} mult={mult} ({mode}) "
            f"pct_atr={pct_atr*100:.2f}% lev={lev:.1f} clamp=[{min_pct*100:.2f}%,{max_pct*100:.2f}%] "
            f"-> trailing={pct*100:.2f}%"
        )
        return float(pct)

    print(f"⚠️ ATR unavailable for {symbol}, using fallback {FALLBACK_TRAILING_PCT*100:.2f}%")
    return float(FALLBACK_TRAILING_PCT)
# =========================================================
# ENTRY STOP LOSS (hard floor + ATR-based)
# =========================================================
ENTRY_SL_USE_ATR = str(os.getenv("ENTRY_SL_USE_ATR", "true")).lower() == "true"
ATR_ENTRY_MULTIPLIER = float(os.getenv("ATR_ENTRY_MULTIPLIER", "2.0"))
ENTRY_SL_MAX_PCT = float(os.getenv("ENTRY_SL_MAX_PCT", "0.02"))  # cap 2%
ENTRY_SL_MIN_PCT_DEFAULT = float(os.getenv("ENTRY_SL_MIN_PCT_DEFAULT", "0.007"))
ENTRY_SL_MIN_PCT_BY_SYMBOL = {
    "ETH": float(os.getenv("ENTRY_SL_MIN_PCT_ETH", "0.007")),
    "SOL": float(os.getenv("ENTRY_SL_MIN_PCT_SOL", "0.009")),
    "BTC": float(os.getenv("ENTRY_SL_MIN_PCT_BTC", "0.006")),
}

def entry_sl_min_pct(symbol: str) -> float:
    base = symbol_base(symbol)
    return float(ENTRY_SL_MIN_PCT_BY_SYMBOL.get(base, ENTRY_SL_MIN_PCT_DEFAULT))

def compute_entry_sl_pct(symbol: str, order) -> float:
    """Compute entry SL percent (0.007 = 0.7%)."""
    hard_floor = entry_sl_min_pct(symbol)

    # Respect explicit order.sl_pct but enforce floor + cap
    try:
        if getattr(order, "sl_pct", None) and float(order.sl_pct) > 0:
            return max(hard_floor, min(float(order.sl_pct), ENTRY_SL_MAX_PCT))
    except Exception:
        pass

    sl_pct = float(DEFAULT_INITIAL_SL_PCT)

    if ENTRY_SL_USE_ATR:
        try:
            atr, atr_price = get_atr_for_symbol(symbol)
            if atr and atr_price and atr_price > 0:
                atr_based = (float(atr) * float(ATR_ENTRY_MULTIPLIER)) / float(atr_price)
                atr_based = min(float(ENTRY_SL_MAX_PCT), max(0.005, atr_based))
                sl_pct = max(sl_pct, atr_based)
                print(
                    f"📊 ENTRY ATR {symbol}: atr={atr:.6f} price={atr_price:.2f} "
                    f"mult={ATR_ENTRY_MULTIPLIER:.2f} -> atr_sl={atr_based*100:.2f}%"
                )
            else:
                print(f"⚠️ ENTRY ATR unavailable for {symbol}, using DEFAULT_INITIAL_SL_PCT")
        except Exception as e:
            print(f"⚠️ ENTRY ATR calc failed for {symbol}: {e}")

    sl_pct = max(hard_floor, sl_pct)
    sl_pct = min(float(ENTRY_SL_MAX_PCT), sl_pct)
    return sl_pct


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
            roi_lev = roi  # alias for leveraged ROI (used by break-even logic)
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
                    f"need>={TRAILING_ACTIVATION_RAW_PCT*100:.3f}% (raw)"
                )
            position_idx = get_position_idx_from_position(p)
            k_pl = _trailing_key(symbol, side_dir, position_idx)
            # Activation gate
            if roi_raw < TRAILING_ACTIVATION_RAW_PCT:
                profit_lock_state.pop(k_pl, None)
                # Log why trailing is not active for debugging
                if sym_id_dbg in DEBUG_SYMBOLS:
                    print(f"   ⏸️ Trailing NOT active: ROI_raw {roi_raw*100:.3f}% < activation threshold {TRAILING_ACTIVATION_RAW_PCT*100:.3f}%")
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
            trailing_distance = get_trailing_distance_pct(symbol, mark_price, leverage, aggressive=(stage == 2))
            new_sl_price = None
            if side_dir == "long":
                k = _trailing_key(symbol, side_dir, position_idx)
                st = trailing_state.get(k, {}) if isinstance(trailing_state.get(k, {}), dict) else {}
                peak = to_float(st.get("peak_mark"), 0.0)
                if peak <= 0:
                    peak = mark_price
                peak = max(peak, mark_price)
                trailing_state[k] = {**st, "peak_mark": peak, "updated_at": datetime.utcnow().isoformat()}
                # --- DWELL-TIME TIGHTENING (LONG) ---
                # Se il prezzo resta vicino al peak per >= TRAIL_TIGHTEN_AFTER_SEC, stringi la distanza trailing a step.
                tighten_after_sec = int(os.getenv("TRAIL_TIGHTEN_AFTER_SEC", "180"))
                tighten_zone_pct = float(os.getenv("TRAIL_TIGHTEN_ZONE_PCT", "0.003"))
                tighten_step = float(os.getenv("TRAIL_TIGHTEN_STEP", "0.85"))
                tighten_min_pct = float(os.getenv("TRAIL_TIGHTEN_MIN_PCT", "0.008"))
                tighten_max_steps = int(os.getenv("TRAIL_TIGHTEN_MAX_STEPS", "4"))

                tighten_since = st.get("tighten_since")
                tighten_level = int(st.get("tighten_level") or 0)

                # "in zona": prezzo rimane molto vicino al massimo (no pullback significativo)
                in_zone = mark_price >= peak * (1 - tighten_zone_pct)

                if in_zone:
                    if not tighten_since:
                        trailing_state[k] = {**trailing_state[k], "tighten_since": datetime.utcnow().isoformat(), "tighten_level": tighten_level}
                    else:
                        try:
                            since_dt = datetime.fromisoformat(tighten_since)
                            dwell_sec = (datetime.utcnow() - since_dt).total_seconds()
                        except Exception:
                            dwell_sec = 0.0

                        if dwell_sec >= tighten_after_sec and tighten_level < tighten_max_steps:
                            # stringi la distanza ma non oltre tighten_min_pct
                            tightened = max(trailing_distance * tighten_step, tighten_min_pct)
                            if tightened < trailing_distance:
                                tighten_level += 1
                                trailing_distance = tightened
                                trailing_state[k] = {**trailing_state[k], "tighten_since": datetime.utcnow().isoformat(), "tighten_level": tighten_level}
                                if sym_id_dbg in DEBUG_SYMBOLS:
                                    print(f"⏱️ TRAIL TIGHTEN LONG {symbol}: dwell>={tighten_after_sec}s near peak, level={tighten_level} dist={trailing_distance*100:.2f}%")
                else:
                    # fuori zona: reset timer (non resettiamo tighten_level)
                    if tighten_since:
                        trailing_state[k] = {**trailing_state[k], "tighten_since": None}
                # Clamp trailing distance (raw) to avoid too-wide stops (never moves) or too-tight stops (stop-out)

                trail_min = float(os.getenv("TRAIL_MIN_DIST_RAW_PCT", "0.010"))

                trail_max = float(os.getenv("TRAIL_MAX_DIST_RAW_PCT", "0.025"))

                trailing_distance = max(trail_min, min(trailing_distance, trail_max))

                target_sl = peak * (1 - trailing_distance)
                # Bybit constraint: LONG stopLoss must stay below last/mark price
                long_min_under_last_pct = float(os.getenv("TRAIL_LONG_MIN_UNDER_LAST_PCT", "0.0015"))
                max_sl_under_last = mark_price * (1 - long_min_under_last_pct)
                target_sl = min(target_sl, max_sl_under_last)
                # PROTEZIONE CRITICA: per LONG, SL non deve MAI essere <= entry
                # altrimenti chiuderemmo in perdita o breakeven!
                # BREAK-EVEN PROTECTION: se in profitto sufficiente, SL minimo = entry + margine
                # --- PROFIT LOCK (leveraged trigger, raw lock) ---
                # Se ROI leveraged >= soglia, blocca un minimo profitto raw sopra entry.
                # --- PROFIT LOCK (raw steps, leverage-independent) ---
                # Steps format: "trigger_raw:lock_raw,trigger_raw:lock_raw,..."
                # Example: "0.015:0.005,0.025:0.010" - less aggressive steps
                steps_raw = os.getenv(
                    "PROFIT_LOCK_RAW_STEPS",
                    "0.015:0.005,0.025:0.010,0.035:0.015,0.045:0.020,0.060:0.030",
                )

                best_lock_raw = None
                try:
                    for part in (steps_raw or "").split(","):
                        part = part.strip()
                        if not part or ":" not in part:
                            continue
                        trig_s, lock_s = part.split(":", 1)
                        trig = float(trig_s.strip())
                        lock = float(lock_s.strip())
                        if roi_raw >= trig:
                            if best_lock_raw is None or lock > best_lock_raw:
                                best_lock_raw = lock
                except Exception as e:
                    if sym_id_dbg in DEBUG_SYMBOLS:
                        print(f"⚠️ PROFIT_LOCK_RAW_STEPS parse error for {symbol}: {e}")

                if best_lock_raw is not None:
                    pl_sl = entry_price * (1 + best_lock_raw)
                    if target_sl < pl_sl:
                        target_sl = pl_sl
                    if sym_id_dbg in DEBUG_SYMBOLS:
                        print(
                            f"🧷 PROFIT LOCK STEP LONG {symbol}: roi_raw={roi_raw*100:.3f}% "
                            f"=> lock_raw={best_lock_raw*100:.3f}% => SL>={target_sl:.2f}"
                        )

                if roi_raw >= BREAKEVEN_ACTIVATION_RAW_PCT:
                    min_sl = entry_price * (1 + BREAKEVEN_MARGIN_PCT)
                    if target_sl < min_sl:
                        target_sl = min_sl
                        print(f"🛡️ BREAK-EVEN PROTECTION {symbol}: SL alzato a {target_sl:.2f} (entry+margin)")
                last_sl = to_float(st.get("last_sl"), 0.0)
                baseline = sl_current if sl_current and sl_current > 0.0 else last_sl
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
                # --- DWELL-TIME TIGHTENING (SHORT) ---
                tighten_after_sec = int(os.getenv("TRAIL_TIGHTEN_AFTER_SEC", "180"))
                tighten_zone_pct = float(os.getenv("TRAIL_TIGHTEN_ZONE_PCT", "0.003"))
                tighten_step = float(os.getenv("TRAIL_TIGHTEN_STEP", "0.85"))
                tighten_min_pct = float(os.getenv("TRAIL_TIGHTEN_MIN_PCT", "0.008"))
                tighten_max_steps = int(os.getenv("TRAIL_TIGHTEN_MAX_STEPS", "4"))

                tighten_since = st.get("tighten_since")
                tighten_level = int(st.get("tighten_level") or 0)

                # "in zona": prezzo rimane vicino al minimo (no bounce significativo)
                in_zone = mark_price <= trough * (1 + tighten_zone_pct)

                if in_zone:
                    if not tighten_since:
                        trailing_state[k] = {**trailing_state[k], "tighten_since": datetime.utcnow().isoformat(), "tighten_level": tighten_level}
                    else:
                        try:
                            since_dt = datetime.fromisoformat(tighten_since)
                            dwell_sec = (datetime.utcnow() - since_dt).total_seconds()
                        except Exception:
                            dwell_sec = 0.0

                        if dwell_sec >= tighten_after_sec and tighten_level < tighten_max_steps:
                            tightened = max(trailing_distance * tighten_step, tighten_min_pct)
                            if tightened < trailing_distance:
                                tighten_level += 1
                                trailing_distance = tightened
                                trailing_state[k] = {**trailing_state[k], "tighten_since": datetime.utcnow().isoformat(), "tighten_level": tighten_level}
                                if sym_id_dbg in DEBUG_SYMBOLS:
                                    print(f"⏱️ TRAIL TIGHTEN SHORT {symbol}: dwell>={tighten_after_sec}s near trough, level={tighten_level} dist={trailing_distance*100:.2f}%")
                else:
                    if tighten_since:
                        trailing_state[k] = {**trailing_state[k], "tighten_since": None}
                # Clamp trailing distance (raw)

                trail_min = float(os.getenv("TRAIL_MIN_DIST_RAW_PCT", "0.010"))

                trail_max = float(os.getenv("TRAIL_MAX_DIST_RAW_PCT", "0.025"))

                trailing_distance = max(trail_min, min(trailing_distance, trail_max))

                target_sl = trough * (1 + trailing_distance)
                # Bybit constraint: SHORT stopLoss must stay above last/mark price
                short_min_over_last_pct = float(os.getenv("TRAIL_SHORT_MIN_OVER_LAST_PCT", "0.0015"))
                min_sl_over_last = mark_price * (1 + short_min_over_last_pct)
                target_sl = max(target_sl, min_sl_over_last)
                # PROTEZIONE CRITICA (SHORT):
                # Evita di impostare uno SL *sotto o uguale* all'entry prima della logica di breakeven/profit-lock.
                # Uno SL sopra entry è normale per una posizione SHORT.
                # BREAK-EVEN PROTECTION per short
                # --- PROFIT LOCK (raw steps, leverage-independent) ---
                steps_raw = os.getenv(
                    "PROFIT_LOCK_RAW_STEPS",
                    "0.015:0.005,0.025:0.010,0.035:0.015,0.045:0.020,0.060:0.030",
                )

                best_lock_raw = None
                try:
                    for part in (steps_raw or "").split(","):
                        part = part.strip()
                        if not part or ":" not in part:
                            continue
                        trig_s, lock_s = part.split(":", 1)
                        trig = float(trig_s.strip())
                        lock = float(lock_s.strip())
                        if roi_raw >= trig:
                            if best_lock_raw is None or lock > best_lock_raw:
                                best_lock_raw = lock
                except Exception as e:
                    if sym_id_dbg in DEBUG_SYMBOLS:
                        print(f"⚠️ PROFIT_LOCK_RAW_STEPS parse error for {symbol}: {e}")

                if best_lock_raw is not None:
                    pl_sl = entry_price * (1 - best_lock_raw)
                    if target_sl > pl_sl:
                        target_sl = pl_sl
                    if sym_id_dbg in DEBUG_SYMBOLS:
                        print(
                            f"🧷 PROFIT LOCK STEP SHORT {symbol}: roi_raw={roi_raw*100:.3f}% "
                            f"=> lock_raw={best_lock_raw*100:.3f}% => SL<={target_sl:.2f}"
                        )

                if roi_raw >= BREAKEVEN_ACTIVATION_RAW_PCT:
                    max_sl = entry_price * (1 - BREAKEVEN_MARGIN_PCT)
                    if target_sl > max_sl:
                        target_sl = max_sl
                        print(f"🛡️ BREAK-EVEN PROTECTION {symbol}: SL abbassato a {target_sl:.2f} (entry-margin)")
                last_sl = to_float(st.get("last_sl"), 0.0)
                baseline = sl_current if sl_current and sl_current > 0.0 else last_sl
                
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
                # Min-step guard to reduce Bybit 'not modified' spam
                baseline_for_step = sl_current if sl_current and sl_current > 0.0 else to_float(st.get("last_sl"), 0.0)
                min_step = float(min_sl_move_for_symbol(symbol))
                if baseline_for_step and baseline_for_step > 0:
                    if abs(float(new_sl_price) - float(baseline_for_step)) < min_step:
                        if sym_id_dbg in DEBUG_SYMBOLS:
                            print(
                                f"🧱 Skip SL update (min-step): {symbol} "
                                f"new={new_sl_price:.4f} baseline={baseline_for_step:.4f} "
                                f"Δ={abs(new_sl_price-baseline_for_step):.4f} < {min_step}"
                            )
                        continue

                # USE_TRAILING_EXIT_ORDER: Bybit does not allow stopLoss for short below MarkPrice.
                # For profit-lock trailing we use a reduce-only conditional StopOrder (Market).
                use_exit = False
                try:
                    if side.lower() == "short" and float(new_sl_price) < float(mark_price):
                        use_exit = True
                    if side.lower() == "long" and float(new_sl_price) > float(mark_price):
                        use_exit = True
                except Exception:
                    use_exit = False

                if use_exit:
                    try:
                        _upsert_trailing_exit_order(
                            exchange,
                            symbol=symbol,
                            position_side=side,
                            position_idx=position_idx,
                            qty=float(size),
                            trigger_price=float(new_sl_price),
                            trigger_by="MarkPrice",
                        )
                    except Exception as e:
                        print(f"⚠️ Trailing-exit order error for {symbol}: {e}")
                    continue

                req = {
                    "category": "linear",
                    "symbol": bybit_symbol_id(symbol),
                    "tpslMode": "Full",
                    "stopLoss": price_str,
                    "slTriggerBy": "MarkPrice",
                    "positionIdx": position_idx,
                }
                resp = exchange.private_post_v5_position_trading_stop(req)
                if isinstance(resp, dict):
                    print(f"✅ SL updated via trading_stop retCode={resp.get('retCode')} retMsg={resp.get('retMsg')}")
                else:
                    print("✅ SL updated via trading_stop")
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
# TRADE LOGGING TO EQUITY HISTORY
# =========================================================
EQUITY_HISTORY_FILE = os.getenv("EQUITY_HISTORY_FILE", "/data/equity_history.json")

def log_trade_to_equity_history(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    pnl_pct: float,
    pnl_dollars: float,
    leverage: float,
    size: float,
    exit_reason: str = "manual"
):
    """
    Log closed trade details to dashboard/data/equity_history.json
    
    This function appends trade data to the equity history file for dashboard visualization
    and analytics. Each trade record includes entry/exit prices, PnL metrics, and metadata.
    """
    try:
# removed debug print
        ensure_parent_dir(EQUITY_HISTORY_FILE)
        
        # Load existing equity history
        equity_data = load_json(EQUITY_HISTORY_FILE, default={"history": []})
        
        # Ensure it has the correct structure
        if not isinstance(equity_data, dict):
            equity_data = {"history": []}
        if "history" not in equity_data:
            equity_data["history"] = []
        
        # Create trade record
        trade_record = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_dollars": round(pnl_dollars, 2),
            "leverage": leverage,
            "size": size,
            "exit_reason": exit_reason,
            "type": "trade"  # Mark as trade entry vs equity snapshot
        }
        
        # Append trade record to history
        equity_data["history"].append(trade_record)
        
        # Keep last 1000 records to prevent file from growing too large
        if len(equity_data["history"]) > 1000:
            equity_data["history"] = equity_data["history"][-1000:]
        
        # Save updated equity history
        save_json(EQUITY_HISTORY_FILE, equity_data)
        
        print(f"💰 Trade logged to equity_history.json: {symbol} {side} PnL={pnl_pct:.2f}%")
        
    except Exception as e:
        print(f"⚠️ Failed to log trade to equity_history.json: {e}")

# =========================================================
# CLOSE / REVERSE EXECUTION
# =========================================================
def execute_close_position(symbol: str, exit_reason: str = "manual") -> bool:
    # POLICY: positions must close ONLY via exchange SL/trailing.
    # Exception: allow software close only for emergency kill switch.
    # Allowed software-driven close reasons.
    # We still keep a policy gate to avoid accidental closes, but critical/risk exits must be permitted.
    allowed = {
        "emergency", "kill_switch",
        "critical", "critical_mgmt_close", "risk", "stop_loss", "sl", "tp", "trail",
        "time_exit", "reverse", "ai", "signal", "cooldown_exit"
    }
    if (exit_reason or "manual") not in allowed:
        print(f"⛔ CLOSE BLOCKED by policy: symbol={symbol} exit_reason={exit_reason}")
        return False

# removed debug print# removed debug print# removed debug print
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
# removed debug print
        params = {"category": "linear", "reduceOnly": True}
        if HEDGE_MODE:
            params["positionIdx"] = position_idx
        exchange.create_order(sym_ccxt, "market", close_side, size, params=params)
        
        # Calculate PnL in dollars (unrealized PnL from position)
        pnl_dollars = to_float(position.get("unrealizedPnl"), 0.0)
        
        # Log trade to equity history
        log_trade_to_equity_history(
            symbol=sym_id,
            side=side_dir,
            entry_price=entry_price,
            exit_price=mark_price,
            pnl_pct=pnl_pct,
            pnl_dollars=pnl_dollars,
            leverage=leverage,
            size=size,
            exit_reason=exit_reason
        )
        
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
            # DEBUG (removed): broken print caused SyntaxError
            # Persist cooldown using TradingState schema (Cooldown expects expires_at)
            _now = datetime.utcnow()
            cooldown = Cooldown(
                symbol=sym_id,
                side=side_dir,
                expires_at=(_now + timedelta(seconds=int(cooldown_sec))).isoformat(),
                reason="position_closed",
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
                side_key = f"{sym_id}_{side_dir}"
                now_ts = time.time()
                cooldowns[side_key] = now_ts
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
        pos_idx = side_to_position_idx(new_dir)
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

def _save_cooldown(symbol_raw: str, side: str, close_time_sec: float | None = None):
    """Save cooldown timestamps to legacy /data/closed_cooldown.json."""
    try:
        ensure_parent_dir(COOLDOWN_FILE)
        cooldowns = load_json(COOLDOWN_FILE, default={})
        ts = float(close_time_sec) if close_time_sec else time.time()
        side_key = f"{symbol_raw}_{side}"
        existing_time = to_float(cooldowns.get(side_key), 0.0)
        if ts > existing_time:
            cooldowns[side_key] = ts
            cooldowns[symbol_raw] = ts
            save_json(COOLDOWN_FILE, cooldowns)
            print(f"[COOLDOWN] saved {side_key} ts={ts}")
    except Exception as e:
        print(f"[COOLDOWN] failed save for {symbol_raw} {side}: {e}")

def check_recent_closes_and_save_cooldown():
    if not exchange:
        return
    try:
        res = exchange.private_get_v5_position_closed_pnl({
            "category": "linear",
            "limit": 20,
        })
        if not res:
            print("closed_pnl: empty response")
            return
        if str(res.get("retCode")) != "0":
            print("closed_pnl retCode=" + str(res.get("retCode")) + " retMsg=" + str(res.get("retMsg")))
            return
        items = (res.get("result", {}) or {}).get("list", []) or []
        print(f"closed_pnl items={len(items)}")
        current_time = time.time()
        ensure_parent_dir(COOLDOWN_FILE)
        cooldowns = load_json(COOLDOWN_FILE, default={})
        changed = False
        for item in items:
            close_time_ms = int(to_float(item.get("updatedTime"), 0))
            close_time_sec = close_time_ms / 1000.0
            if (current_time - close_time_sec) > 7200:
                # debug: too old for window
                # print(f"closed_pnl: skipping old close {symbol_raw} updatedTime={close_time_ms}")
                continue
            symbol_raw = (item.get("symbol") or "").upper()  # es: BTCUSDT
            side = (item.get("side") or "").lower()          # buy/sell
            # closed_pnl.side is the closing order side: Buy closes SHORT, Sell closes LONG
            side = "short" if side == "buy" else "long"
            side_key = f"{symbol_raw}_{side}"
            existing_time = to_float(cooldowns.get(side_key), 0.0)
            if close_time_sec > existing_time:
                cooldowns[side_key] = close_time_sec
                cooldowns[symbol_raw] = close_time_sec
                changed = True
                print(f"💾 Cooldown auto-salvato per {side_key} (chiusura Bybit)")
                # learning record
                try:
                    entry_price = to_float(item.get("avgEntryPrice"), 0.0)
                    exit_price = to_float(item.get("avgExitPrice"), 0.0)
                    leverage = max(1.0, to_float(item.get("leverage"), 1.0))
                    created_time_ms = int(to_float(item.get("createdTime"), close_time_ms))
                    duration_minutes = int((close_time_ms - created_time_ms) / 1000 / 60)
                    # Join con TradingState per recuperare intent_id + feature snapshot dell'entry
                    ts = None
                    pm = None
                    feat = {}
                    try:
                        ts = get_trading_state()
                        pm = ts.get_position(symbol_raw, side)
                    except Exception:
                        ts = None
                        pm = None
                    try:
                        if pm and getattr(pm, 'features', None) and isinstance(pm.features, dict):
                            feat = dict(pm.features)
                    except Exception:
                        feat = {}
                    record_trade_for_learning(
                        symbol=symbol_raw,
                        side_raw=side,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        leverage=leverage,
                        duration_minutes=duration_minutes,
                        market_conditions={**feat, "closed_by": "bybit_sl_tp"},
                        intent_id=(pm.intent_id if pm and getattr(pm, 'intent_id', None) else None),
                    )
                    # Pulizia: rimuovi la posizione dallo state (se presente)
                    try:
                        if ts and pm:
                            ts.remove_position(symbol_raw, side)
                    except Exception:
                        pass
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
        # Get Bybit closed PnL data
        res = exchange.private_get_v5_position_closed_pnl({"category": "linear", "limit": 20})
        if not res or str(res.get("retCode")) != "0":
            return []
        
        bybit_items = (res.get("result", {}) or {}).get("list", []) or []
        
        # Get local closed trades
        trading_state = get_trading_state()
        closed_trades = trading_state.get_closed_trades()
        
        # Process Bybit items and enrich with local data
        enriched = []
        for bybit_item in bybit_items:
            ts_ms = int(to_float(bybit_item.get("updatedTime"), 0))
            if ts_ms == 0:
                continue
            
            ts_sec = ts_ms / 1000.0
            symbol = (bybit_item.get("symbol") or "").upper()
            side_raw = (bybit_item.get("side") or "").lower()  # buy/sell
            
            # Normalize Bybit side to pos_side (buy closes short, sell closes long)
            pos_side = "short" if side_raw == "buy" else "long"
            
            # Base record from Bybit (backward compatible)
            record = {
                "datetime": datetime.fromtimestamp(ts_sec).strftime("%Y-%m-%d %H:%M"),
                "symbol": symbol,
                "side": side_raw,  # Keep original for backward compatibility
                "price": to_float(bybit_item.get("avgExitPrice"), 0.0),
                "closedPnl": to_float(bybit_item.get("closedPnl"), 0.0),
            }
            
            # Try to match with local closed_trades
            # Matching strategy: symbol + pos_side + nearest close time within 12hr window
            best_match = None
            best_match_time_diff = float('inf')
            time_window_sec = 12 * 3600  # 12 hours
            
            for local_trade in closed_trades:
                local_symbol = local_trade.get("symbol", "").upper()
                local_side = local_trade.get("side", "").lower()
                local_closed_at = local_trade.get("closed_at", "")
                
                # Match symbol and pos_side
                if local_symbol != symbol or local_side != pos_side:
                    continue
                
                # Parse local close time
                try:
                    local_closed_dt = datetime.fromisoformat(local_closed_at)
                    local_closed_sec = local_closed_dt.timestamp()
                    time_diff = abs(local_closed_sec - ts_sec)
                    
                    # Within time window and closer than previous best
                    if time_diff <= time_window_sec and time_diff < best_match_time_diff:
                        best_match = local_trade
                        best_match_time_diff = time_diff
                except Exception:
                    continue
            
            # Enrich record with local data if match found
            if best_match:
                record["intent_id"] = best_match.get("intent_id")
                record["entry_type"] = best_match.get("entry_type")
                record["entry_price"] = best_match.get("entry_price")
                record["opened_at"] = best_match.get("opened_at")
                record["exit_reason"] = best_match.get("exit_reason")
                record["closed_at"] = best_match.get("closed_at")
                record["pos_side"] = pos_side  # Add normalized position side
            
            enriched.append(record)
        
        return enriched
    except Exception as e:
        print(f"⚠️ Error in get_closed_positions: {e}")
        return []

@app.get("/get_pending_intents")
def get_pending_intents_endpoint():
    """Returns list of pending order intents (especially LIMIT orders awaiting fill)"""
    try:
        trading_state = get_trading_state()
        pending_intents = []
        
        for intent_id, intent_data in trading_state._state.get("intents", {}).items():
            intent = OrderIntent.from_dict(intent_data)
            if intent.status == OrderStatus.PENDING:
                pending_intents.append({
                    "intent_id": intent.intent_id,
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "entry_type": intent.entry_type,
                    "entry_price": intent.entry_price,
                    "entry_expires_at": intent.entry_expires_at,
                    "status": intent.status.value,
                    "created_at": intent.created_at,
                    "exchange_order_id": intent.exchange_order_id,
                    "exchange_order_link_id": intent.exchange_order_link_id
                })
        
        return {"intents": pending_intents, "count": len(pending_intents)}
    except Exception as e:
        return {"error": str(e), "intents": []}

@app.post("/cancel_intent")
def cancel_intent_endpoint(request: dict):
    """Cancel a pending intent by intent_id"""
    try:
        intent_id = request.get("intent_id")
        if not intent_id:
            return {"status": "error", "msg": "intent_id required"}
        
        trading_state = get_trading_state()
        intent_data = trading_state._state.get("intents", {}).get(intent_id)
        
        if not intent_data:
            return {"status": "error", "msg": f"Intent {intent_id} not found"}
        
        intent = OrderIntent.from_dict(intent_data)
        
        # Only cancel if PENDING
        if intent.status != OrderStatus.PENDING:
            return {"status": "error", "msg": f"Intent {intent_id} is not PENDING (status={intent.status})"}
        
        # Cancel the exchange order if LIMIT entry and we have order IDs
        cancel_success = False
        if exchange and intent.entry_type == "LIMIT":
            # Verify exchange is properly initialized
            try:
                # Quick check that exchange is responsive
                if not hasattr(exchange, 'private_post_v5_order_cancel'):
                    print(f"⚠️ Exchange not properly initialized, cannot cancel order")
                else:
                    symbol_id = bybit_symbol_id(intent.symbol)
                    if intent.exchange_order_link_id:
                        # Cancel by orderLinkId (preferred)
                        exchange.private_post_v5_order_cancel({
                            "category": "linear",
                            "symbol": symbol_id,
                            "orderLinkId": intent.exchange_order_link_id
                        })
                        print(f"✅ Cancelled LIMIT order by orderLinkId: {intent.exchange_order_link_id}")
                        cancel_success = True
                    elif intent.exchange_order_id:
                        # Fallback to orderId
                        exchange.private_post_v5_order_cancel({
                            "category": "linear",
                            "symbol": symbol_id,
                            "orderId": intent.exchange_order_id
                        })
                        print(f"✅ Cancelled LIMIT order by orderId: {intent.exchange_order_id}")
                        cancel_success = True
            except Exception as cancel_err:
                print(f"⚠️ Exchange cancel error: {cancel_err}")
                # Continue to mark intent as cancelled even if exchange call fails
        elif intent.entry_type == "MARKET":
            # MARKET orders typically execute immediately, so PENDING MARKET is rare
            # If we get here, it's likely already executed or failed
            print(f"⚠️ Warning: Attempting to cancel PENDING MARKET order {intent_id}")
        
        # Mark intent as CANCELLED
        trading_state.update_intent_status(
            intent_id,
            OrderStatus.CANCELLED,
            error_message="Cancelled by orchestrator (cancel+replace)"
        )
        
        return {
            "status": "success",
            "msg": f"Intent {intent_id} cancelled",
            "intent_id": intent_id,
            "exchange_cancelled": cancel_success
        }
    except Exception as e:
        print(f"❌ Error cancelling intent: {e}")
        return {"status": "error", "msg": str(e)}
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
            print(f"💾 IDEMPOTENT: intent_id={_truncate_id(intent_id)} already processed")
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
        
        # === STRICT ENTRY TYPE VALIDATION ===
        # When STRICT_ENTRY_TYPE is enabled, reject orders without explicit entry_type
        entry_type = order.entry_type
        if STRICT_ENTRY_TYPE:
            if not entry_type or entry_type == "":
                error_msg = "STRICT_ENTRY_TYPE enabled: entry_type is required (MARKET or LIMIT)"
                print(f"❌ STRICT MODE REJECTION: {sym_id} {requested_dir} - {error_msg}")
                
                # Create and immediately mark intent as FAILED
                failed_intent = OrderIntent(
                    intent_id=intent_id,
                    symbol=sym_id,
                    side=requested_dir,
                    action=order.side,
                    leverage=order.leverage,
                    size_pct=order.size_pct,
                    tp_pct=order.tp_pct,
                    sl_pct=order.sl_pct,
                    time_in_trade_limit_sec=order.time_in_trade_limit_sec,
                    cooldown_sec=order.cooldown_sec,
                    entry_type="",  # Empty to indicate missing
                    entry_price=order.entry_price,
                    features=(order.features or {}),
                    status=OrderStatus.FAILED,
                    error_message=error_msg
                )
                trading_state.add_intent(failed_intent)
                
                return {
                    "status": "error",
                    "msg": error_msg,
                    "intent_id": intent_id,
                    "symbol": sym_id,
                    "side": requested_dir
                }
        
        # Default to MARKET if not in strict mode
        if not entry_type:
            entry_type = "MARKET"
        
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
            cooldown_sec=order.cooldown_sec,
            entry_type=entry_type,  # Use validated entry_type
            entry_price=order.entry_price,
            features=(order.features or {}),
        )
        # Calculate expiry for LIMIT orders
        if new_intent.entry_type == "LIMIT":
            ttl_sec = order.entry_ttl_sec or 3600  # Default 1 hour
            new_intent.entry_expires_at = (datetime.now() + timedelta(seconds=ttl_sec)).isoformat()
        
        trading_state.add_intent(new_intent)
        print(f"📝 Intent registered: {_truncate_id(intent_id)} for {sym_id} {requested_dir} type={new_intent.entry_type}")
        
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
                        # Opposite side requested
                        if not HEDGE_MODE:
                            # In One-Way mode, cannot have opposite side - must close first
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
        # === COOLDOWN (file-based, robust) ===
        # trading_state.cooldowns may be empty due to persistence issues; closed_cooldown.json is the reliable source.
        try:
            now_ts = time.time()
            cooldown_sec = int(order.cooldown_sec or (COOLDOWN_MINUTES * 60))
            anti_flip_sec = int(os.getenv("ANTI_FLIP_SECONDS", "3600"))

            cooldowns = load_json(COOLDOWN_FILE, default={})

            side_key = f"{sym_id}_{requested_dir}"
            opp_dir = "short" if requested_dir == "long" else "long"
            opp_side_key = f"{sym_id}_{opp_dir}"

            last_close_same = to_float(cooldowns.get(side_key), 0.0)
            last_close_any = to_float(cooldowns.get(sym_id), 0.0)
            last_close_opp = to_float(cooldowns.get(opp_side_key), 0.0)

            # Same-side cooldown (standard)
            if last_close_same > 0 and (now_ts - last_close_same) < cooldown_sec:
                remaining = int(cooldown_sec - (now_ts - last_close_same))
                print(f"⏳ COOLDOWN(FILE): {sym_ccxt} {requested_dir} remaining={remaining}s (last_close={last_close_same})")
                trading_state.update_intent_status(intent_id, OrderStatus.CANCELLED,
                                                  error_message="Cooldown active (file-based)")
                return {
                    "status": "cooldown",
                    "msg": f"Cooldown attivo per {sym_ccxt} {requested_dir} (file) - {remaining}s rimanenti",
                    "intent_id": intent_id
                }

            # Anti-flip: block opposite direction shortly after any recent close
            # (prevents churn OPEN_LONG -> close -> OPEN_SHORT immediately)
            if last_close_opp > 0 and (now_ts - last_close_opp) < anti_flip_sec:
                remaining = int(anti_flip_sec - (now_ts - last_close_opp))
                print(f"⛔ ANTI-FLIP(FILE): {sym_ccxt} block {requested_dir} remaining={remaining}s (opp_close={last_close_opp})")
                trading_state.update_intent_status(intent_id, OrderStatus.CANCELLED,
                                                  error_message="Anti-flip cooldown active (file-based)")
                return {
                    "status": "cooldown",
                    "msg": f"Anti-flip attivo per {sym_ccxt}: blocco {requested_dir} per altri {remaining}s",
                    "intent_id": intent_id
                }

            # Optional: also respect symbol-wide cooldown timestamp if present
            if last_close_any > 0 and (now_ts - last_close_any) < cooldown_sec:
                remaining = int(cooldown_sec - (now_ts - last_close_any))
                print(f"⏳ COOLDOWN(FILE-any): {sym_ccxt} remaining={remaining}s (last_close={last_close_any})")
                trading_state.update_intent_status(intent_id, OrderStatus.CANCELLED,
                                                  error_message="Cooldown active (symbol-wide, file-based)")
                return {
                    "status": "cooldown",
                    "msg": f"Cooldown attivo per {sym_ccxt} (file) - {remaining}s rimanenti",
                    "intent_id": intent_id
                }
        except Exception as e:
            print(f"⚠️ Errore check cooldown file-based: {e}")

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
        # Compute SL pct with hard floor + ATR-based widening (unless order.sl_pct is explicitly provided)
        sl_pct = compute_entry_sl_pct(sym_id, order)
        sl_price = price * (1 - sl_pct) if requested_dir == "long" else price * (1 + sl_pct)
        sl_str = exchange.price_to_precision(sym_ccxt, sl_price)

        print(
            f"🧱 ENTRY SL {sym_id}: pct={sl_pct*100:.2f}% "
            f"(floor={entry_sl_min_pct(sym_id)*100:.2f}%, cap={ENTRY_SL_MAX_PCT*100:.2f}%) -> SL={sl_str}"
        )
        # TP disabled by policy (use trailing SL only)
        tp_str = None
        pos_idx = side_to_position_idx(requested_dir)
        # Log scalping parameters
        scalping_info = ""
        if order.time_in_trade_limit_sec:
            scalping_info = f" MaxTime={order.time_in_trade_limit_sec}s"
        
        # entry_type was already validated and set during intent creation
        print(f"🚀 ORDER {sym_ccxt}: type={entry_type} side={requested_side} qty={final_qty} SL={sl_str}" + 
              f" idx={pos_idx}{scalping_info}")
        
        # === ORDER CREATION: MARKET vs LIMIT ===
        params = {"category": "linear"}
        if HEDGE_MODE:
            params["positionIdx"] = pos_idx
        
        if entry_type == "LIMIT":
            # LIMIT order with orderLinkId for reliable tracking
            if not order.entry_price or order.entry_price <= 0:
                trading_state.update_intent_status(intent_id, OrderStatus.FAILED, 
                                                   error_message="LIMIT order requires valid entry_price")
                return {"status": "error", "msg": "LIMIT order requires valid entry_price", "intent_id": intent_id}
            
            # Use intent_id as orderLinkId for deterministic tracking
            params["orderLinkId"] = intent_id
            
            limit_price = order.entry_price
            limit_price_str = exchange.price_to_precision(sym_ccxt, limit_price)
            
            print(f"📋 LIMIT ENTRY: {sym_ccxt} side={requested_side} qty={final_qty} price={limit_price_str} orderLinkId={_truncate_id(intent_id)}")
            
            res = exchange.create_order(sym_ccxt, "limit", requested_side, final_qty, limit_price, params=params)
            exchange_order_id = res.get("id")
            
            # Extract actual Bybit orderId from response info
            info = res.get("info", {}) or {}
            bybit_order_id = info.get("orderId") or exchange_order_id
            
            # Store both orderId and orderLinkId
            trading_state.update_intent_status(
                intent_id, 
                OrderStatus.PENDING,  # LIMIT order remains PENDING until filled
                exchange_order_id=bybit_order_id,
                exchange_order_link_id=intent_id
            )
            
            print(f"✅ LIMIT order submitted: {sym_id} {requested_dir} orderId={bybit_order_id} orderLinkId={_truncate_id(intent_id)}")
            print(f"   ⏰ Will expire at: {new_intent.entry_expires_at}")
            
            return {
                "status": "pending",
                "msg": "LIMIT order submitted, awaiting fill",
                "id": bybit_order_id,
                "exchange_order_id": bybit_order_id,
                "exchange_order_link_id": intent_id,
                "intent_id": intent_id,
                "symbol": sym_id,
                "side": requested_dir,
                "entry_type": "LIMIT",
                "entry_price": limit_price,
                "expires_at": new_intent.entry_expires_at
            }
        
        # MARKET order (default, backward compatible)
        # Mark intent as EXECUTING for MARKET orders
        trading_state.update_intent_status(intent_id, OrderStatus.EXECUTING)
        
        res = exchange.create_order(sym_ccxt, "market", requested_side, final_qty, params=params)
        exchange_order_id = res.get("id")
        
        # Extract actual Bybit orderId from response info
        info = res.get("info", {}) or {}
        bybit_order_id = info.get("orderId") or exchange_order_id

        # After entry: set StopLoss server-side via trading_stop using MarkPrice (robust retry)
        req = {
            "category": "linear",
            "symbol": sym_id,
            "tpslMode": "Full",
            "stopLoss": sl_str,
            "slTriggerBy": "MarkPrice",
        }
        if HEDGE_MODE:
            req["positionIdx"] = pos_idx

        _sl_ok = False
        _last_err = None
        for _i, _sleep in enumerate([0.4, 0.8, 1.2, 2.0, 3.0], start=1):
            try:
                resp = exchange.private_post_v5_position_trading_stop(req)
                if isinstance(resp, dict) and str(resp.get("retCode")) == "0":
                    print(f"✅ Entry SL set via trading_stop: {sym_id} SL={sl_str} trigger=MarkPrice (try={_i})")
                    _sl_ok = True
                    break
                if isinstance(resp, dict):
                    _last_err = f"retCode={resp.get('retCode')} retMsg={resp.get('retMsg')}"
                else:
                    _last_err = f"unexpected_response={type(resp).__name__}"
                print(f"⚠️ Entry SL trading_stop rejected (try={_i}): {_last_err}")
            except Exception as e:
                _last_err = repr(e)
                print(f"⚠️ Entry SL trading_stop error (try={_i}): {e}")
            import time as _t
            _t.sleep(_sleep)

        if not _sl_ok:
            print(f"❌ CRITICAL: Entry SL NOT set for {sym_id} after retries. LastErr={_last_err}")
            execute_close_position(sym_id, exit_reason="emergency")
        
        # Mark intent as EXECUTED
        trading_state.update_intent_status(intent_id, OrderStatus.EXECUTED, 
                                          exchange_order_id=bybit_order_id)
        
        # Store position metadata for time-based exit
        position_metadata = PositionMetadata(
            symbol=sym_id,
            side=requested_dir,
            opened_at=datetime.now().isoformat(),
            intent_id=intent_id,
            features=(order.features or {}),
            time_in_trade_limit_sec=order.time_in_trade_limit_sec,
            entry_price=price,
            size=final_qty,
            leverage=order.leverage,
            cooldown_sec=order.cooldown_sec,
            entry_type=entry_type  # Persist entry_type (validated earlier)
        )
        trading_state.add_position(position_metadata)
        
        print(f"✅ Position opened: {sym_id} {requested_dir} [intent:{_truncate_id(intent_id)}]")
        
        return {
            "status": "executed", 
            "id": bybit_order_id,
            "exchange_order_id": bybit_order_id,
            "intent_id": intent_id,
            "symbol": sym_id,
            "side": requested_dir
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
        ok = execute_close_position(req.symbol, exit_reason=req.exit_reason)
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

# =========================================================
# TRAILING EXIT (reduce-only conditional StopOrder)
# =========================================================
def _trail_exit_order_link_id(symbol: str, side: str, position_idx: int) -> str:
    sid = bybit_symbol_id(symbol).upper()
    sd = str(side).lower()
    if sd not in ("long", "short"):
        sd = "unk"
    return f"TRLEX_{sid}_{position_idx}_{sd}".replace(":", "").replace("/", "")

def _cancel_trailing_exit(exchange, symbol: str, order_link_id: str) -> None:
    try:
        resp = exchange.private_post_v5_order_cancel({
            "category": "linear",
            "symbol": bybit_symbol_id(symbol),
            "orderLinkId": order_link_id,
        })
        # Bybit: 110001 = "order not exists or too late to cancel" (benigno in upsert flow)
        if isinstance(resp, dict) and str(resp.get("retCode")) == "110001":
            return
        print(f"🧹 Cancel trailing-exit orderLinkId={order_link_id} resp={resp}")
    except Exception as e:
        # keep warnings for real exceptions (network/auth/etc.)
        print(f"⚠️ Cancel trailing-exit failed orderLinkId={order_link_id}: {e}")

def _upsert_trailing_exit_order(exchange, symbol: str, position_side: str, position_idx: int, qty: float, trigger_price: float, trigger_by: str = "MarkPrice") -> None:
    if qty <= 0:
        return
    side_norm = str(position_side).lower()
    if side_norm == "short":
        order_side = "Buy"
        trigger_dir = 1  # rises to trigger
    else:
        order_side = "Sell"
        trigger_dir = 2  # falls to trigger

    order_link_id = _trail_exit_order_link_id(symbol, side_norm, int(position_idx))
    _cancel_trailing_exit(exchange, symbol, order_link_id)

    try:
        qty_str = exchange.amount_to_precision(symbol, float(qty))
    except Exception:
        qty_str = str(qty)
    try:
        trig_str = exchange.price_to_precision(symbol, float(trigger_price))
    except Exception:
        trig_str = str(trigger_price)

    req = {
        "category": "linear",
        "symbol": bybit_symbol_id(symbol),
        "side": order_side,
        "orderType": "Market",
        "qty": qty_str,
        "reduceOnly": True,
        "orderFilter": "StopOrder",
        "triggerPrice": trig_str,
        "triggerBy": trigger_by,
        "triggerDirection": trigger_dir,
        "orderLinkId": order_link_id,
    }
    resp = exchange.private_post_v5_order_create(req)
    print(f"🧷 Trailing-exit upsert {symbol} side={side_norm} idx={position_idx} qty={qty_str} trigger={trig_str} triggerBy={trigger_by} resp={resp}")

