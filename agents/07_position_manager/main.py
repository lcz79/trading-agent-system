import os
import ccxt
import json
import time
import math
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
# Attiva il trailing quando il profitto supera l'1.8%
TRAILING_ACTIVATION_PCT = 0.018
# Mantieni lo stop a questa distanza dal prezzo corrente (1%)
TRAILING_DISTANCE_PCT = 0.010
# Stop Loss Iniziale di Default (se l'AI non lo specifica)
DEFAULT_INITIAL_SL_PCT = 0.04

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
                with open(f, 'r') as file:
                    return json.load(file)
            except:
                return d
        return d

def save_json(f, d):
    with file_lock:
        try:
            with open(f, 'w') as file:
                json.dump(d, file, indent=2)
        except:
            pass

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
                if len(hist) > 4000:
                    hist = hist[-4000:]
                save_json(HISTORY_FILE, hist)
            except:
                pass
        time.sleep(60)

Thread(target=record_equity_loop, daemon=True).start()

# --- MODELLI ---
class OrderRequest(BaseModel):
    symbol: str          # es. "BTCUSDT"
    side: str = "buy"    # es. "OPEN_LONG", "OPEN_SHORT", "buy", "sell"
    leverage: float = 1.0
    size_pct: float = 0.0
    sl_pct: float = 0.0  # Percentuale Stop Loss gestita dall'AI (0 = usa default)

class CloseRequest(BaseModel):
    symbol: str

# --- TRAILING LOGIC ---
def check_and_update_trailing_stops():
    """
    Controlla le posizioni aperte e sposta lo SL se in profitto > TRAILING_ACTIVATION_PCT.
    """
    if not exchange:
        return

    try:
        positions = exchange.fetch_positions(None, params={'category': 'linear'})

        for p in positions:
            qty = float(p.get('contracts') or 0)
            if qty == 0:
                continue

            symbol = p['symbol']  # es. "BTCUSDT" oppure "BTC/USDT:USDT"
            side_raw = (p.get('side') or '').lower()   # "long", "short", "buy", "sell"
            is_long = side_raw in ['long', 'buy']
            bybit_side = 'Buy' if is_long else 'Sell'

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
                    # Long: SL si muove sotto il prezzo attuale
                    target_sl = mark_price * (1 - TRAILING_DISTANCE_PCT)
                    # aggiorna solo se SL sale (proteggi di più) o se non esiste
                    if sl_current == 0 or target_sl > sl_current:
                        new_sl_price = target_sl
                else:
                    # Short: SL si muove sopra il prezzo attuale
                    target_sl = mark_price * (1 + TRAILING_DISTANCE_PCT)
                    # aggiorna solo se SL scende (più vicino a mark) o se non esiste
                    if sl_current == 0 or target_sl < sl_current:
                        new_sl_price = target_sl

                if new_sl_price:
                    price_str = exchange.price_to_precision(symbol, new_sl_price)

                    print(f"🏃 TRAILING STOP {symbol} ROI={roi_pct*100:.2f}% "
                          f"SL {sl_current} -> {price_str}")

                    # set_trading_stop(symbol, params={...})
                    exchange.set_trading_stop(
                        symbol,
                        {
                            'category': 'linear',
                            'side': bybit_side,
                            'stopLoss': price_str,
                        }
                    )

    except Exception as e:
        print(f"⚠️ Trailing logic error: {e}")

# --- API ENDPOINTS ---
@app.get("/get_wallet_balance")
def get_balance():
    if not exchange:
        return {"equity": 0, "available": 0}
    try:
        bal = exchange.fetch_balance(params={'type': 'swap'})
        u = bal.get('USDT', {})
        return {"equity": float(u.get('total', 0)), "available": float(u.get('free', 0))}
    except:
        return {"equity": 0, "available": 0}

@app.get("/get_open_positions")
def get_positions():
    if not exchange:
        return {"active": [], "details": []}
    try:
        raw = exchange.fetch_positions(None, params={'category': 'linear'})
        active = []
        details = []
        for p in raw:
            if float(p.get('contracts') or 0) > 0:
                sym = p['symbol'].split(':')[0].replace('/', '')
                details.append({
                    "symbol": sym,
                    "side": p.get('side'),
                    "size": float(p['contracts']),
                    "entry_price": float(p['entryPrice']),
                    "pnl": float(p.get('unrealizedPnl') or 0),
                    "leverage": p.get('leverage', 1)
                })
                active.append(sym)
        return {"active": active, "details": details}
    except:
        return {"active": [], "details": []}

@app.get("/get_history")
def get_hist():
    return load_json(HISTORY_FILE)

@app.get("/get_closed_positions")
def get_closed():
    # TODO: implementare lettura closed PnL se ti serve storicizzare
    return []

