import os
import ccxt
import json
import time
import math
import requests
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
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

# --- SMART REVERSE THRESHOLDS ---
WARNING_THRESHOLD = -0.08
AI_REVIEW_THRESHOLD = -0.12
REVERSE_THRESHOLD = -0.15
HARD_STOP_THRESHOLD = -0.20
REVERSE_COOLDOWN_MINUTES = 30
REVERSE_LEVERAGE = 5.0  # Leva per posizioni reverse
reverse_cooldown_tracker = {}

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

# --- FUNZIONE PER FETCH POSIZIONI CON SL REALE ---
def fetch_positions_with_sl():
    """Fetch positions con Stop Loss reale da Bybit API V5"""
    if not exchange:
        return []
    
    try:
        result = exchange.private_get_v5_position_list({
            'category': 'linear',
            'settleCoin': 'USDT'
        })
        
        if result and result.get('retCode') == 0:
            return result.get('result', {}).get('list', [])
        else:
            print(f"⚠️ Errore fetch_positions_with_sl: retCode={result.get('retCode')}")
            return []
    except Exception as e:
        print(f"⚠️ Errore fetch_positions_with_sl: {e}")
        return []

# --- TRAILING LOGIC (FIXED) ---
def check_and_update_trailing_stops():
    if not exchange: return

    try:
        # Usa API V5 per ottenere Stop Loss reale
        positions = fetch_positions_with_sl()

        for p in positions:
            qty = float(p.get('size') or 0)
            if qty == 0: continue

            # Symbol è già nel formato corretto (es. "BTCUSDT")
            symbol_raw = p.get('symbol', '')
            
            # Converti in formato ccxt (es. "BTC/USDT:USDT")
            try:
                # Cerca il market corrispondente
                symbol = None
                for m in exchange.markets.values():
                    if m.get('id') == symbol_raw and m.get('linear', False):
                        symbol = m['symbol']
                        break
                
                if not symbol:
                    # Fallback: costruisci simbolo standard
                    base = symbol_raw.replace('USDT', '')
                    symbol = f"{base}/USDT:USDT"
            except:
                continue

            side_raw = (p.get('side') or '').lower()
            is_long = side_raw in ['long', 'buy']
            
            entry_price = float(p.get('avgPrice') or 0)
            mark_price = float(p.get('markPrice') or 0)
            leverage = float(p.get('leverage') or 1)
            
            # Leggi Stop Loss reale dalla risposta V5
            sl_current = float(p.get('stopLoss') or 0)
            
            if entry_price == 0 or mark_price == 0:
                continue

            # 1) ROI raw (senza leva)
            if is_long:
                roi_raw = (mark_price - entry_price) / entry_price
            else:
                roi_raw = (entry_price - mark_price) / entry_price
            
            # 2) ROI con leva (come mostrato da Bybit)
            roi_pct = roi_raw * leverage

            # 3) Attivazione trailing
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

                    print(f"🏃 TRAILING STOP {symbol_raw} ROI={roi_pct*100:.2f}% (raw={roi_raw*100:.2f}% x{leverage}) SL {sl_current} -> {price_str}")

                    # --- CHIAMATA DIRETTA V5 ---
                    try:
                        req = {
                            "category": "linear",
                            "symbol": symbol_raw,  # Usa symbol raw (es. "BTCUSDT")
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
        
        # Chiudi la posizione
        size = float(position.get('contracts'))
        side = position.get('side', '').lower()
        close_side = 'sell' if side in ['long', 'buy'] else 'buy'
        
        print(f"🔒 Chiudo posizione {symbol}: {side} size={size}")
        
        exchange.create_order(
            symbol, 'market', close_side, size,
            params={'category': 'linear', 'reduceOnly': True}
        )
        
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
                    print(f"📊 AI RACCOMANDA: {action}")
                    print(f"   Rationale: {rationale}")
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
        is_long = 'buy' in order.side.lower() or 'long' in order.side.lower()
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
    check_and_update_trailing_stops()
    check_smart_reverse()
    return {"status": "ok"}
