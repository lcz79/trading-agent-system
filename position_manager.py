import time
import requests
import os
import logging
from datetime import datetime
from fastapi import FastAPI
from threading import Thread
from pybit.unified_trading import HTTP
from pydantic import BaseModel

# --- CONFIGURAZIONE ---
SLEEP_INTERVAL = 900  # 15 Minuti (Ciclo AI Master)
FAST_CHECK_INTERVAL = 30 # 30 Secondi (Ciclo Guardiano SL)

MASTER_AI_URL = "http://master-ai-agent:8000"
TARGET_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# Precisione decimali per Qty e Prezzo (SL/TP)
QTY_PRECISION = {"BTCUSDT": 3, "ETHUSDT": 2, "SOLUSDT": 1}
PRICE_PRECISION = {"BTCUSDT": 1, "ETHUSDT": 2, "SOLUSDT": 3}

# --- GESTIONE RISCHIO ---
DEFAULT_SL_PERCENT = 0.02  # 2% Stop Loss iniziale
DEFAULT_TP_PERCENT = 0.05  # 5% Take Profit iniziale (Risk:Reward 1:2.5)

# --- BREAK EVEN (Pareggio Dinamico) ---
BE_TRIGGER_PCT = 0.008 # Se il prezzo va a +0.8% a favore...
BE_OFFSET_PCT = 0.001  # ...sposta lo SL a +0.1% (così paghiamo le commissioni)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PositionManager")
app = FastAPI()

# LOGS
management_logs = [] 
equity_history = [] 

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
IS_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

session = None
try:
    session = HTTP(testnet=IS_TESTNET, api_key=API_KEY, api_secret=API_SECRET)
except: pass

class CloseRequest(BaseModel):
    symbol: str

