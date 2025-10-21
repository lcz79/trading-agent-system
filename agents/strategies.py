# ===============================================================
# MITRAGLIERE A.I. - ARSENALE STRATEGICO
# ===============================================================
# Contiene le definizioni pure delle strategie di trading, 
# pronte per essere usate sia dall'analisi in tempo reale 
# che dal backtesting parallelo.
# ===============================================================

import pandas as pd
import pandas_ta as ta
import json

# --- Funzioni di supporto universali ---

def _risk_reward_dynamic(entry: float, atr: float, side: str, rr_mult: float = 1.5):
    """Calcola SL e TP basandosi sull'ATR e un moltiplicatore di Risk/Reward."""
    if side == "LONG":
        sl = entry - atr
        tp = entry + (rr_mult * atr)
    else:  # SHORT
        sl = entry + atr
        tp = entry - (rr_mult * atr)
    return sl, tp

def _sanity_check(side: str, entry: float, sl: float, tp: float) -> bool:
    """Verifica che i livelli di SL/TP siano logicamente corretti."""
    if side == "LONG":
        return sl < entry < tp
    else:  # SHORT
        return tp < entry < sl

# --- DEFINIZIONE DELLE STRATEGIE ---

def strategy_pullback(df: pd.DataFrame, params: dict) -> dict | None:
    """
    Strategia Trend-Following: Cerca entrate sui ritracciamenti durante un trend definito.
    Richiede nel DataFrame: 'close', 'open', 'high', 'low', 'EMA_F', 'EMA_S', 'ATR'.
    """
    if len(df) < 2:
        return None
    
    c, p = df.iloc[-1], df.iloc[-2] # Candela attuale e precedente
    
    # Filtri di qualità del segnale
    if (c.get("ATR", 0) / c["close"]) > 0.08:  # Evita volatilità estrema
        return None
        
    side = None
    # Condizione Long: trend rialzista, il prezzo ritraccia sulla EMA veloce e chiude verde
    if (p["close"] > p["EMA_S"]) and (p["low"] <= p["EMA_F"]) and (c["close"] > c["open"]):
        side = "LONG"
    # Condizione Short: trend ribassista, il prezzo ritraccia sulla EMA veloce e chiude rosso
    elif (p["close"] < p["EMA_S"]) and (p["high"] >= p["EMA_F"]) and (c["close"] < c["open"]):
        side = "SHORT"
    else:
        return None
        
    sl, tp = _risk_reward_dynamic(float(c["close"]), c["ATR"], side)
    if not _sanity_check(side, float(c["close"]), sl, tp):
        return None
        
    return {
        "side": side,
        "entry": float(c["close"]),
        "sl": float(sl),
        "tp": float(tp),
        "strategy": "PULLBACK",
        "params": json.dumps(params)
    }


def strategy_meanrev(df: pd.DataFrame, params: dict) -> dict | None:
    """
    Strategia Mean-Reversion: Cerca entrate su condizioni di ipervenduto/ipercomprato.
    Richiede nel DataFrame: 'close', 'BBL', 'BBU', 'RSI', 'ATR'.
    """
    if len(df) < 2:
        return None
        
    c, p = df.iloc[-1], df.iloc[-2] # Candela attuale e precedente
    
    side = None
    rsi_oversold = params.get("rsi_oversold", 30)
    rsi_overbought = params.get("rsi_overbought", 70)

    # Condizione Long: ipervenduto (sotto banda di Bollinger e RSI basso)
    if (p["close"] <= p["BBL"]) and (p["RSI"] <= rsi_oversold):
        side = "LONG"
    # Condizione Short: ipercomprato (sopra banda di Bollinger e RSI alto)
    elif (p["close"] >= p["BBU"]) and (p["RSI"] >= rsi_overbought):
        side = "SHORT"
    else:
        return None
        
    sl, tp = _risk_reward_dynamic(float(c["close"]), c["ATR"], side)
    if not _sanity_check(side, float(c["close"]), sl, tp):
        return None
        
    return {
        "side": side,
        "entry": float(c["close"]),
        "sl": float(sl),
        "tp": float(tp),
        "strategy": "MEANREV",
        "params": json.dumps(params)
    }

# --- MAPPA DELLE STRATEGIE ---
# Un modo semplice per chiamare le strategie per nome.
STRATEGY_MAP = {
    "PULLBACK": strategy_pullback,
    "MEANREV": strategy_meanrev,
}