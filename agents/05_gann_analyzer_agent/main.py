import os
import pandas as pd
import numpy as np
from typing import Dict, Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pybit.unified_trading import HTTP

app = FastAPI(title="Gann Fan Agent")

# --- ABILITAZIONE CORS (Obbligatorio per la Dashboard) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURAZIONE ---
session = HTTP(
    testnet=False, 
    api_key=os.getenv("BYBIT_API_KEY"), 
    api_secret=os.getenv("BYBIT_API_SECRET")
)

class GannRequest(BaseModel):
    symbol: str
    interval: str = "D" # Gann funziona meglio su Daily (D) o 4H (240)

@app.post("/analyze_gann")
def analyze_gann(request: GannRequest):
    try:
        # 1. Scarichiamo dati storici (150 candele bastano per cicli recenti)
        resp = session.get_kline(
            category="linear", 
            symbol=request.symbol, 
            interval=request.interval, 
            limit=150
        )
        
        if resp['retCode'] != 0: return {}
        
        # DataFrame Pandas
        df = pd.DataFrame(resp['result']['list'], columns=['t','o','h','l','c','v','to'])
        df = df.iloc[::-1].reset_index(drop=True)
        
        # Conversione numerica
        df['h'] = df['h'].astype(float)
        df['l'] = df['l'].astype(float)
        df['c'] = df['c'].astype(float)
        
        curr_price = df['c'].iloc[-1]
        
        # 2. Trova Pivot (Massimo e Minimo Assoluti nel periodo)
        idx_max = df['h'].idxmax()
        idx_min = df['l'].idxmin()
        
        high_val = df['h'].loc[idx_max]
        low_val = df['l'].loc[idx_min]
        
        # 3. Logica Ancoraggio Intelligente
        # Determiniamo se il ciclo dominante è Rialzista o Ribassista
        # basandoci su quale pivot è avvenuto prima.
        
        anchor_price = 0.0
        anchor_idx = 0
        mode = "" # "FAN_UP" o "FAN_DOWN"
        
        if idx_min < idx_max:
            # Il Minimo è più vecchio del Massimo -> Trend UP
            # Ancoriamo il ventaglio al Minimo (Low)
            anchor_price = low_val
            anchor_idx = idx_min
            target_price = high_val
            target_idx = idx_max
            mode = "FAN_UP_FROM_LOW"
        else:
            # Il Massimo è più vecchio del Minimo -> Trend DOWN
            # Ancoriamo il ventaglio al Massimo (High)
            anchor_price = high_val
            anchor_idx = idx_max
            target_price = low_val
            target_idx = idx_min
            mode = "FAN_DOWN_FROM_HIGH"
            
        # 4. Calcolo Scala Dinamica (La "Unit" di Gann)
        # Calcoliamo la velocità reale del trend tra i due pivot.
        # Pendenza = (Prezzo Target - Prezzo Anchor) / Tempo
        
        bars_diff = target_idx - anchor_idx
        if bars_diff == 0: bars_diff = 1
        
        unit_1x1 = abs(target_price - anchor_price) / bars_diff
        
        # 5. Proiezione Angoli ad OGGI
        elapsed_since_anchor = len(df) - 1 - anchor_idx
        
        ratios = {
            "1x1": 1.0, "2x1": 2.0, "3x1": 3.0, "4x1": 4.0,
            "1x2": 0.5, "1x3": 0.33, "1x4": 0.25
        }
        
        levels = {}
        
        for name, ratio in ratios.items():
            if mode == "FAN_UP_FROM_LOW":
                # Ventaglio sale: Anchor + (Unit * Ratio * Tempo)
                price = anchor_price + (unit_1x1 * ratio * elapsed_since_anchor)
            else:
                # Ventaglio scende: Anchor - (Unit * Ratio * Tempo)
                price = anchor_price - (unit_1x1 * ratio * elapsed_since_anchor)
            
            levels[name] = price

        # 6. Trova Supporto e Resistenza più vicini (Bracket)
        sorted_levels = sorted(levels.items(), key=lambda x: x[1])
        
        closest_support = 0.0
        closest_resistance = 0.0
        support_name = "None"
        resistance_name = "None"
        
        # Cerchiamo i due livelli che "intrappolano" il prezzo attuale
        for i in range(len(sorted_levels) - 1):
            lvl_low = sorted_levels[i]
            lvl_high = sorted_levels[i+1]
            
            if lvl_low[1] <= curr_price <= lvl_high[1]:
                closest_support = lvl_low[1]
                support_name = lvl_low[0]
                
                closest_resistance = lvl_high[1]
                resistance_name = lvl_high[0]
                break
        
        # Casi fuori scala (Sopra tutto o Sotto tutto)
        if curr_price > sorted_levels[-1][1]:
            closest_support = sorted_levels[-1][1]
            support_name = sorted_levels[-1][0]
            resistance_name = "Sky"
        if curr_price < sorted_levels[0][1]:
            closest_resistance = sorted_levels[0][1]
            resistance_name = sorted_levels[0][0]
            support_name = "Floor"

        # 7. Stato Trend rispetto alla 1x1
        p_1x1 = levels["1x1"]
        trend_status = "NEUTRAL"
        
        if mode == "FAN_UP_FROM_LOW":
            trend_status = "STRONG_BULL" if curr_price > p_1x1 else "WEAK_CORRECTION"
        else:
            trend_status = "STRONG_BEAR" if curr_price < p_1x1 else "WEAK_REVERSAL"

        return {
            "symbol": request.symbol,
            "current_price": curr_price,
            "anchor_mode": mode,
            "trend_status": trend_status,
            "support_level": closest_support,
            "support_angle": support_name,
            "resistance_level": closest_resistance,
            "resistance_angle": resistance_name
        }

    except Exception as e:
        print(f"Gann Error: {e}")
        return {}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
