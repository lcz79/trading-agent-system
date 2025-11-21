import os
import math
from typing import List, Dict, Optional
from decimal import Decimal, ROUND_DOWN

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pybit.unified_trading import HTTP
import pandas as pd
import numpy as np

app = FastAPI(title="AI Trading Agent - ATR Trailing")

# --- CONFIGURAZIONE AVANZATA ---
ATR_PERIOD = 14          # Periodo per il calcolo della volatilità
ATR_MULTIPLIER = 2.5     # Distanza dello Stop Loss in unità di ATR (es. 2.5 volte la volatilità media)
MIN_UPDATE_TICKS = 5     # Aggiorna SL solo se la modifica è > 5 tick (anti-spam)

# --- MODELLI DATI ---

class Position(BaseModel):
    order_id: str
    crypto_symbol: str
    entry_price: float
    decision: str  # 'BUY' (Long) o 'SELL' (Short)

class ManageRequest(BaseModel):
    positions: List[Position]

class Action(BaseModel):
    action: str
    order_id: str
    symbol: str
    new_stop_loss: float
    message: str

# --- INIZIALIZZAZIONE BYBIT ---
api_key = os.getenv("BYBIT_API_KEY")
api_secret = os.getenv("BYBIT_API_SECRET")

if not api_key or not api_secret:
    # Fallback per sviluppo locale (NON USARE IN PRODUZIONE SENZA ENV VARS)
    print("ATTENZIONE: API KEY non trovate, il bot potrebbe non funzionare.")

session = HTTP(
    testnet=False, 
    api_key=api_key,
    api_secret=api_secret,
)

# --- CACHE STRUMENTI (Tick Size) ---
# Memorizziamo le info sugli strumenti per non richiederle a ogni ciclo
instrument_cache: Dict[str, float] = {}

def get_tick_size(symbol: str) -> float:
    """
    Recupera e cacha il 'tick size' (minimo incremento di prezzo) per un simbolo.
    Essenziale per evitare l'errore 'Invalid Price Precision'.
    """
    if symbol in instrument_cache:
        return instrument_cache[symbol]
    
    try:
        # Scarichiamo le info dello strumento
        resp = session.get_instruments_info(category="linear", symbol=symbol)
        if resp['retCode'] == 0:
            tick = float(resp['result']['list'][0]['priceFilter']['tickSize'])
            instrument_cache[symbol] = tick
            return tick
    except Exception as e:
        print(f"[WARN] Errore tick size per {symbol}: {e}")
    
    return 0.01  # Fallback di sicurezza

def round_to_tick(price: float, tick_size: float) -> float:
    """Arrotonda il prezzo al multiplo più vicino del tick size."""
    if tick_size == 0: return price
    d_price = Decimal(str(price))
    d_tick = Decimal(str(tick_size))
    rounded = d_price.quantize(d_tick, rounding=ROUND_DOWN)
    return float(rounded)

# --- LOGICA FINANZIARIA (ATR) ---

