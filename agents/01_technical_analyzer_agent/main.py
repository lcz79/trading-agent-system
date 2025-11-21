import os
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pybit.unified_trading import HTTP

app = FastAPI(title="Multi-Timeframe Technical Analysis Agent")

# --- CONFIGURAZIONE BYBIT ---
api_key = os.getenv("BYBIT_API_KEY")
api_secret = os.getenv("BYBIT_API_SECRET")

session = HTTP(testnet=False, api_key=api_key, api_secret=api_secret)

# --- MODELLI DI OUTPUT ---

class IndicatorValue(BaseModel):
    """
    Restituisce valore attuale e precedente per permettere
    all'agente decisionale di calcolare pendenze e incroci.
    """
    current: float
    previous: float

class TechnicalState(BaseModel):
    """Lo stato tecnico di un singolo timeframe"""
    close_price: float
    volume: float
    
    # Trend
    sma_50: IndicatorValue
    sma_200: IndicatorValue
    ema_9: IndicatorValue  # Utile per trend breve
    
    # Momentum
    rsi_14: IndicatorValue
    
    # MACD
    macd_line: IndicatorValue
    macd_signal: IndicatorValue
    macd_hist: IndicatorValue
    
    # Volatilità
    bb_upper: float # Bollinger Upper
    bb_lower: float # Bollinger Lower
    bb_width: float # (Upper - Lower) / Middle -> Importante per Squeeze
    atr_14: float   # Average True Range

class AnalysisRequest(BaseModel):
    symbol: str
    timeframes: List[str] = ["15", "60", "240", "D"] 
    # Bybit format: 15=15m, 60=1h, 240=4h, D=1Day

class MultiFrameResponse(BaseModel):
    symbol: str
    # Un dizionario dove la chiave è il timeframe (es. "60") e il valore è lo stato tecnico
    data: Dict[str, TechnicalState]

# --- CALCOLI MATEMATICI (Core) ---

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Aggiunge colonne tecniche al DataFrame."""
    if df.empty: return df

    # 1. RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # 2. MACD (12, 26, 9)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd_line'] = ema12 - ema26
    df['macd_signal'] = df['macd_line'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd_line'] - df['macd_signal']

    # 3. Medie Mobili
    df['sma_50'] = df['close'].rolling(window=50).mean()
    df['sma_200'] = df['close'].rolling(window=200).mean()
    df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()

    # 4. Bande di Bollinger (20, 2)
    df['bb_mid'] = df['close'].rolling(window=20).mean()
    df['bb_std'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * 2)
    df['bb_lower'] = df['bb_mid'] - (df['bb_std'] * 2)
    # Larghezza bande (utile per rilevare bassa volatilità prima di esplosioni)
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']

    # 5. ATR (14)
    df['prev_close'] = df['close'].shift(1)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = (df['high'] - df['prev_close']).abs()
    df['tr3'] = (df['low'] - df['prev_close']).abs()
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=14).mean()

    return df

def fetch_data_for_timeframe(symbol: str, interval: str) -> Optional[TechnicalState]:
    """Scarica dati per un singolo timeframe e calcola indicatori."""
    try:
        # Scarichiamo abbastanza candele per la SMA 200
        response = session.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=250 
        )
        
        if response['retCode'] != 0 or not response['result']['list']:
            print(f"No data for {symbol} interval {interval}")
            return None

        # Parsing
        cols = ['startTime', 'open', 'high', 'low', 'close', 'vol', 'to']
        df = pd.DataFrame(response['result']['list'], columns=cols)
        
        # Ordina cronologicamente (Bybit da il più recente per primo -> reverse)
        df = df.iloc[::-1].reset_index(drop=True)
        
        # Casting a float
        for c in ['open', 'high', 'low', 'close', 'vol']:
            df[c] = df[c].astype(float)

        # Calcoli
        df = calculate_indicators(df)

        # Estrazione dati per l'agente decisionale.
        # NOTA: Prendiamo il penultimo valore (iloc[-2]) come "current" (ultima candela CHIUSA)
        # e il terzultimo (iloc[-3]) come "previous".
        # Usare la candela in corso (iloc[-1]) è rischioso perché i valori cambiano fino alla chiusura.
        
        if len(df) < 3: return None
        
        curr = df.iloc[-2] # Ultima candela completata
        prev = df.iloc[-3] # Penultima candela completata

        return TechnicalState(
            close_price=curr['close'],
            volume=curr['vol'],
            
            sma_50=IndicatorValue(current=curr['sma_50'], previous=prev['sma_50']),
            sma_200=IndicatorValue(current=curr['sma_200'], previous=prev['sma_200']),
            ema_9=IndicatorValue(current=curr['ema_9'], previous=prev['ema_9']),
            
            rsi_14=IndicatorValue(current=curr['rsi'], previous=prev['rsi']),
            
            macd_line=IndicatorValue(current=curr['macd_line'], previous=prev['macd_line']),
            macd_signal=IndicatorValue(current=curr['macd_signal'], previous=prev['macd_signal']),
            macd_hist=IndicatorValue(current=curr['macd_hist'], previous=prev['macd_hist']),
            
            bb_upper=curr['bb_upper'],
            bb_lower=curr['bb_lower'],
            bb_width=curr['bb_width'],
            atr_14=curr['atr']
        )

    except Exception as e:
        print(f"Error processing {interval}: {e}")
        return None

# --- ENDPOINT ---

@app.post("/analyze_multi_tf", response_model=MultiFrameResponse)
def analyze_multi_timeframe(request: AnalysisRequest):
    """
    Analizza il simbolo su tutti i timeframe richiesti.
    Restituisce un report tecnico dettagliato, SENZA giudizi di trading.
    """
    results = {}
    
    for tf in request.timeframes:
        tech_state = fetch_data_for_timeframe(request.symbol, tf)
        if tech_state:
            results[tf] = tech_state
            
    if not results:
        raise HTTPException(status_code=404, detail="Impossibile ottenere dati per i timeframe richiesti")

    return MultiFrameResponse(
        symbol=request.symbol,
        data=results
    )
