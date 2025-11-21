import os
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel
from pybit.unified_trading import HTTP

app = FastAPI(title="Gann Agent")
session = HTTP(testnet=False, api_key=os.getenv("BYBIT_API_KEY"), api_secret=os.getenv("BYBIT_API_SECRET"))

class GannRequest(BaseModel):
    symbol: str
    interval: str = "D"

@app.post("/analyze_gann")
def analyze_gann(request: GannRequest):
    try:
        resp = session.get_kline(category="linear", symbol=request.symbol, interval=request.interval, limit=100)
        if resp['retCode'] != 0: return {}
        
        df = pd.DataFrame(resp['result']['list'], columns=['t','o','h','l','c','v','to'])
        df = df.iloc[::-1].reset_index(drop=True)
        df['l'] = df['l'].astype(float)
        df['h'] = df['h'].astype(float)
        df['c'] = df['c'].astype(float)
        
        curr = df['c'].iloc[-1]
        idx_min = df['l'].idxmin()
        min_val = df['l'].iloc[idx_min]
        
        # Semplice ventaglio rialzista dal minimo
        elapsed = len(df) - 1 - idx_min
        if elapsed < 1: elapsed = 1
        
        # Dynamic Scale: (Prezzo - Min) / Barre
        unit = (curr - min_val) / elapsed if elapsed > 0 else curr*0.01
        if unit <= 0: unit = curr * 0.01
        
        # Angoli principali
        p_1x1 = min_val + (unit * 1.0 * elapsed)
        p_2x1 = min_val + (unit * 2.0 * elapsed) # Ripido (Supporto forte)
        p_1x2 = min_val + (unit * 0.5 * elapsed) # Lento
        
        # Identifica supporto/resistenza immediati
        levels = sorted([p_1x1, p_2x1, p_1x2])
        support = 0.0
        resistance = 0.0
        
        for l in levels:
            if l < curr: support = l
            if l > curr and resistance == 0: resistance = l
            
        return {
            "symbol": request.symbol,
            "support_angle": "Gann Level",
            "support_level": support,
            "resistance_level": resistance,
            "trend_status": "BULLISH" if curr > p_1x1 else "BEARISH"
        }
    except:
        return {}
