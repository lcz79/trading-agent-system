import os
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pybit.unified_trading import HTTP
from decimal import Decimal, ROUND_DOWN
import uvicorn

app = FastAPI(title="Position Manager (ATR Trailing)")

# --- ABILITAZIONE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok"}

# --- CONFIGURAZIONE ---
session = HTTP(
    testnet=False, 
    api_key=os.getenv("BYBIT_API_KEY"), 
    api_secret=os.getenv("BYBIT_API_SECRET")
)

# Cache per evitare di chiedere il tick size ogni volta
instrument_info_cache = {}

# --- MODELLI DATI ---
class Position(BaseModel):
    symbol: str
    side: str
    entry_price: float
    stop_loss: float = 0.0

class ManageRequest(BaseModel):
    positions: List[Position] = [] # Opzionale

class Action(BaseModel):
    action: str = "update_stop_loss"
    symbol: str
    new_stop_loss: float
    message: str

# --- HELPER FUNCTIONS ---

def get_tick_size(symbol: str) -> float:
    """Recupera la precisione minima del prezzo per il simbolo."""
    if symbol in instrument_info_cache:
        return instrument_info_cache[symbol]
    try:
        resp = session.get_instruments_info(category="linear", symbol=symbol)
        if resp['retCode'] == 0:
            tick = float(resp['result']['list'][0]['priceFilter']['tickSize'])
            instrument_info_cache[symbol] = tick
            return tick
    except Exception as e:
        print(f"Error fetching tick size for {symbol}: {e}")
    return 0.01 # Fallback

def round_price(price: float, tick_size: float) -> float:
    """Arrotonda il prezzo al tick size corretto."""
    if tick_size == 0: return price
    d_price = Decimal(str(price))
    d_tick = Decimal(str(tick_size))
    rounded = d_price.quantize(d_tick, rounding=ROUND_DOWN)
    return float(rounded)

def calculate_atr_stop(symbol: str, side: str, entry_price: float, interval: str = '60') -> float:
    """Calcola il livello di Stop basato sull'ATR."""
    try:
        # Scarichiamo le ultime 30 candele (bastano per ATR 14)
        resp = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=30)
        if resp['retCode'] != 0: return 0.0
        
        df = pd.DataFrame(resp['result']['list'], columns=['t','o','h','l','c','v','to'])
        df = df.iloc[::-1].reset_index(drop=True)
        
        for c in ['h','l','c']: df[c] = df[c].astype(float)
        
        # Calcolo True Range
        df['prev_c'] = df['c'].shift(1)
        df['tr1'] = df['h'] - df['l']
        df['tr2'] = (df['h'] - df['prev_c']).abs()
        df['tr3'] = (df['l'] - df['prev_c']).abs()
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        # ATR 14
        df['atr'] = df['tr'].rolling(window=14).mean()
        current_atr = df['atr'].iloc[-1]
        
        if np.isnan(current_atr): return 0.0
        
        # Moltiplicatore ATR (2.5 è standard per swing trading)
        multiplier = 2.5
        
        if side == "Buy":
            # Per i Long, lo stop sale: Prezzo Corrente - (ATR * Mult)
            current_price = df['c'].iloc[-1]
            stop_price = current_price - (current_atr * multiplier)
        else:
            # Per gli Short, lo stop scende: Prezzo Corrente + (ATR * Mult)
            current_price = df['c'].iloc[-1]
            stop_price = current_price + (current_atr * multiplier)
            
        return stop_price
        
    except Exception as e:
        print(f"ATR Calc Error for {symbol}: {e}")
        return 0.0

# --- ENDPOINTS ---

@app.get("/get_open_positions")
def get_open_positions():
    """Restituisce una lista dei simboli con posizioni aperte su Bybit"""
    try:
        resp = session.get_positions(category="linear", settleCoin="USDT")
        open_positions = []
        if resp['retCode'] == 0:
            for p in resp['result']['list']:
                if float(p['size']) > 0:
                    open_positions.append(p['symbol'])
        return {"open_positions": open_positions}
    except Exception as e:
        print(f"Error getting positions: {e}")
        return {"open_positions": []}

@app.post("/manage", response_model=List[Action])
def manage_positions(request: ManageRequest):
    
    positions_to_check = []
    
    # 1. Se la richiesta è vuota, scarichiamo le posizioni reali da Bybit
    if not request.positions:
        try:
            resp = session.get_positions(category="linear", settleCoin="USDT")
            if resp['retCode'] == 0:
                for p in resp['result']['list']:
                    if float(p['size']) > 0:
                        positions_to_check.append(Position(
                            symbol=p['symbol'],
                            side=p['side'], # "Buy" o "Sell"
                            entry_price=float(p['avgPrice']),
                            stop_loss=float(p['stopLoss']) if p['stopLoss'] != "" else 0.0
                        ))
        except Exception as e:
            print(f"Bybit Positions Error: {e}")
            return []
    else:
        positions_to_check = request.positions

    actions = []

    # 2. Analisi per ogni posizione
    for pos in positions_to_check:
        # Calcolo nuovo SL ideale basato su ATR
        potential_sl = calculate_atr_stop(pos.symbol, pos.side, pos.entry_price)
        
        if potential_sl == 0: continue # Errore calcolo ATR
        
        # Arrotondamento al Tick Size (CRUCIALE)
        tick_size = get_tick_size(pos.symbol)
        new_sl = round_price(potential_sl, tick_size)
        
        should_update = False
        
        if pos.side == "Buy":
            # Aggiorna SOLO se il nuovo SL è più alto del vecchio (Trail UP)
            if new_sl > pos.stop_loss:
                # Filtro Anti-Spam: Aggiorna solo se la differenza è > 5 tick
                if (new_sl - pos.stop_loss) > (tick_size * 5):
                    should_update = True
                    
        elif pos.side == "Sell":
            # Aggiorna SOLO se il nuovo SL è più basso del vecchio (Trail DOWN)
            # O se non c'era stop loss (0)
            if pos.stop_loss == 0 or new_sl < pos.stop_loss:
                if pos.stop_loss == 0 or (pos.stop_loss - new_sl) > (tick_size * 5):
                    should_update = True
        
        if should_update:
            print(f"Updating SL for {pos.symbol} to {new_sl}")
            try:
                # Eseguiamo l'aggiornamento su Bybit
                session.set_trading_stop(
                    category="linear",
                    symbol=pos.symbol,
                    stopLoss=str(new_sl),
                    positionIdx=0
                )
                actions.append(Action(
                    symbol=pos.symbol,
                    new_stop_loss=new_sl,
                    message=f"ATR Trailing: SL moved to {new_sl}"
                ))
            except Exception as e:
                print(f"Error updating SL on Bybit: {e}")

    return actions

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
