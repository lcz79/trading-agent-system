import os
import ccxt
import json
import time
import math
import requests
import httpx
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel
from threading import Thread, Lock

app = FastAPI()

# --- CONFIGURAZIONE ---
HISTORY_FILE = "equity_history.json"
API_KEY = os.getenv('BYBIT_API_KEY')
API_SECRET = os.getenv('BYBIT_API_SECRET')
IS_TESTNET = os.getenv('BYBIT_TESTNET', 'false').lower() == 'true'

# --- PARAMETRI TRAILING STOP ---
TRAILING_ACTIVATION_PCT = 0.018  # Attiva se profitto > 1.8%
TRAILING_DISTANCE_PCT = 0.010    # Mantieni stop a 1% di distanza
DEFAULT_INITIAL_SL_PCT = 0.04    # Stop Loss Iniziale

# --- PARAMETRI AI REVIEW ---
ENABLE_AI_REVIEW = os.getenv("ENABLE_AI_REVIEW", "true").lower() == "true"
AI_REVIEW_LOSS_THRESHOLD = 0.03  # Attiva review se perdita > 3%
MASTER_AI_URL = os.getenv("MASTER_AI_URL", "http://04_master_ai_agent:8000")

# --- LEARNING AGENT ---
LEARNING_AGENT_URL = "http://10_learning_agent:8000"
DEFAULT_SIZE_PCT = 0.15  # Default size percentage for learning when actual value unknown

def normalize_symbol(symbol: str) -> str:
    """Normalize symbol by removing separators and suffixes"""
    return symbol.replace("/", "").replace(":USDT", "")


def record_closed_trade(symbol: str, side: str, entry_price: float, exit_price: float, 
                        pnl_pct: float, leverage: float, size_pct: float, 
                        duration_minutes: int, market_conditions: Optional[dict] = None):
    """Send closed trade to Learning Agent for analysis"""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
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
                    "market_conditions": market_conditions or {}
                }
            )
            if response.status_code == 200:
                print(f"📚 Trade recorded for learning: {symbol} {side} PnL={pnl_pct:.2f}%")
    except Exception as e:
        print(f"⚠️ Failed to record trade for learning: {e}")


def record_trade_for_learning(symbol: str, side: str, entry_price: float, exit_price: float,
                               leverage: float, duration_minutes: int, 
                               market_conditions: Optional[dict] = None):
    """Helper to calculate PnL and record trade to Learning Agent"""
    try:
        # Normalizza symbol
        symbol_key = normalize_symbol(symbol)
        
        # Calcola PnL % con leva
        is_long = side in ['long', 'buy']
        if entry_price > 0:
            if is_long:
                pnl_raw = (exit_price - entry_price) / entry_price
            else:
                pnl_raw = (entry_price - exit_price) / entry_price
            pnl_pct = pnl_raw * leverage * 100
        else:
            pnl_pct = 0
        
        record_closed_trade(
            symbol=symbol_key,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=pnl_pct,
            leverage=leverage,
            size_pct=DEFAULT_SIZE_PCT,
            duration_minutes=duration_minutes,
            market_conditions=market_conditions or {}
        )
    except Exception as e:
        print(f"⚠️ Errore in record_trade_for_learning: {e}")

# --- SMART REVERSE THRESHOLDS ---
WARNING_THRESHOLD = -0.08
AI_REVIEW_THRESHOLD = -0.12
REVERSE_THRESHOLD = -0.15
HARD_STOP_THRESHOLD = -0.20
REVERSE_COOLDOWN_MINUTES = 30
REVERSE_LEVERAGE = 5.0  # Leva per posizioni reverse
reverse_cooldown_tracker = {}

# --- COOLDOWN CONFIGURATION ---
COOLDOWN_MINUTES = 5
COOLDOWN_FILE = "/data/closed_cooldown.json"

# --- AI DECISIONS FILE ---
AI_DECISIONS_FILE = "/data/ai_decisions.json"

file_lock = Lock()

