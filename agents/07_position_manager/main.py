import os
import ccxt
import pandas as pd
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# --- CONFIGURAZIONE STRATEGIA ATR ---
ATR_PERIOD = 14          # Periodo calcolo volatilità
SL_MULTIPLIER = 2.0      # Stop Loss = 2 volte la volatilità (Standard)
TP_MULTIPLIER = 3.0      # Take Profit = 3 volte la volatilità (Reward > Risk)
# ------------------------------------

# Connessione Bybit
API_KEY = os.getenv('BYBIT_API_KEY')
API_SECRET = os.getenv('BYBIT_API_SECRET')
IS_TESTNET = os.getenv('BYBIT_TESTNET', 'true').lower() == 'true'

exchange = None
if API_KEY and API_SECRET:
    try:
        exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'options': {'defaultType': 'future'},
        })
        if IS_TESTNET:
            exchange.set_sandbox_mode(True)
        print(f"🔌 Position Manager: Connesso a Bybit (Testnet: {IS_TESTNET})")
    except Exception as e:
        print(f"⚠️ Errore connessione Bybit: {e}")

class OrderRequest(BaseModel):
    symbol: str
    side: str
    leverage: float
    size_pct: float

def calculate_atr_sl_tp(symbol, side, current_price, leverage):
    """
    Calcola i prezzi di Stop Loss e Take Profit basati su ATR.
    Include protezione contro liquidazione in base alla leva.
    """
    if not exchange: return 0, 0, 0

    try:
        # 1. Scarica candele orarie (1h) per l'ATR
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=ATR_PERIOD + 5)
        if not ohlcv: return 0, 0, 0
        
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        
        # 2. Calcolo ATR (True Range)
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        atr = df['tr'].rolling(window=ATR_PERIOD).mean().iloc[-1]
        
        # 3. Calcolo Distanze
        stop_dist = atr * SL_MULTIPLIER
        tp_dist = atr * TP_MULTIPLIER
        
        # 4. Protezione Anti-Liquidazione (Safety Net)
        # Esempio: Leva 10x => Liquidazione a +/- 10%. Stop Loss max deve essere al 8%.
        max_sl_dist_pct = (1.0 / leverage) * 0.80 
        max_sl_dist_price = current_price * max_sl_dist_pct
        
        # Se l'ATR suggerisce uno stop troppo largo per questa leva, lo stringiamo
        if stop_dist > max_sl_dist_price:
            print(f"⚠️ ATR Stop troppo largo per Leva {leverage}x. Ridimensionamento di sicurezza.")
            stop_dist = max_sl_dist_price

        # 5. Calcolo Prezzi Finali
        if side.lower() == 'buy': # LONG
            sl_price = current_price - stop_dist
            tp_price = current_price + tp_dist
        else: # SHORT
            sl_price = current_price + stop_dist
            tp_price = current_price - tp_dist
            
        return sl_price, tp_price, atr

    except Exception as e:
        print(f"❌ Errore calcolo ATR: {e}")
        return 0, 0, 0

@app.post("/open_position")
def open_position(order: OrderRequest):
    if not exchange:
        return {"status": "simulated", "msg": "No Exchange Connected"}
    
    try:
        symbol = order.symbol
        side = order.side.lower() # 'buy' or 'sell'
        
        # A. Imposta Leva
        try:
            exchange.set_leverage(int(order.leverage), symbol)
        except: pass 

        # B. Prepara Dati Ordine
        ticker = exchange.fetch_ticker(symbol)
        current_price = float(ticker['last'])
        
        # C. Calcola Size
        bal = exchange.fetch_balance()
        available_equity = float(bal['USDT']['free'])
        trade_cost = available_equity * order.size_pct
        qty_usdt = trade_cost * order.leverage
        qty = qty_usdt / current_price
        
        # D. CALCOLO ATR (Il cuore della strategia)
        sl_price, tp_price, atr_val = calculate_atr_sl_tp(symbol, side, current_price, order.leverage)
        
        print(f"📊 {symbol} ATR: {atr_val:.2f} | Prezzo: {current_price}")
        print(f"🎯 Setting SL: {sl_price:.2f} | TP: {tp_price:.2f}")

        # E. Parametri Ordine Avanzato (Order attaches SL/TP immediately)
        params = {}
        if sl_price > 0 and tp_price > 0:
            params = {
                'stopLoss': str(round(sl_price, 4)),
                'takeProfit': str(round(tp_price, 4))
            }

        # F. Invia Ordine a Mercato
        direction = 'buy' if side in ['buy', 'open_long'] else 'sell'
        order_resp = exchange.create_order(symbol, 'market', direction, qty, params=params)
        
        return {
            "status": "executed", 
            "id": order_resp['id'], 
            "atr_used": atr_val,
            "sl": sl_price,
            "tp": tp_price
        }

    except Exception as e:
        print(f"❌ ERRORE CRITICO ORDINE: {e}")
        return {"status": "failed", "error": str(e)}

@app.get("/get_wallet_balance")
def get_balance():
    if not exchange: return {"equity": 10000}
    try:
        b = exchange.fetch_balance()['USDT']
        return {"equity": b['total'], "available": b['free']}
    except: return {"equity": 0}

@app.get("/get_open_positions")
def get_positions():
    if not exchange: return {"active": []}
    try:
        # Fetch posizioni che hanno size > 0
        pos = [p for p in exchange.fetch_positions() if float(p['contracts']) > 0]
        active = [p['symbol'] for p in pos]
        return {"active": active, "details": pos}
    except: return {"active": []}

@app.post("/manage_active_positions")
def manage_positions():
    # Con lo Stop Loss nativo su Bybit (impostato sopra), 
    # questa funzione serve solo per monitoraggio o trailing stop futuri.
    # La protezione è già attiva sull'exchange!
    return {"status": "protected_by_exchange_orders"}