# --- OPEN POSITION LOGIC ---

def _resolve_market(raw_sym: str):
    """
    Risolve 'BTCUSDT' in un market ccxt (es. 'BTC/USDT:USDT') lineare.
    """
    # Prova a matchare per id lineare
    for m in exchange.markets.values():
        if m.get('id') == raw_sym and m.get('linear', False):
            return m
    # Fallback: usa il simbolo così com'è se esiste
    if raw_sym in exchange.markets:
        return exchange.market(raw_sym)
    return None

@app.post("/open_position")
def open_position(order: OrderRequest):
    if not exchange:
        return {"status": "error", "msg": "No Exchange"}

    try:
        # 1. Risoluzione Market
        raw_sym = order.symbol
        target_market = _resolve_market(raw_sym)
        if not target_market:
            return {"status": "error", "msg": f"Symbol {raw_sym} not found in markets"}

        sym = target_market['symbol']
        info = target_market.get('info', {}) or {}
        print(f"🚀 Processing {sym}...")

        # 2. Leva
        try:
            exchange.set_leverage(int(order.leverage), sym, params={'category': 'linear'})
        except Exception as e:
            print(f"⚠️ Leverage warning: {e}")

        # 3. Calcoli Soldi
        bal = exchange.fetch_balance(params={'type': 'swap'})['USDT']['free']
        bal = float(bal)

        if order.size_pct <= 0:
            return {"status": "error", "msg": "size_pct must be > 0"}

        cost = bal * order.size_pct
        # minimo di sicurezza
        if cost < 10.0:
            cost = 10.0

        ticker = exchange.fetch_ticker(sym)
        price = float(ticker['last'])

        # 4. Calcolo Qty grezza
        qty_raw = (cost * order.leverage) / price

        # 5. Ricava lotSizeFilter: minOrderQty + qtyStep
        lot_filter = info.get('lotSizeFilter', {}) or {}
        min_order_qty = float(lot_filter.get('minOrderQty') or target_market['limits']['amount']['min'] or 0)
        qty_step = float(lot_filter.get('qtyStep') or target_market['limits']['amount']['min'] or 0)

        if qty_step <= 0:
            # fallback robusto
            qty_step = float(target_market['limits']['amount']['min'] or 0.001)

        d_qty = Decimal(str(qty_raw))
        d_step = Decimal(str(qty_step))

        # numero di step interi
        steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
        d_final = steps * d_step

        if min_order_qty > 0 and d_final < Decimal(str(min_order_qty)):
            d_final = Decimal(str(min_order_qty))

        # stringa "pulita"
        final_qty_str = "{:f}".format(d_final.normalize())

        # applica ancora la precisione ccxt per sicurezza
        final_qty_str = exchange.amount_to_precision(sym, float(final_qty_str))
        final_qty = float(final_qty_str)

        print(f"📐 QTY Logic {sym}: bal={bal}, cost={cost}, price={price}, lev={order.leverage}")
        print(f"   raw={qty_raw}, min={min_order_qty}, step={qty_step}, final={final_qty}")

        if final_qty <= 0:
            return {"status": "error", "msg": f"Final qty <= 0 for {sym}"}

        # 6. Calcolo Stop Loss Iniziale
        sl_percent = order.sl_pct if order.sl_pct > 0 else DEFAULT_INITIAL_SL_PCT

        side_lower = order.side.lower()
        is_long = ('long' in side_lower) or ('buy' in side_lower)
        side = 'buy' if is_long else 'sell'

        if is_long:
            sl_price = price * (1 - sl_percent)
        else:
            sl_price = price * (1 + sl_percent)

        sl_str = exchange.price_to_precision(sym, sl_price)

        print(f"🛡️ Risk Setup {sym}: Entry~={price}, SL={sl_str} ({-sl_percent*100:.2f}%), qty={final_qty}")

        # 7. Invio Ordine con SL immediato
        res = exchange.create_order(
            sym,
            'market',
            side,
            final_qty,
            params={
                'category': 'linear',
                'stopLoss': sl_str
            }
        )

        print(f"🎉 SUCCESS: {res['id']}")
        return {"status": "executed", "id": res['id'], "symbol": sym, "qty": final_qty}

    except Exception as e:
        print(f"❌ Error: {e}")
        return {"status": "error", "msg": str(e)}

@app.post("/close_position")
def close_position(req: CloseRequest):
    # TODO: qui puoi implementare chiusura automatica (market close) se vuoi
    return {"status": "manual_only"}

@app.post("/manage_active_positions")
def manage():
    # Questa funzione viene chiamata dall'Orchestrator periodicamente.
    # La usiamo per aggiornare i Trailing Stop.
    check_and_update_trailing_stops()
    return {"status": "ok"}
