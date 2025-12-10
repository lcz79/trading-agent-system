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
            sl_current = float(p.get('stopLoss') or 0)

            # 1) ROI in %
            if is_long:
                roi_pct = (mark_price - entry_price) / entry_price
            else:
                roi_pct = (entry_price - mark_price) / entry_price

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

# --- AI REVIEW LOGIC ---
def check_ai_review_for_losing_positions():
    """Chiede a Master AI cosa fare con posizioni in perdita > 3%"""
    if not ENABLE_AI_REVIEW or not exchange:
        return
    
    try:
        positions = exchange.fetch_positions(None, params={'category': 'linear'})
        
        for p in positions:
            size = float(p.get('contracts') or 0)
            if size == 0:
                continue
            
            symbol = p.get('symbol', '')
            entry_price = float(p.get('entryPrice') or 0)
            mark_price = float(p.get('markPrice') or 0)
            side = p.get('side', '').lower()
            
            if entry_price == 0:
                continue
            
            # Ottieni leva
            leverage = float(p.get('leverage') or 1)
            
            # Calcola ROI con leva (come mostrato su Bybit)
            is_long = side in ['long', 'buy']
            if is_long:
                roi_raw = (mark_price - entry_price) / entry_price
            else:
                roi_raw = (entry_price - mark_price) / entry_price
            
            roi = roi_raw * leverage  # ROI con leva
            
            # Se in perdita > threshold, chiedi a AI
            if roi < -AI_REVIEW_LOSS_THRESHOLD:
                print(f"🔍 AI REVIEW: {symbol} {side.upper()} ROI={roi*100:.2f}% (leva {leverage}x) - Chiedo a Master AI...")
                
                try:
                    response = requests.post(
                        f"{MASTER_AI_URL}/analyze",
                        json={
                            "symbol": symbol.replace("/", "").replace(":USDT", ""),
                            "current_position": {
                                "side": side,
                                "entry_price": entry_price,
                                "mark_price": mark_price,
                                "roi_pct": roi,
                                "size": size
                            },
                            "request_type": "position_review"
                        },
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        decision = response.json()
                        action = decision.get("action", "HOLD")
                        rationale = decision.get("rationale", "No rationale")
                        
                        print(f"🤖 AI DECISION for {symbol}: {action}")
                        print(f"   Rationale: {rationale}")
                        
                        if action == "CLOSE":
                            print(f"⚠️ AI suggests CLOSE for {symbol} - Manual action required")
                            # Non chiudiamo automaticamente per sicurezza
                        elif action == "REVERSE":
                            print(f"⚠️ AI suggests REVERSE for {symbol} - Manual action required")
                            # Non reversiamo automaticamente per sicurezza
                        else:
                            print(f"✅ AI suggests HOLD for {symbol} - Keeping position")
                    else:
                        print(f"⚠️ AI Review failed for {symbol}: HTTP {response.status_code} - Defaulting to HOLD")
                        
                except requests.exceptions.Timeout:
                    print(f"⚠️ AI Review timeout for {symbol} - Defaulting to HOLD")
                except Exception as e:
                    print(f"⚠️ AI Review error for {symbol}: {e} - Defaulting to HOLD")
                    
    except Exception as e:
        print(f"⚠️ AI Review system error: {e}")

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
    check_ai_review_for_losing_positions()
    return {"status": "ok"}
