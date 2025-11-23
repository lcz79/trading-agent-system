import os
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pybit.unified_trading import HTTP

class CryptoSymbol(BaseModel):
    crypto_symbol: str

app = FastAPI()
@app.get("/health")
def health_check():
    return {"status": "ok"}
session = HTTP(testnet=False, api_key=os.getenv("BYBIT_API_KEY"), api_secret=os.getenv("BYBIT_API_SECRET"))

def get_bybit_data(symbol: str, interval: str = 'D', limit: int = 200):
    try:
        response = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        if response['retCode'] == 0 and response['result']['list']:
            df = pd.DataFrame(response['result']['list'], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df.iloc[::-1]
        else:
            # MODIFICA: Restituisce sempre un DataFrame vuoto in caso di problemi, mai None.
            return pd.DataFrame()
    except Exception as e:
        print(f"Errore durante il recupero dei dati da Bybit: {e}")
        # MODIFICA: Restituisce sempre un DataFrame vuoto in caso di problemi, mai None.
        return pd.DataFrame()

@app.post("/analyze_fibonacci")
async def analyze_fibonacci(symbol: CryptoSymbol):
    df = get_bybit_data(symbol.crypto_symbol)
    
    # MODIFICA: Controllo robusto che gestisce il DataFrame vuoto
    if df.empty:
        print(f"Dati non disponibili da Bybit per {symbol.crypto_symbol}. Impossibile calcolare Fibonacci.")
        raise HTTPException(status_code=404, detail=f"Dati non disponibili per {symbol.crypto_symbol}")

    highest_high = df['high'].max()
    lowest_low = df['low'].min()
    swing = highest_high - lowest_low
    current_price = df['close'].iloc[-1]
    
    # Se non c'è swing (prezzo sempre uguale), evita divisione per zero e calcoli inutili.
    if swing == 0:
         return {
            "symbol": symbol.crypto_symbol, "trend": "sideways",
            "current_price": float(current_price), "nearest_support": float(current_price),
            "nearest_resistance": float(current_price),
            "fib_levels": {},
            "in_golden_pocket": False
        }

    fib_levels = {
        'level_0.236': highest_high - (swing * 0.236), 'level_0.382': highest_high - (swing * 0.382),
        'level_0.500': highest_high - (swing * 0.5), 'level_0.618': highest_high - (swing * 0.618),
        'level_0.786': highest_high - (swing * 0.786),
    }

    support_levels = [lvl for lvl in fib_levels.values() if lvl < current_price]
    resistance_levels = [lvl for lvl in fib_levels.values() if lvl > current_price]
    
    nearest_support = max(support_levels) if support_levels else lowest_low
    nearest_resistance = min(resistance_levels) if resistance_levels else highest_high
    
    in_golden_pocket = fib_levels['level_0.618'] <= current_price <= fib_levels['level_0.500']
    trend = "bullish_bias" if current_price > fib_levels['level_0.500'] else "bearish_bias"

    return {
        "symbol": symbol.crypto_symbol, "trend": str(trend),
        "current_price": float(current_price), "nearest_support": float(nearest_support),
        "nearest_resistance": float(nearest_resistance),
        "fib_levels": {key: float(value) for key, value in fib_levels.items()},
        # MODIFICA: Converte esplicitamente il bool di numpy in bool standard di Python
        "in_golden_pocket": bool(in_golden_pocket)
    }

@app.get("/docs")
def read_docs():
    return {"message": "Docs"}
