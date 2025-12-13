import math
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel
from pybit.unified_trading import HTTP

app = FastAPI()
session = HTTP()

class GannRequest(BaseModel):
    symbol: str

@app.post("/analyze_gann")
def analyze(req: GannRequest):
    symbol = req.symbol.upper()
    if "USDT" not in symbol: symbol += "USDT"
    
    try:
        # 1. Prendiamo i dati giornalieri per trovare il ciclo mensile
        resp = session.get_kline(category="linear", symbol=symbol, interval="D", limit=60)
        if not resp or resp.get('retCode') != 0: 
            return {"error": "Bybit API Error"}
        
        result = resp.get('result')
        if not result:
            return {"error": "No result from Bybit"}
            
        data = result.get('list')
        if not data:
            return {"error": "No data from Bybit"}
            
        df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        
        current_price = df['close'].iloc[0]
        
        # 2. Troviamo il Minimo più basso degli ultimi 60 giorni (Start of Cycle)
        low_price = df['low'].min()
        
        # 3. Calcolo Gann Square of 9 (Static Levels)
        # La formula di Gann basa i livelli sulla radice quadrata del minimo + un fattore di rotazione
        # Factor 1 = 180 gradi (Supporto/Resistenza forte)
        # Factor 2 = 360 gradi (Ciclo completo)
        
        root_low = math.sqrt(low_price)
        
        levels = {}
        # Calcoliamo 5 livelli superiori (Resistenze) basati su rotazioni di 180 gradi (0.5 coefficiente ganniano * step)
        for i in range(1, 6):
            # Gann Factor: aggiungiamo incrementi alla radice
            # Ogni +1 sulla radice è un ciclo di 180 gradi sul Quadrato del 9 (approssimazione classica)
            next_root = root_low + i 
            level_price = next_root ** 2
            levels[f"Res_Level_{i} ({(i*180)}deg)"] = round(level_price, 2)

        # Determina il trend di Gann
        # Se siamo sopra il livello di 360 gradi (Level 2), il trend è forte
        trend = "NEUTRAL"
        deg_360 = levels["Res_Level_2 (360deg)"]
        
        if current_price > deg_360:
            trend = "BULLISH_GANN (Above 360deg Cycle)"
        elif current_price < low_price:
            trend = "BEARISH_BREAKDOWN"
        else:
            trend = "ACCUMULATION (Inside Cycle)"

        return {
            "symbol": symbol,
            "current_price": current_price,
            "cycle_start_low": low_price,
            "gann_trend": trend,
            "next_important_levels": levels
        }

    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.get("/health")
def health(): return {"status": "active"}
