import os
import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pybit.unified_trading import HTTP

app = FastAPI(title="Technical Analyzer Agent (Pandas TA)")
@app.get("/health")
def health_check():
    return {"status": "ok"}
# --- ABILITAZIONE CORS (Per la Dashboard) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURAZIONE ---
session = HTTP(testnet=False, api_key=os.getenv("BYBIT_API_KEY"), api_secret=os.getenv("BYBIT_API_SECRET"))

class AnalysisRequest(BaseModel):
    symbol: str
    timeframes: List[str] = ["15", "60", "240"]

class AnalysisResponse(BaseModel):
    symbol: str
    data: Dict[str, Any]

def get_kline_data(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    """Scarica le candele. Limit aumentato a 300 per supportare SMA200."""
    try:
        response = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        if response['retCode'] == 0 and response['result']['list']:
            # Bybit restituisce: [time, open, high, low, close, vol, turnover]
            # I dati sono dal più recente al più vecchio.
            df = pd.DataFrame(response['result']['list'], columns=['time', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
            
            # Invertiamo per avere l'ordine cronologico corretto per Pandas TA
            df = df.iloc[::-1].reset_index(drop=True)
            
            # Convertiamo in numeri
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
                
            return df
    except Exception as e:
        print(f"Error fetching {symbol} {interval}: {e}")
    
    return pd.DataFrame()

@app.post("/analyze_multi_tf", response_model=AnalysisResponse)
def analyze_multi_tf(req: AnalysisRequest):
    results = {}
    
    for tf in req.timeframes:
        df = get_kline_data(req.symbol, tf)
        if df.empty or len(df) < 200:
            continue

        # --- CALCOLO INDICATORI CON PANDAS TA ---
        
        # 1. RSI (14)
        df.ta.rsi(length=14, append=True) # Crea colonna RSI_14
        
        # 2. MACD (12, 26, 9)
        df.ta.macd(fast=12, slow=26, signal=9, append=True) 
        # Crea MACD_12_26_9 (Linea), MACDs_12_26_9 (Signal), MACDh_12_26_9 (Istogramma)
        
        # 3. Bollinger Bands (20, 2)
        df.ta.bbands(length=20, std=2, append=True)
        # Crea BBL_20_2.0 (Lower), BBM_20_2.0 (Mid), BBU_20_2.0 (Upper)
        
        # 4. Medie Mobili (SMA 50 e 200)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=200, append=True)
        
        # 5. ATR (Volatilità)
        df.ta.atr(length=14, append=True)

        # --- ESTRAZIONE DATI SICURI (Ultima candela CHIUSA) ---
        # Usiamo iloc[-2] (penultima) come riferimento sicuro per i segnali
        # Usiamo iloc[-1] (ultima) solo per il prezzo attuale live
        
        curr = df.iloc[-1] # Candela in corso (Live Price)
        closed = df.iloc[-2] # Ultima candela chiusa (Safe Signal)
        prev = df.iloc[-3] # Quella ancora prima (per vedere incroci)

        # Logica Incrocio MACD (sulla candela chiusa)
        macd_line = closed.get('MACD_12_26_9', 0)
        macd_signal = closed.get('MACDs_12_26_9', 0)
        prev_macd_line = prev.get('MACD_12_26_9', 0)
        prev_macd_signal = prev.get('MACDs_12_26_9', 0)
        
        macd_cross = "NEUTRAL"
        if prev_macd_line < prev_macd_signal and macd_line > macd_signal:
            macd_cross = "BULLISH_CROSS"
        elif prev_macd_line > prev_macd_signal and macd_line < macd_signal:
            macd_cross = "BEARISH_CROSS"

        # Logica Trend (Prezzo Chiuso vs SMA 200)
        sma200 = closed.get('SMA_200', 0)
        trend = "NEUTRAL"
        if sma200 > 0:
            trend = "BULLISH" if closed['close'] > sma200 else "BEARISH"

        # --- COSTRUZIONE JSON PER BRAIN & DASHBOARD ---
        results[tf] = {
            "close_price": float(curr['close']), # Prezzo live
            
            "rsi_14": {
                "current": float(closed.get('RSI_14', 50)),
                "previous": float(prev.get('RSI_14', 50))
            },
            
            "macd": {
                "line": float(macd_line),
                "hist": float(closed.get('MACDh_12_26_9', 0)),
                "cross_status": macd_cross
            },
            
            "bollinger": {
                "upper": float(closed.get('BBU_20_2.0', 0)),
                "lower": float(closed.get('BBL_20_2.0', 0)),
                "width_pct": float((closed.get('BBU_20_2.0', 0) - closed.get('BBL_20_2.0', 0)) / closed['close'])
            },
            
            "sma_50": {"current": float(closed.get('SMA_50', 0))},
            "sma_200": {"current": float(sma200)},
            
            "atr_14": float(closed.get('ATRr_14', 0)),
            
            "trend_bias": trend
        }

    return {"symbol": req.symbol, "data": results}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