exchange = None
if API_KEY and API_SECRET:
    try:
        exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'options': {
                'defaultType': 'swap',
                'adjustForTimeDifference': True
            }
        })
        if IS_TESTNET:
            exchange.set_sandbox_mode(True)
        exchange.load_markets()
        print(f"🔌 Position Manager: Connesso (Testnet: {IS_TESTNET})")
    except Exception as e:
        print(f"⚠️ Errore Connessione: {e}")

# --- MEMORY ---
def load_json(f, d=[]):
    with file_lock:
        if os.path.exists(f):
            try:
                with open(f, 'r') as file: return json.load(file)
            except: return d
        return d

def save_json(f, d):
    with file_lock:
        try:
            with open(f, 'w') as file: json.dump(d, file, indent=2)
        except: pass

def record_equity_loop():
    while True:
        if exchange:
            try:
                bal = exchange.fetch_balance(params={'type': 'swap'})
                usdt = bal.get('USDT', {})
                real_bal = float(usdt.get('total', 0))
                pos = exchange.fetch_positions(None, params={'category': 'linear'})
                upnl = sum([float(p.get('unrealizedPnl') or 0) for p in pos])

                hist = load_json(HISTORY_FILE)
                hist.append({
                    "timestamp": datetime.now().isoformat(),
                    "real_balance": real_bal,
                    "live_equity": real_bal + upnl
                })
                if len(hist) > 4000: hist = hist[-4000:]
                save_json(HISTORY_FILE, hist)
            except: pass
        time.sleep(60)

Thread(target=record_equity_loop, daemon=True).start()

# --- MODELLI ---
class OrderRequest(BaseModel):
    symbol: str
    side: str = "buy"
    leverage: float = 1.0
    size_pct: float = 0.0
    sl_pct: float = 0.0 

class CloseRequest(BaseModel):
    symbol: str

# --- TRAILING LOGIC (FIXED) ---
def check_and_update_trailing_stops():
    if not exchange: return

    try:
        positions = exchange.fetch_positions(None, params={'category': 'linear'})

        for p in positions:
            qty = float(p.get('contracts') or 0)
            if qty == 0: continue

            symbol = p['symbol'] 
            
            # Ottieni ID di mercato per chiamate RAW
            try:
                market_id = exchange.market(symbol)['id']
            except:
                market_id = symbol.replace('/', '').split(':')[0]

            side_raw = (p.get('side') or '').lower()
            is_long = side_raw in ['long', 'buy']
            
            entry_price = float(p['entryPrice'])
            mark_price = float(p['markPrice'])
            sl_current = float(p.get('info', {}).get('stopLoss') or p.get('stopLoss') or 0)

            # 1) ROI in % (con leva)
            leverage = float(p. get('leverage') or 1)
            if is_long:
                roi_raw = (mark_price - entry_price) / entry_price
            else:
                roi_raw = (entry_price - mark_price) / entry_price
            roi_pct = roi_raw * leverage
            # 2) Attivazione trailing
            if roi_pct >= TRAILING_ACTIVATION_PCT:
                new_sl_price = None

                if is_long:
                    target_sl = mark_price * (1 - TRAILING_DISTANCE_PCT)
                    if sl_current == 0 or target_sl > sl_current:
                        new_sl_price = target_sl
                else:
                    target_sl = mark_price * (1 + TRAILING_DISTANCE_PCT)
                    if sl_current == 0 or target_sl < sl_current:
                        new_sl_price = target_sl

                if new_sl_price:
                    price_str = exchange.price_to_precision(symbol, new_sl_price)

                    print(f"🏃 TRAILING STOP {symbol} ROI={roi_pct*100:.2f}% SL {sl_current} -> {price_str}")

                    # --- FIX: CHIAMATA DIRETTA V5 ---
                    try:
                        req = {
                            "category": "linear",
                            "symbol": market_id,
                            "stopLoss": price_str,
                            "positionIdx": 0
                        }
                        exchange.private_post_v5_position_trading_stop(req)
                        print("✅ SL Aggiornato con successo su Bybit")
                    except Exception as api_err:
                        print(f"❌ Errore API Bybit: {api_err}")

    except Exception as e:
        print(f"⚠️ Trailing logic error: {e}")

# --- SMART REVERSE SYSTEM ---

