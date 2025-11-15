import pandas as pd
import numpy as np

# NUOVA FUNZIONE: Calcolo dei Punti Pivot
def calculate_pivot_points(data: pd.DataFrame):
    """
    Calcola i Punti Pivot e i livelli di Supporto/Resistenza (S1, S2, R1, R2).
    Usa l'ultimo dato completo disponibile (la candela precedente) per i calcoli.
    """
    if len(data) < 2:
        return { "pivot": None, "s1": None, "s2": None, "r1": None, "r2": None }
        
    last_candle = data.iloc[-2]
    high, low, close = last_candle['high'], last_candle['low'], last_candle['close']

    pivot = (high + low + close) / 3
    r1, s1 = (2 * pivot) - low, (2 * pivot) - high
    r2, s2 = pivot + (high - low), pivot - (high - low)
    
    return { "pivot": pivot, "s1": s1, "s2": s2, "r1": r1, "r2": r2 }

# FUNZIONE CORRETTA E RESA SICURA
def calculate_rsi(data, window=14):
    """Calcola l'Relative Strength Index (RSI) in modo sicuro."""
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    
    # --- INIZIO CORREZIONE ---
    # Preveniamo la divisione per zero
    rs = gain / loss.replace(0, np.nan) # Sostituisci 0 con NaN per evitare divisione per zero
    rsi = 100 - (100 / (1 + rs))
    # Sostituiamo i valori non validi (inf, NaN) con None, che diventerà 'null' in JSON
    rsi = rsi.replace([np.inf, -np.inf], np.nan).fillna(50) # Usiamo 50 come valore neutrale se RSI non è calcolabile
    # --- FINE CORREZIONE ---

    return rsi

def analyze(market_data: pd.DataFrame):
    """Funzione principale che esegue l'analisi tecnica completa."""
    if not isinstance(market_data, pd.DataFrame) or 'close' not in market_data.columns:
        raise ValueError("L'input deve essere un DataFrame di pandas con la colonna 'close'.")

    market_data = market_data.sort_values('timestamp').reset_index(drop=True)

    pivot_levels = calculate_pivot_points(market_data)
    rsi = calculate_rsi(market_data)
    
    latest_price = market_data['close'].iloc[-1]
    
    latest_indicators = {
        "latest_price": latest_price,
        "rsi": rsi.iloc[-1] if not rsi.empty else 50.0, # Usiamo 50.0 come default
        "pivot_point": pivot_levels.get("pivot"),
        "support_1": pivot_levels.get("s1"),
        "support_2": pivot_levels.get("s2"),
        "resistance_1": pivot_levels.get("r1"),
        "resistance_2": pivot_levels.get("r2")
    }
    
    # Sostituisci eventuali NaN/inf residui nei risultati finali con None
    for key, value in latest_indicators.items():
        if isinstance(value, (float, int)) and not np.isfinite(value):
            latest_indicators[key] = None

    signal = "HOLD"
    # Assicuriamoci che i livelli non siano None prima di fare confronti
    if pivot_levels.get("s1") is not None and latest_price < pivot_levels["s1"]:
        signal = "POTENTIAL_BUY"
    elif pivot_levels.get("r1") is not None and latest_price > pivot_levels["r1"]:
        signal = "POTENTIAL_SELL"

    latest_indicators["signal_preliminary"] = signal
    
    return latest_indicators

if __name__ == '__main__':
    print("Esecuzione test (CON PIVOT POINTS e RSI SICURO)...")
    # ... il resto del file di test rimane invariato ...