def fetch_and_calculate_atr(symbol: str, interval: str = "60") -> float:
    """
    Scarica le candele (kline) da Bybit e calcola l'ATR corrente.
    interval="60" significa candele da 1 ora.
    """
    try:
        # Scarichiamo 2 volte il periodo necessario per avere dati stabili (es. 30 candele)
        resp = session.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=ATR_PERIOD * 2
        )
        
        if resp['retCode'] != 0:
            return 0.0

        # Parsing dati Bybit: [startTime, open, high, low, close, volume, ...]
        # Creiamo DataFrame Pandas
        data = resp['result']['list']
        if not data: 
            return 0.0
            
        # I dati Bybit arrivano dal più recente al più vecchio, invertiamoli per Pandas
        df = pd.DataFrame(data, columns=['startTime', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
        df = df.iloc[::-1].reset_index(drop=True)
        
        # Convertiamo stringhe in float
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)

        # Calcolo True Range (TR)
        # TR = max(high-low, abs(high-prev_close), abs(low-prev_close))
        df['prev_close'] = df['close'].shift(1)
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = (df['high'] - df['prev_close']).abs()
        df['tr3'] = (df['low'] - df['prev_close']).abs()
        
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        # Calcolo ATR (Media mobile del TR)
        df['atr'] = df['tr'].rolling(window=ATR_PERIOD).mean()
        
        # Restituiamo l'ultimo ATR disponibile
        last_atr = df['atr'].iloc[-1]
        
        if np.isnan(last_atr):
            return 0.0
            
        return float(last_atr)

    except Exception as e:
        print(f"[ERR] Errore calcolo ATR per {symbol}: {e}")
        return 0.0

# --- ENDPOINT PRINCIPALE ---

@app.post("/manage", response_model=List[Action])
def manage_positions(request: ManageRequest) -> List[Action]:
    if not request.positions:
        return []

    actions: List[Action] = []
    
    # 1. Identifica i simboli unici per ottimizzare le chiamate
    symbols = list({p.crypto_symbol for p in request.positions})
    
    # 2. Batch Fetching: Prezzi attuali e Posizioni Bybit reali
    market_prices = {}
    real_positions_map = {}

    try:
        # A) Ottieni prezzi (Tickers)
        tickers_resp = session.get_tickers(category="linear") # Prende tutto (più veloce che fare loop)
        if tickers_resp['retCode'] == 0:
            for t in tickers_resp['result']['list']:
                if t['symbol'] in symbols:
                    market_prices[t['symbol']] = float(t['lastPrice'])

        # B) Ottieni posizioni attive (Real Positions)
        pos_resp = session.get_positions(category="linear", settleCoin="USDT")
        if pos_resp['retCode'] == 0:
            for p in pos_resp['result']['list']:
                # Chiave unica: Symbol + Side
                key = f"{p['symbol']}_{p['side']}"
                real_positions_map[key] = p
                
    except Exception as e:
        print(f"[CRITICAL] Errore comunicazione Bybit: {e}")
        raise HTTPException(status_code=502, detail="Errore connessione exchange")

    # 3. Analisi Posizioni
    for pos_req in request.positions:
        current_price = market_prices.get(pos_req.crypto_symbol)
        if not current_price: continue

        side_bybit = "Buy" if pos_req.decision.upper() == "BUY" else "Sell"
        
        # Trova la posizione reale corrispondente
        real_pos = real_positions_map.get(f"{pos_req.crypto_symbol}_{side_bybit}")
        
        # Se la posizione non esiste realmente o size=0, salta
        if not real_pos or float(real_pos['size']) == 0:
            continue
            
        # Ottieni Stop Loss attuale (se esiste)
        current_sl_raw = real_pos.get("stopLoss", "0")
        current_sl = float(current_sl_raw) if current_sl_raw and current_sl_raw != "" else 0.0
        
        # --- CALCOLO ATR (Intelligenza Volatilità) ---
        # Se l'ATR fallisce, usiamo un fallback del 2% fisso
        atr_value = fetch_and_calculate_atr(pos_req.crypto_symbol)
        
        if atr_value > 0:
            trailing_distance = atr_value * ATR_MULTIPLIER
            strategy_name = "ATR Trailing"
        else:
            trailing_distance = current_price * 0.02  # Fallback 2%
            strategy_name = "Fixed 2% (ATR Fallback)"

        # Ottieni Tick Size per arrotondamento
        tick_size = get_tick_size(pos_req.crypto_symbol)

        # --- LOGICA TRAILING ---
        
        if side_bybit == "Buy":
            # LONG: Stop Loss = Prezzo Attuale - Distanza
            potential_new_sl = current_price - trailing_distance
            
            # Arrotonda
            potential_new_sl = round_to_tick(potential_new_sl, tick_size)
            
            # Regole per aggiornare LONG:
            # 1. Nuovo SL deve essere > del vecchio SL (saliamo soltanto)
            # 2. Nuovo SL deve essere > Prezzo Ingresso (Break Even garantito)
            # 3. Anti-Spam: La differenza deve essere > X tick
            
            if (potential_new_sl > current_sl) and (potential_new_sl > pos_req.entry_price):
                diff = potential_new_sl - current_sl
                if diff > (tick_size * MIN_UPDATE_TICKS):
                    actions.append(Action(
                        action="update_stop_loss",
                        order_id=pos_req.order_id,
                        symbol=pos_req.crypto_symbol,
                        new_stop_loss=potential_new_sl,
                        message=f"[{strategy_name}] Profit Locked. P: {current_price} -> New SL: {potential_new_sl}"
                    ))

        elif side_bybit == "Sell":
            # SHORT: Stop Loss = Prezzo Attuale + Distanza
            potential_new_sl = current_price + trailing_distance
            potential_new_sl = round_to_tick(potential_new_sl, tick_size)
            
            # Regole per aggiornare SHORT:
            # 1. Nuovo SL < vecchio SL (scendiamo soltanto) oppure vecchio SL è 0
            # 2. Nuovo SL < Prezzo Ingresso
            
            is_improvement = (current_sl == 0.0) or (potential_new_sl < current_sl)
            
            if is_improvement and (potential_new_sl < pos_req.entry_price):
                # Verifica anti-spam (se SL attuale è 0, aggiorna sempre)
                diff = abs(current_sl - potential_new_sl)
                if (current_sl == 0.0) or (diff > (tick_size * MIN_UPDATE_TICKS)):
                    actions.append(Action(
                        action="update_stop_loss",
                        order_id=pos_req.order_id,
                        symbol=pos_req.crypto_symbol,
                        new_stop_loss=potential_new_sl,
                        message=f"[{strategy_name}] Profit Locked. P: {current_price} -> New SL: {potential_new_sl}"
                    ))

    return actions

@app.get("/")
def root():
    return {"status": "active", "agent": "ATR Smart Trailing v2.0"}