def save_ai_decision(decision_data):
    """Salva la decisione AI per visualizzarla nella dashboard"""
    try:
        decisions = []
        if os.path.exists(AI_DECISIONS_FILE):
            with open(AI_DECISIONS_FILE, 'r') as f:
                decisions = json.load(f)
        
        decisions.append({
            'timestamp': datetime.now().isoformat(),
            'symbol': decision_data.get('symbol'),
            'action': decision_data.get('action'),
            'leverage': decision_data.get('leverage', 0),
            'size_pct': decision_data.get('size_pct', 0),
            'rationale': decision_data.get('rationale', ''),
            'analysis_summary': decision_data.get('analysis_summary', ''),
            'roi_pct': decision_data.get('roi_pct', 0),
            'source': 'position_manager'  # Per distinguere dalla fonte
        })
        
        decisions = decisions[-100:]  # Mantieni solo ultime 100
        
        os.makedirs(os.path.dirname(AI_DECISIONS_FILE), exist_ok=True)
        with open(AI_DECISIONS_FILE, 'w') as f:
            json.dump(decisions, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving AI decision: {e}")

def request_reverse_analysis(symbol, position_data):
    """Chiama Master AI per analisi reverse"""
    try:
        response = requests.post(
            f"{MASTER_AI_URL}/analyze_reverse",
            json={
                "symbol": symbol.replace("/", "").replace(":USDT", ""),
                "current_position": position_data
            },
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"⚠️ Reverse analysis failed: HTTP {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        print(f"⚠️ Reverse analysis timeout for {symbol}")
        return None
    except Exception as e:
        print(f"⚠️ Reverse analysis error: {e}")
        return None


def execute_close_position(symbol):
    """Chiude una posizione esistente"""
    if not exchange:
        return False
    
    try:
        # Ottieni la posizione corrente
        positions = exchange.fetch_positions([symbol], params={'category': 'linear'})
        position = None
        for p in positions:
            if float(p.get('contracts') or 0) > 0:
                position = p
                break
        
        if not position:
            print(f"⚠️ Nessuna posizione aperta per {symbol}")
            return False
        
        # Cattura dati pre-chiusura per learning
        entry_price = float(position.get('entryPrice', 0))
        mark_price = float(position.get('markPrice', entry_price))
        leverage = float(position.get('leverage', 1))
        side = position.get('side', '').lower()
        unrealized_pnl = float(position.get('unrealizedPnl', 0))
        
        # Calcola PnL % con leva (matching Bybit ROI)
        is_long = side in ['long', 'buy']
        if is_long:
            pnl_raw = (mark_price - entry_price) / entry_price if entry_price > 0 else 0
        else:
            pnl_raw = (entry_price - mark_price) / entry_price if entry_price > 0 else 0
        pnl_pct = pnl_raw * leverage * 100
        
        # Chiudi la posizione
        size = float(position.get('contracts'))
        close_side = 'sell' if is_long else 'buy'
        
        print(f"🔒 Chiudo posizione {symbol}: {side} size={size}")
        
        exchange.create_order(
            symbol, 'market', close_side, size,
            params={'category': 'linear', 'reduceOnly': True}
        )
        
        # Record trade per learning
        # Nota: duration_minutes non disponibile per chiusure manuali
        # Il Learning Agent userà solo i trade con durata valida per analisi temporali
        record_trade_for_learning(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=mark_price,
            leverage=leverage,
            duration_minutes=0,
            market_conditions={}
        )
        
        # Salva cooldown per symbol + direzione
        try:
            symbol_key = symbol.replace("/", "").replace(":USDT", "")
            cooldowns = {}
            if os.path.exists(COOLDOWN_FILE):
                with open(COOLDOWN_FILE, 'r') as f:
                    cooldowns = json.load(f)
            
            # Salva con direzione specifica
            direction_key = f"{symbol_key}_{side}"
            cooldowns[direction_key] = time.time()
            # Mantieni anche per compatibilità
            cooldowns[symbol_key] = time.time()
            
            with open(COOLDOWN_FILE, 'w') as f:
                json.dump(cooldowns, f, indent=2)
            
            print(f"💾 Cooldown salvato per {direction_key}")
        except Exception as e:
            print(f"⚠️ Errore salvataggio cooldown: {e}")
        
        print(f"✅ Posizione {symbol} chiusa con successo")
        return True
        
    except Exception as e:
        print(f"❌ Errore chiusura posizione {symbol}: {e}")
        return False


def execute_reverse(symbol, current_side, recovery_size_pct):
    """Chiude posizione corrente e apre posizione opposta con size di recupero"""
    if not exchange:
        return False
    
    try:
        # 1. Chiudi posizione corrente
        if not execute_close_position(symbol):
            return False
        
        time.sleep(1)  # Breve pausa per assicurarsi che la chiusura sia processata
        
        # 2. Calcola nuova posizione opposta
        new_side = 'sell' if current_side in ['long', 'buy'] else 'buy'
        
        # 3. Ottieni balance e prezzo
        bal = exchange.fetch_balance(params={'type': 'swap'})
        free_balance = float(bal['USDT']['free'])
        price = float(exchange.fetch_ticker(symbol)['last'])
        
        # 4. Calcola size con recovery_size_pct
        cost = max(free_balance * recovery_size_pct, 10.0)
        leverage = REVERSE_LEVERAGE
        
        # 5. Calcola quantità con precisione
        target_market = exchange.market(symbol)
        info = target_market.get('info', {}) or {}
        lot_filter = info.get('lotSizeFilter', {}) or {}
        qty_step = float(lot_filter.get('qtyStep') or target_market['limits']['amount']['min'] or 0.001)
        min_qty = float(lot_filter.get('minOrderQty') or qty_step)
        
        qty_raw = (cost * leverage) / price
        d_qty = Decimal(str(qty_raw))
        d_step = Decimal(str(qty_step))
        steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
        final_qty_d = steps * d_step
        
        if final_qty_d < Decimal(str(min_qty)):
            final_qty_d = Decimal(str(min_qty))
        final_qty = float("{:f}".format(final_qty_d.normalize()))
        
        # 6. Imposta leva
        try:
            exchange.set_leverage(int(leverage), symbol, params={'category': 'linear'})
        except Exception as e:
            print(f"⚠️ Impossibile impostare leva: {e}")
        
        # 7. Calcola Stop Loss
        sl_pct = DEFAULT_INITIAL_SL_PCT
        is_long = new_side == 'buy'
        sl_price = price * (1 - sl_pct) if is_long else price * (1 + sl_pct)
        sl_str = exchange.price_to_precision(symbol, sl_price)
        
        print(f"🔄 REVERSE {symbol}: {current_side} -> {new_side}, size={recovery_size_pct*100:.1f}%, qty={final_qty}")
        
        # 8. Apri nuova posizione
        res = exchange.create_order(
            symbol, 'market', new_side, final_qty,
            params={'category': 'linear', 'stopLoss': sl_str}
        )
        
        print(f"✅ Reverse eseguito con successo: {res['id']}")
        return True
        
    except Exception as e:
        print(f"❌ Errore durante reverse: {e}")
        return False


def check_recent_closes_and_save_cooldown():
    """
    Rileva posizioni chiuse da Bybit (SL/TP) e salva cooldown
    
    Questa funzione previene la riapertura immediata di posizioni nella stessa direzione
    quando Bybit chiude automaticamente una posizione tramite Stop Loss o Take Profit.
    
    Comportamento:
    - Controlla le ultime 20 posizioni chiuse
    - Salva cooldown per posizioni chiuse negli ultimi 10 minuti
    - Usa chiave specifica per direzione (es: ETHUSDT_long, BTCUSDT_short)
    - Permette REVERSE (direzione opposta) ma blocca stessa direzione per COOLDOWN_MINUTES
    
    Esempio:
    - ETH LONG chiuso da SL → salva cooldown ETHUSDT_long
    - Nuovo segnale LONG su ETH → ❌ bloccato (cooldown attivo)
    - Nuovo segnale SHORT su ETH → ✅ permesso (reverse)
    """
    if not exchange:
        return
    
    try:
        # Ottieni posizioni chiuse negli ultimi 10 minuti
        res = exchange.private_get_v5_position_closed_pnl({
            'category': 'linear',
            'limit': 20
        })
        
        if not res or res.get('retCode') != 0:
            return
        
        items = res.get('result', {}).get('list', [])
        current_time = time.time()
        
        # Carica cooldown esistenti con lock
        with file_lock:
            cooldowns = {}
            if os.path.exists(COOLDOWN_FILE):
                try:
                    with open(COOLDOWN_FILE, 'r') as f:
                        cooldowns = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    print(f"⚠️ Errore lettura cooldown file: {e}")
                    cooldowns = {}
        
        for item in items:
            # Controlla se chiusa negli ultimi 10 minuti
            close_time_ms = int(item.get('updatedTime', 0))
            close_time_sec = close_time_ms / 1000
            
            if (current_time - close_time_sec) > 600:  # Più di 10 minuti fa
                continue
            
            # Symbol già normalizzato da Bybit (es. "ETHUSDT")
            symbol_raw = item.get('symbol', '')
            side = item.get('side', '').lower()  # "Buy" o "Sell"
            
            # Converti side in long/short
            direction = 'long' if side == 'buy' else 'short'
            
            # Crea chiave cooldown (usa symbol completo per consistenza)
            direction_key = f"{symbol_raw}_{direction}"
            
            # Salva cooldown se non esiste già o è più vecchio
            existing_time = cooldowns.get(direction_key, 0)
            if close_time_sec > existing_time:
                cooldowns[direction_key] = close_time_sec
                # Salva anche con chiave symbol per backward compatibility
                cooldowns[symbol_raw] = close_time_sec
                print(f"💾 Cooldown auto-salvato per {direction_key} (chiusura Bybit)")
                
                # Record trade per learning (chiusura automatica Bybit)
                try:
                    entry_price = float(item.get('avgEntryPrice', 0))
                    exit_price = float(item.get('avgExitPrice', 0))
                    leverage = float(item.get('leverage', 1))
                    
                    # Calcola durata in minuti
                    created_time_ms = int(item.get('createdTime', close_time_ms))
                    duration_minutes = int((close_time_ms - created_time_ms) / 1000 / 60)
                    
                    record_trade_for_learning(
                        symbol=symbol_raw,
                        side=direction,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        leverage=leverage,
                        duration_minutes=duration_minutes,
                        market_conditions={"closed_by": "bybit_sl_tp"}
                    )
                except Exception as e:
                    print(f"⚠️ Errore recording auto-closed trade: {e}")
        
        # Salva file con lock
        with file_lock:
            try:
                with open(COOLDOWN_FILE, 'w') as f:
                    json.dump(cooldowns, f, indent=2)
            except IOError as e:
                print(f"⚠️ Errore scrittura cooldown file: {e}")
            
    except Exception as e:
        print(f"⚠️ Errore check chiusure recenti: {e}")


def check_smart_reverse():
    """Sistema intelligente multi-livello per gestire posizioni in perdita"""
    if not ENABLE_AI_REVIEW or not exchange:
        return
    
    try:
        positions = exchange.fetch_positions(None, params={'category': 'linear'})
        wallet_bal = exchange.fetch_balance(params={'type': 'swap'})
        wallet_balance = float(wallet_bal.get('USDT', {}).get('total', 0))
        
        if wallet_balance == 0:
            return
        
        for p in positions:
            size = float(p.get('contracts') or 0)
            if size == 0:
                continue
            
            symbol = p.get('symbol', '')
            entry_price = float(p.get('entryPrice') or 0)
            mark_price = float(p.get('markPrice') or 0)
            side = p.get('side', '').lower()
            pnl_dollars = float(p.get('unrealizedPnl') or 0)
            
            if entry_price == 0:
                continue
            
            # Calcola ROI con leva
            leverage = float(p.get('leverage') or 1)
            is_long = side in ['long', 'buy']
            if is_long:
                roi_raw = (mark_price - entry_price) / entry_price
            else:
                roi_raw = (entry_price - mark_price) / entry_price
            
            roi = roi_raw * leverage  # ROI con leva
            
            # Sistema a 4 livelli
            
            # LIVELLO 4: HARD STOP (-20%) - Chiudi sempre
            if roi <= HARD_STOP_THRESHOLD:
                print(f"🛑 HARD STOP: {symbol} {side.upper()} ROI={roi*100:.2f}% - Chiusura immediata!")
                execute_close_position(symbol)
                continue
            
            # LIVELLO 3: REVERSE TRIGGER (-15%) - Chiedi AI e reverse se confermato
            if roi <= REVERSE_THRESHOLD:
                # Controlla cooldown
                symbol_key = symbol.replace("/", "").replace(":USDT", "")
                last_reverse_time = reverse_cooldown_tracker.get(symbol_key, 0)
                current_time = time.time()
                
                if (current_time - last_reverse_time) < (REVERSE_COOLDOWN_MINUTES * 60):
                    minutes_left = int((REVERSE_COOLDOWN_MINUTES * 60 - (current_time - last_reverse_time)) / 60)
                    print(f"⏳ Reverse cooldown attivo per {symbol}: {minutes_left} minuti rimanenti")
                    continue
                
                print(f"⚠️ REVERSE TRIGGER: {symbol} {side.upper()} ROI={roi*100:.2f}% - Chiedo conferma AI...")
                
                position_data = {
                    "side": side,
                    "entry_price": entry_price,
                    "mark_price": mark_price,
                    "roi_pct": roi,
                    "size": size,
                    "pnl_dollars": pnl_dollars,
                    "leverage": leverage,
                    "wallet_balance": wallet_balance
                }
                
                analysis = request_reverse_analysis(symbol, position_data)
                
                if analysis:
                    action = analysis.get("action", "HOLD")
                    rationale = analysis.get("rationale", "No rationale")
                    confidence = analysis.get("confidence", 0)
                    recovery_size_pct = analysis.get("recovery_size_pct", 0.15)
                    
                    print(f"🤖 AI REVERSE DECISION for {symbol}: {action} (confidence: {confidence}%)")
                    print(f"   Rationale: {rationale}")
                    
                    # Salva decisione AI per dashboard
                    save_ai_decision({
                        'symbol': symbol.replace("/", "").replace(":USDT", ""),
                        'action': action,
                        'rationale': rationale,
                        'analysis_summary': f"REVERSE TRIGGER | ROI: {roi*100:.2f}% | Confidence: {confidence}%",
                        'roi_pct': roi * 100,
                        'leverage': leverage,
                        'size_pct': recovery_size_pct * 100 if action == "REVERSE" else 0
                    })
                    
                    if action == "REVERSE":
                        print(f"🔄 Eseguo REVERSE per {symbol} con size {recovery_size_pct*100:.1f}%")
                        if execute_reverse(symbol, side, recovery_size_pct):
                            reverse_cooldown_tracker[symbol_key] = current_time
                    elif action == "CLOSE":
                        print(f"🔒 Eseguo CLOSE per {symbol}")
                        execute_close_position(symbol)
                    else:
                        print(f"✋ HOLD - Mantengo posizione {symbol}")
                else:
                    print(f"⚠️ Analisi AI fallita per {symbol} - Mantengo posizione")
                
                continue
            
            # LIVELLO 2: AI REVIEW (-12%) - Solo analisi e log
            if roi <= AI_REVIEW_THRESHOLD:
                print(f"🔍 AI REVIEW: {symbol} {side.upper()} ROI={roi*100:.2f}% - Chiedo consiglio AI...")
                
                position_data = {
                    "side": side,
                    "entry_price": entry_price,
                    "mark_price": mark_price,
                    "roi_pct": roi,
                    "size": size,
                    "pnl_dollars": pnl_dollars,
                    "leverage": leverage,
                    "wallet_balance": wallet_balance
                }
                
                analysis = request_reverse_analysis(symbol, position_data)
                
                if analysis:
                    action = analysis.get("action", "HOLD")
                    rationale = analysis.get("rationale", "No rationale")
                    confidence = analysis.get("confidence", 0)
                    print(f"📊 AI RACCOMANDA: {action}")
                    print(f"   Rationale: {rationale}")
                    
                    # Salva decisione AI per dashboard
                    save_ai_decision({
                        'symbol': symbol.replace("/", "").replace(":USDT", ""),
                        'action': action,
                        'rationale': rationale,
                        'analysis_summary': f"AI REVIEW | ROI: {roi*100:.2f}% | Confidence: {confidence}%",
                        'roi_pct': roi * 100,
                        'leverage': leverage,
                        'size_pct': 0
                    })
                else:
                    print(f"⚠️ Analisi AI fallita per {symbol}")
                
                continue
            
            # LIVELLO 1: WARNING (-8%) - Solo log
            if roi <= WARNING_THRESHOLD:
                print(f"⚠️ WARNING: {symbol} {side.upper()} ROI={roi*100:.2f}% - Posizione in perdita moderata")
                
    except Exception as e:
        print(f"⚠️ Smart Reverse system error: {e}")

# --- API ENDPOINTS ---
@app.get("/get_wallet_balance")
def get_balance():
    if not exchange: return {"equity": 0, "available": 0}
    try:
        bal = exchange.fetch_balance(params={'type': 'swap'})
        u = bal.get('USDT', {})
        return {"equity": float(u.get('total', 0)), "available": float(u.get('free', 0))}
    except: return {"equity": 0, "available": 0}

@app.get("/get_open_positions")
def get_positions():
    if not exchange: return {"active": [], "details": []}
    try:
        raw = exchange.fetch_positions(None, params={'category': 'linear'})
        active = []
        details = []
        for p in raw:
            if float(p.get('contracts') or 0) > 0:
                sym = p['symbol'].split(':')[0].replace('/', '')
                entry_price = float(p['entryPrice'])
                mark_price = float(p.get('markPrice', p['entryPrice']))
                leverage = float(p.get('leverage', 1))
                side = p.get('side', '').lower()
                
                # Calculate PnL % with leverage (matching Bybit ROI display)
                if side in ['short', 'sell']:
                    pnl_pct = ((entry_price - mark_price) / entry_price) * leverage * 100
                else:  # long/buy
                    pnl_pct = ((mark_price - entry_price) / entry_price) * leverage * 100
                
                details.append({
                    "symbol": sym,
                    "side": p.get('side'),
                    "size": float(p['contracts']),
                    "entry_price": entry_price,
                    "mark_price": mark_price,
                    "pnl": float(p.get('unrealizedPnl') or 0),
                    "pnl_pct": round(pnl_pct, 2),  # NEW FIELD with leverage
                    "leverage": leverage
                })
                active.append(sym)
        return {"active": active, "details": details}
    except: return {"active": [], "details": []}

@app.get("/get_history")
def get_hist(): return load_json(HISTORY_FILE)

@app.get("/get_closed_positions")
def get_closed():
    if not exchange: return []
    try:
        res = exchange.private_get_v5_position_closed_pnl({'category': 'linear', 'limit': 20})
        if res and res.get('retCode') == 0:
            items = res.get('result', {}).get('list', [])
            clean = []
            for i in items:
                ts = int(i.get('updatedTime', 0))
                clean.append({
                    'datetime': datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M'),
                    'symbol': i.get('symbol'),
                    'side': i.get('side'),
                    'price': float(i.get('avgExitPrice', 0)),
                    'closedPnl': float(i.get('closedPnl', 0))
                })
            return clean
        return []
    except: return []

@app.post("/open_position")
def open_position(order: OrderRequest):
    if not exchange: return {"status": "error", "msg": "No Exchange"}

    try:
        raw_sym = order.symbol
        target_market = None
        for m in exchange.markets.values():
            if m.get('id') == raw_sym and m.get('linear', False):
                target_market = m
                break
        if not target_market: target_market = exchange.market(raw_sym)
        sym = target_market['symbol']
        
        # Determina la direzione richiesta
        is_long_request = 'buy' in order.side.lower() or 'long' in order.side.lower()
        requested_side = 'long' if is_long_request else 'short'
        symbol_key = sym.replace("/", "").replace(":USDT", "")
        
        # CONTROLLO 1: Verifica posizioni esistenti
        try:
            positions = exchange.fetch_positions([sym], params={'category': 'linear'})
            for p in positions:
                contracts = float(p.get('contracts', 0))
                if contracts > 0:
                    existing_side = p.get('side', '').lower()
                    
                    if existing_side == requested_side:
                        # Stessa direzione → BLOCCA
                        print(f"⚠️ SKIP: Già esiste posizione {existing_side.upper()} su {sym}")
                        return {
                            "status": "skipped", 
                            "msg": f"Posizione {existing_side} già aperta su {sym}",
                            "existing_side": existing_side
                        }
                    else:
                        # Direzione opposta → REVERSE permesso
                        print(f"🔄 REVERSE PERMESSO: {existing_side} → {requested_side} su {sym}")
        except Exception as e:
            print(f"⚠️ Errore check posizioni esistenti: {e}")
        
        # CONTROLLO 2: Verifica cooldown per symbol + direzione
        try:
            if os.path.exists(COOLDOWN_FILE):
                with open(COOLDOWN_FILE, 'r') as f:
                    cooldowns = json.load(f)
                
                # Chiave specifica per symbol + direzione (es: ETH_long, BTC_short)
                cooldown_key = f"{symbol_key}_{requested_side}"
                last_close_time = cooldowns.get(cooldown_key, 0)
                elapsed = time.time() - last_close_time
                
                if elapsed < (COOLDOWN_MINUTES * 60):
                    minutes_left = COOLDOWN_MINUTES - (elapsed / 60)
                    print(f"⏳ COOLDOWN: {sym} {requested_side} - ancora {minutes_left:.1f} minuti")
                    return {
                        "status": "cooldown",
                        "msg": f"Cooldown attivo per {sym} {requested_side}",
                        "minutes_left": round(minutes_left, 1)
                    }
        except Exception as e:
            print(f"⚠️ Errore check cooldown: {e}")
        
        # 1. Leva
        try: exchange.set_leverage(int(order.leverage), sym, params={'category': 'linear'})
        except: pass

        # 2. Soldi
        bal = float(exchange.fetch_balance(params={'type': 'swap'})['USDT']['free'])
        cost = max(bal * order.size_pct, 10.0)
        price = float(exchange.fetch_ticker(sym)['last'])

        # 3. Quantità
        info = target_market.get('info', {}) or {}
        lot_filter = info.get('lotSizeFilter', {}) or {}
        qty_step = float(lot_filter.get('qtyStep') or target_market['limits']['amount']['min'] or 0.001)
        min_qty = float(lot_filter.get('minOrderQty') or qty_step)

        qty_raw = (cost * order.leverage) / price
        d_qty = Decimal(str(qty_raw))
        d_step = Decimal(str(qty_step))
        steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
        final_qty_d = steps * d_step
        
        if final_qty_d < Decimal(str(min_qty)): final_qty_d = Decimal(str(min_qty))
        final_qty = float("{:f}".format(final_qty_d.normalize()))

        # 4. SL Iniziale
        sl_pct = order.sl_pct if order.sl_pct > 0 else DEFAULT_INITIAL_SL_PCT
        is_long = requested_side == 'long'
        side = 'buy' if is_long else 'sell'
        
        sl_price = price * (1 - sl_pct) if is_long else price * (1 + sl_pct)
        sl_str = exchange.price_to_precision(sym, sl_price)

        print(f"🚀 ORDER {sym}: Qty={final_qty} | SL={sl_str}")

        res = exchange.create_order(
            sym, 'market', side, final_qty, 
            params={'category': 'linear', 'stopLoss': sl_str}
        )

        return {"status": "executed", "id": res['id']}

    except Exception as e:
        print(f"❌ Order Error: {e}")
        return {"status": "error", "msg": str(e)}

@app.post("/close_position")
def close_position(req: CloseRequest): return {"status": "manual_only"}

@app.post("/manage_active_positions")
def manage():
    check_recent_closes_and_save_cooldown()  # Rileva chiusure automatiche Bybit
    check_and_update_trailing_stops()
    check_smart_reverse()
    return {"status": "ok"}
