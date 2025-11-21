import os
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel
from pybit.unified_trading import HTTP

app = FastAPI(title="Fibonacci Agent")

# Connessione a Bybit (solo per leggere i dati)
session = HTTP(
    testnet=False, 
    api_key=os.getenv("BYBIT_API_KEY"), 
    api_secret=os.getenv("BYBIT_API_SECRET")
)

class FibRequest(BaseModel):
    crypto_symbol: str
    interval: str = "240" # Default: 4 Ore (Ottimale per Swing Trading)

@app.post("/analyze_fibonacci")
def analyze_fib(request: FibRequest):
    try:
        # Scarichiamo 200 candele per avere uno storico affidabile
        resp = session.get_kline(
            category="linear", 
            symbol=request.crypto_symbol, 
            interval=request.interval, 
            limit=200
        )
        
        if resp['retCode'] != 0: 
            return {"current_price": 0, "error": "Bybit error"}
        
        # Creazione DataFrame Pandas
        # Bybit restituisce i dati dal più nuovo al più vecchio, invertiamo con [::-1]
        df = pd.DataFrame(resp['result']['list'], columns=['t','o','h','l','c','v','to'])
        df = df.iloc[::-1].reset_index(drop=True)
        
        # Convertiamo stringhe in numeri
        df['h'] = df['h'].astype(float)
        df['l'] = df['l'].astype(float)
        df['c'] = df['c'].astype(float)
        
        curr_price = df['c'].iloc[-1]
        
        # Troviamo i punti di Swing (Massimo e Minimo assoluti nel periodo)
        idx_max = df['h'].idxmax()
        idx_min = df['l'].idxmin()
        
        swing_high = df['h'].loc[idx_max]
        swing_low = df['l'].loc[idx_min]
        
        # Determiniamo la direzione del trend principale
        # Se il Massimo è più recente del Minimo -> Trend UP (Stiamo ritracciando)
        trend = "UP_TREND" if idx_max > idx_min else "DOWN_TREND"
        diff = swing_high - swing_low
        
        # Calcolo Golden Pocket (Tra il 61.8% e il 65% del movimento)
        in_gp = False
        
        if trend == "UP_TREND":
            # Ritracciamento verso il basso: Supporto Golden Pocket
            gp_top = swing_high - (diff * 0.618)
            gp_bot = swing_high - (diff * 0.65)
            in_gp = gp_bot <= curr_price <= gp_top
        else:
            # Rimbalzo verso l'alto: Resistenza Golden Pocket
            gp_bot = swing_low + (diff * 0.618)
            gp_top = swing_low + (diff * 0.65)
            in_gp = gp_bot <= curr_price <= gp_top
            
        return {
            "symbol": request.crypto_symbol,
            "current_price": curr_price,
            "trend_direction": trend,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "in_golden_pocket": in_gp
        }
    except Exception as e:
        print(f"Fibonacci Error: {e}")
        return {"current_price": 0}
