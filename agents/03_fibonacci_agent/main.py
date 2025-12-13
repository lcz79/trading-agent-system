import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel
from pybit.unified_trading import HTTP

app = FastAPI()
session = HTTP()

class FibRequest(BaseModel):
    symbol: str
    # Il campo price è opzionale, se c'è lo ignoriamo perché guardiamo il mercato vero
    price: float = 0.0

def get_market_structure(symbol):
    try:
        # Scarichiamo candele a 4 ORE (240 min) per trend solidi
        resp = session.get_kline(category="linear", symbol=symbol, interval="240", limit=200)
        if not resp or resp.get('retCode') != 0: 
            return None
        
        result = resp.get('result')
        if not result:
            return None
            
        data = result.get('list')
        if not data:
            return None
            
        # [ts, open, high, low, close, ...]
        df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        return df
    except Exception:
        return None

@app.post("/analyze_fib")
def analyze(req: FibRequest):
    df = get_market_structure(req.symbol)
    
    if df is None or df.empty:
        return {"symbol": req.symbol, "status": "error", "msg": "No data from Bybit"}

    # Troviamo il massimo e minimo degli ultimi 200 periodi (Swing High / Swing Low)
    swing_high = df['high'].max()
    swing_low = df['low'].min()
    current_price = df['close'].iloc[0] # Bybit da il più recente all'indice 0

    # Calcolo del Range
    diff = swing_high - swing_low
    
    # Se siamo vicini al minimo, cerchiamo resistenze (Ritracciamento verso l'alto)
    # Se siamo vicini al massimo, cerchiamo supporti (Ritracciamento verso il basso)
    # Per semplificare, restituiamo i livelli assoluti di prezzo nel range
    
    levels = {
        "0.0 (Low)": swing_low,
        "0.236": swing_low + (diff * 0.236),
        "0.382": swing_low + (diff * 0.382),
        "0.5 (Mid)": swing_low + (diff * 0.5),
        "0.618 (Golden)": swing_low + (diff * 0.618),
        "0.786": swing_low + (diff * 0.786),
        "1.0 (High)": swing_high
    }

    # Determiniamo se siamo in "Zona Golden Pocket" (tra 0.618 e 0.65 è zona reversal)
    # O se siamo in zona "Discount" (< 0.5) o "Premium" (> 0.5)
    position = "PREMIUM (Expensive)" if current_price > levels["0.5 (Mid)"] else "DISCOUNT (Cheap)"

    return {
        "symbol": req.symbol,
        "current_price": current_price,
        "range_high": swing_high,
        "range_low": swing_low,
        "market_structure": position,
        "fib_levels": {k: round(v, 2) for k, v in levels.items()},
        "status": "active_real_data"
    }

@app.get("/health")
def health(): return {"status": "active"}