def add_log(title, message, status="info"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {title}: {message}")
    management_logs.insert(0, {"id": int(time.time()*1000), "time": timestamp, "pair": title, "action": message, "status": status})
    if len(management_logs) > 100: management_logs.pop()

def get_wallet_data():
    if not session: return 0.0, []
    bal = 0.0
    pos = []
    try:
        r = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        if r['retCode'] == 0:
            bal = float(r['result']['list'][0]['coin'][0]['walletBalance'])
        r2 = session.get_positions(category="linear", settleCoin="USDT")
        if r2['retCode'] == 0:
            for p in r2['result']['list']:
                if float(p['size']) > 0:
                    pos.append({
                        "symbol": p['symbol'],
                        "side": p['side'],
                        "size": float(p['size']),
                        "entry_price": float(p['avgPrice']),
                        "leverage": float(p['leverage']),
                        "pnl": float(p['unrealisedPnl']),
                        "stop_loss": float(p.get('stopLoss', 0)),
                        "take_profit": float(p.get('takeProfit', 0)),
                        "mark_price": float(p['markPrice'])
                    })
    except: pass
    return bal, pos

def get_price(sym):
    try:
        r = session.get_tickers(category="linear", symbol=sym)
        return float(r['result']['list'][0]['markPrice'])
    except: return 0.0

def calculate_sl_tp(entry_price, direction, sl_pct, tp_pct, precision):
    """Calcola prezzi esatti per SL e TP in base alla direzione"""
    if direction == "long":
        sl = entry_price * (1 - sl_pct)
        tp = entry_price * (1 + tp_pct)
    else: # short
        sl = entry_price * (1 + sl_pct)
        tp = entry_price * (1 - tp_pct)
    
    return round(sl, precision), round(tp, precision)

# --- GUARDIANO VELOCE (Thread Parallelo) ---
def monitor_positions():
    """Controlla ogni 30s se dobbiamo spostare lo SL a pareggio"""
    time.sleep(60) # Aspetta 1 minuto all'avvio
    add_log("GUARDIAN", "Break-Even Monitor Active", "success")
    
    while True:
        try:
            _, positions = get_wallet_data()
            
            for p in positions:
                sym = p['symbol']
                side = p['side']
                entry = p['entry_price']
                curr_price = p['mark_price']
                curr_sl = p['stop_loss']
                precision = PRICE_PRECISION.get(sym, 2)

                # LOGICA LONG
                if side == "Buy":
                    # Se il prezzo è salito sopra il trigger (es. +0.8%)
                    target_trigger = entry * (1 + BE_TRIGGER_PCT)
                    new_sl = round(entry * (1 + BE_OFFSET_PCT), precision)
                    
                    if curr_price > target_trigger:
                        # Controlla se abbiamo già spostato lo SL (per non spammare API)
                        # Se current SL è 0 o è minore del new_sl, lo alziamo
                        if curr_sl == 0 or curr_sl < new_sl: 
                            add_log(sym, f"Moving SL to Break Even ()", "warning")
                            try:
                                session.set_trading_stop(category="linear", symbol=sym, stopLoss=str(new_sl), slTriggerBy="MarkPrice")
                            except Exception as e:
                                logger.error(f"Failed move SL {sym}: {e}")

                # LOGICA SHORT
                elif side == "Sell":
                    # Se il prezzo è sceso sotto il trigger (es. -0.8%)
                    target_trigger = entry * (1 - BE_TRIGGER_PCT)
                    new_sl = round(entry * (1 - BE_OFFSET_PCT), precision)
                    
                    if curr_price < target_trigger:
                        # Controlla se abbiamo già spostato lo SL
                        # Se current SL è 0 o è maggiore del new_sl, lo abbassiamo
                        if curr_sl == 0 or curr_sl > new_sl: 
                            add_log(sym, f"Moving SL to Break Even ()", "warning")
                            try:
                                session.set_trading_stop(category="linear", symbol=sym, stopLoss=str(new_sl), slTriggerBy="MarkPrice")
                            except Exception as e:
                                logger.error(f"Failed move SL {sym}: {e}")
            
            time.sleep(FAST_CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Guardian Error: {e}")
            time.sleep(60)

def execute_decision(decision):
    sym = decision.get("symbol") + "USDT"
    op = decision.get("operation", "hold").lower()
    direct = decision.get("direction", "").lower()
    lev = int(decision.get("leverage", 1))
    size_pct = float(decision.get("target_portion_of_balance", 0.0))
    reason = decision.get("reason", "")

    logger.info(f"EXEC: {sym} -> {op.upper()} ({reason[:40]}...)")
    
    if op == "hold": return

    bal, positions = get_wallet_data()
    my_pos = next((p for p in positions if p['symbol'] == sym), None)

    # --- MODIFICA: CHIUSURA AUTOMATICA DISABILITATA ---
    if op == "close" and my_pos:
        # Invece di chiudere, logghiamo solo che l'AI lo avrebbe voluto fare
        add_log(sym, f"AI SIGNAL: Close requested but IGNORED (Auto-Close Disabled)", "warning")
        return # Esce dalla funzione senza chiudere

    # --- APERTURA con SL/TP ---
    elif op == "open" and not my_pos:
        try:
            session.set_leverage(category="linear", symbol=sym, buyLeverage=str(lev), sellLeverage=str(lev))
        except: pass
        
        bal, _ = get_wallet_data()
        price = get_price(sym)
        if price == 0 or bal < 10: return

        # 1. Calcola Quantità
        amount = (bal * size_pct * lev * 0.95) / price
        qty_prec = QTY_PRECISION.get(sym, 3)
        qty = f"{amount:.{qty_prec}f}"
        
        # 2. Calcola SL e TP Dinamici
        adjusted_sl = DEFAULT_SL_PERCENT / (lev / 2) if lev > 2 else DEFAULT_SL_PERCENT
        adjusted_tp = DEFAULT_TP_PERCENT / (lev / 2) if lev > 2 else DEFAULT_TP_PERCENT
        
        price_prec = PRICE_PRECISION.get(sym, 2)
        sl_price, tp_price = calculate_sl_tp(price, direct, adjusted_sl, adjusted_tp, price_prec)
        
        side = "Buy" if direct == "long" else "Sell"
        
        add_log(sym, f"Opening {direct.upper()} x{lev} | SL: {sl_price} TP: {tp_price}", "info")

        try:
            r = session.place_order(
                category="linear", 
                symbol=sym, 
                side=side, 
                orderType="Market", 
                qty=qty,
                stopLoss=str(sl_price),
                takeProfit=str(tp_price)
            )
            if r['retCode'] == 0: 
                add_log(sym, f"OPENED {direct.upper()} with SL/TP", "success")
            else: 
                add_log(sym, f"Open Rejected: {r['retMsg']}", "error")
        except Exception as e: 
            add_log(sym, f"Open Fail: {e}", "error")

def trading_cycle():
    add_log("SYSTEM", "Smart Batch Engine Started (15m Cycle)", "success")
    while True:
        try:
            bal, pos = get_wallet_data()
            equity_history.append({"time": datetime.now().strftime("%H:%M"), "equity": bal})
            if len(equity_history) > 50: equity_history.pop(0)
            
            payload = {
                "symbols": TARGET_SYMBOLS,
                "portfolio": {"balance_usd": bal, "open_positions": pos}
            }
            
            add_log("AI", "Calling Mitragliere Master Brain...", "info")
            resp = requests.post(f"{MASTER_AI_URL}/execute_batch_strategy", json=payload, timeout=180)
            
            if resp.status_code == 200:
                data = resp.json()
                trades = data.get("trades", []) 
                if not trades: add_log("AI", "Mitragliere says: HOLD position.", "info")
                for trade in trades: execute_decision(trade)
            else:
                add_log("AI", f"API Error: {resp.status_code}", "error")
            
            add_log("SYSTEM", f"Cycle Done. Sleeping 15m...", "info")
            time.sleep(SLEEP_INTERVAL)
            
        except Exception as e:
            add_log("CRASH", f"{e}", "error")
            time.sleep(60)

@app.on_event("startup")
def startup():
    # Avviamo DUE thread: uno per l'AI (lento) e uno per il Guardiano (veloce)
    Thread(target=trading_cycle, daemon=True).start()
    Thread(target=monitor_positions, daemon=True).start()

# --- ENDPOINTS API ---
@app.get("/health")
def health(): return {"status": "active"}

@app.get("/management_logs")
def logs(): return management_logs

@app.get("/get_wallet_balance")
def api_balance(): 
    b, _ = get_wallet_data()
    return {"balance": b}

@app.get("/get_open_positions")
def api_positions():
    _, p = get_wallet_data()
    return p

@app.get("/equity_history")
def api_equity(): return equity_history

@app.post("/close_position")
def manual_close(req: CloseRequest):
    # --- MODIFICA: CHIUSURA MANUALE DISABILITATA ---
    symbol = req.symbol
    add_log("MANUAL", f"Manual close request for {symbol} REJECTED (Disabled in code)", "error")
    return {"status": "error", "message": "Manual closing disabled by configuration"}

@app.post("/manage_active_positions")
def manage_compat(): return {"status": "ok"}
