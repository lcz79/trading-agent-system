import time
import requests
import os
import logging
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from threading import Thread
from pybit.unified_trading import HTTP

# --- CONFIGURAZIONE ---
SLEEP_INTERVAL = 900
MASTER_AI_URL = "http://master-ai-agent:8000"
QTY_PRECISION = {"BTCUSDT": 3, "ETHUSDT": 2, "SOLUSDT": 1}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PositionManager")

app = FastAPI()

# --- FIX CORS (Il pezzo mancante per la Dashboard) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Accetta richieste da TUTTI (Dashboard compresa)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MEMORIA DASHBOARD
management_logs = [] 
equity_history = []

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
IS_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

session = None
try:
    session = HTTP(testnet=IS_TESTNET, api_key=API_KEY, api_secret=API_SECRET)
    logger.info("Connessione Bybit OK")
except Exception as e:
    logger.error(f"Errore Bybit: {e}")

# --- UTILS ---
def add_log(title, message, status="info"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    logger.info(f"{title}: {message}")
    log_entry = {
        "id": int(time.time() * 100000),
        "time": timestamp,
        "pair": title,       
        "action": message,    
        "status": status
    }
    management_logs.insert(0, log_entry)
    if len(management_logs) > 50: management_logs.pop()

def get_wallet_balance_value():
    if not session: return 0.0
    try:
        resp = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        if resp['retCode'] == 0:
            for coin in resp['result']['list'][0]['coin']:
                if coin['coin'] == "USDT": return float(coin['walletBalance'])
    except: pass
    return 0.0

def get_open_positions_data():
    positions = []
    if not session: return positions
    try:
        resp = session.get_positions(category="linear", settleCoin="USDT")
        if resp['retCode'] == 0:
            for p in resp['result']['list']:
                if float(p['size']) > 0:
                    positions.append({
                        "symbol": p['symbol'],
                        "side": p['side'],
                        "size": float(p['size']),
                        "entry_price": float(p['avgPrice']),
                        "pnl": float(p['unrealisedPnl']),
                        "roi": 0.0 
                    })
    except: pass
    return positions

def get_price(symbol):
    if not session: return 0.0
    try:
        resp = session.get_tickers(category="linear", symbol=symbol)
        if resp['retCode'] == 0: return float(resp['result']['list'][0]['markPrice'])
    except: pass
    return 0.0

def execute_trade(symbol, decision, size_pct, leverage):
    if not session: return
    positions = get_open_positions_data()
    target_pos = next((p for p in positions if p['symbol'] == symbol), None)

    if decision == "CLOSE" and target_pos:
        add_log(symbol, "Closing Position...", "warning")
        try:
            side = "Sell" if target_pos['side'] == "Buy" else "Buy"
            session.place_order(category="linear", symbol=symbol, side=side, orderType="Market", qty=str(target_pos['size']), reduceOnly=True)
            add_log(symbol, "Position Closed", "success")
        except Exception as e:
            add_log(symbol, f"Close Error: {e}", "error")
            
    elif "OPEN" in decision and not target_pos:
        add_log(symbol, f"Opening {decision}...", "info")
        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=str(leverage), sellLeverage=str(leverage))
        except: pass

        bal = get_wallet_balance_value()
        price = get_price(symbol)
        if bal > 0 and price > 0:
            raw_qty = (bal * size_pct * leverage * 0.95) / price
            precision = QTY_PRECISION.get(symbol, 3)
            qty = round(raw_qty, precision)
            if precision == 0: qty = int(qty)
            
            side = "Buy" if "LONG" in decision else "Sell"
            try:
                resp = session.place_order(category="linear", symbol=symbol, side=side, orderType="Market", qty=str(qty))
                if resp['retCode'] == 0:
                    add_log(symbol, f"Order Filled: {qty}", "success")
                else:
                    add_log(symbol, f"Order Failed: {resp['retMsg']}", "error")
            except Exception as e:
                 add_log(symbol, f"Order Exception: {e}", "error")

def trading_loop():
    add_log("SYSTEM", "Bot Online (CORS ENABLED). Cycle: 15m", "success")
    while True:
        try:
            market_data = {}
            for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
                p = get_price(sym)
                if p > 0: market_data[sym] = {"price": p}
            
            if market_data:
                try:
                    resp = requests.post(f"{MASTER_AI_URL}/analyze", json={"raw_data": market_data}, timeout=60)
                    if resp.status_code == 200:
                        decisions = resp.json()
                        for sym, dec in decisions.items():
                            d = dec.get("decision", "HOLD")
                            if d != "HOLD":
                                execute_trade(sym, d, 0.1, 5)
                except Exception as e:
                    add_log("AI", f"Analysis Failed: {e}", "error")
            time.sleep(SLEEP_INTERVAL)
        except Exception:
            time.sleep(60)

@app.on_event("startup")
def startup():
    Thread(target=trading_loop, daemon=True).start()

@app.get("/health")
def health(): return {"status": "active"}
@app.get("/get_wallet_balance")
def api_balance(): return {"balance": get_wallet_balance_value()}
@app.get("/get_open_positions")
def api_positions(): return get_open_positions_data()
@app.get("/management_logs")
def api_logs(): return management_logs
@app.get("/stats")
def api_stats(): return {"daily_pnl": 0.00, "win_rate": 0, "total_trades": 0}
@app.get("/equity_history")
def api_equity(): return equity_history
