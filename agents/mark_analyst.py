import logging
from typing import List, Dict, Any, Optional
import pandas as pd
import pandas_ta as ta
from core.memory_hub import publish

class MarkAnalyst:
    def __init__(self, exchange, assets: List[str], timeframe: str, ind_cfg: Dict[str, Any], filt_cfg: Dict[str, Any], logic_cfg: Dict[str, Any]):
        self.ex = exchange
        self.assets = assets
        self.tf = timeframe
        self.ind = ind_cfg
        self.filt = filt_cfg
        self.logic = logic_cfg

    def fetch_df(self, symbol: str, limit: int = 300) -> Optional[pd.DataFrame]:
        try:
            data = None
            # --- CORREZIONE DEFINITIVA PER BYBIT ---
            # Bybit per i derivati usa il formato 'BTCUSDT'.
            # Tentiamo prima questo formato.
            unified_symbol = symbol.replace("/", "")
            
            if unified_symbol in self.ex.markets:
                data = self.ex.fetch_ohlcv(unified_symbol, timeframe=self.tf, limit=limit)
            elif symbol in self.ex.markets: # Tentativo di fallback con il simbolo originale
                data = self.ex.fetch_ohlcv(symbol, timeframe=self.tf, limit=limit)
            # ------------------------------------
            
            if data is None:
                # Se non troviamo dati, registriamo un avviso invece di un errore che blocca tutto.
                logging.warning(f"[MARK] fetch {symbol}: Nessuna variante del simbolo trovata sull'exchange o dati non disponibili.")
                return None

            if not data: return None
            df = pd.DataFrame(data, columns=["time","open","high","low","close","volume"])
            df["timestamp"] = pd.to_datetime(df["time"], unit="ms")
            for c in ["open","high","low","close","volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna().reset_index(drop=True)
        except Exception as e:
            # Gestisce altri errori imprevisti durante il fetch.
            logging.error(f"[MARK] Eccezione imprevista in fetch_df per {symbol}: {e}")
            return None

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.ind
        
        bb = ta.bbands(df["close"], length=p["bb_len"], std=p["bb_mult"])
        if bb is not None and not bb.empty:
            df["BBL"] = bb.iloc[:, 0]
            df["BBM"] = bb.iloc[:, 1]
            df["BBU"] = bb.iloc[:, 2]
            
        df["RSI"] = ta.rsi(df["close"], length=p["rsi_len"])
        df["EMA_FAST"] = ta.ema(df["close"], length=p["ema_fast"])
        df["EMA_SLOW"] = ta.ema(df["close"], length=p["ema_slow"])
        df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=p["atr_len"])
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=p["adx_len"])
        if adx_df is not None and not adx_df.empty: df["ADX"] = adx_df.iloc[:,0]
        kc = ta.kc(df["high"], df["low"], df["close"], length=p["kc_len"], scalar=p["kc_mult"])
        if kc is not None and not kc.empty:
            df["KCL"] = kc.iloc[:, 0]
            df["KCU"] = kc.iloc[:, 2]
        if "BBU" in df and "KCU" in df:
            df["SQUEEZE_ON"] = (df["BBU"] < df["KCU"]) & (df["BBL"] > df["KCL"])
        return df.fillna(0)

    def regime_ok(self, row: pd.Series) -> bool:
        if not all(k in row for k in ["ATR", "ADX", "close"]) or row["close"] <= 0 or row["ATR"] <= 0: return False
        atr_pct = row["ATR"] / row["close"]
        return self.filt["atr_min_pct"] <= atr_pct <= self.filt["atr_max_pct"] and row["ADX"] >= self.filt["min_adx"]

    def logic_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        required_cols = ["EMA_FAST", "BBM", "RSI", "BBL", "BBU", "SQUEEZE_ON", "ATR", "ADX"]
        if len(df) < 4 or not all(c in df.columns for c in required_cols):
            return {"signal": "NEUTRAL", "reason": "Dati indicatori insufficienti"}
        prev, now, prev2 = df.iloc[-2], df.iloc[-1], df.iloc[-3]
        if not self.regime_ok(prev): return {"signal": "NEUTRAL", "reason": "Filtro di regime"}
        rr, atr = self.logic["rr"], float(prev["ATR"])
        if atr == 0: return {"signal": "NEUTRAL", "reason": "ATR è zero"}
        entry = float(now["close"])
        if (prev["close"] > prev["EMA_FAST"]) and (prev["RSI"] < self.logic["rsi_buy_level"]) and (prev["low"] <= prev["BBM"]):
            sl, tp = entry - 2 * atr, entry + rr * (2 * atr); return {"signal":"LONG","logic":"TrendPullback","entry":entry,"sl":sl,"tp":tp}
        if (prev["close"] < prev["EMA_FAST"]) and (prev["RSI"] > self.logic["rsi_sell_level"]) and (prev["high"] >= prev["BBM"]):
            sl, tp = entry + 2 * atr, entry - rr * (2 * atr); return {"signal":"SHORT","logic":"TrendPullback","entry":entry,"sl":sl,"tp":tp}
        if (prev["low"] <= prev["BBL"]) and (prev["RSI"] <= self.logic["rsi_oversold"]):
            if float(prev["BBM"]) > entry: sl, tp = entry - 2 * atr, float(prev["BBM"]); return {"signal":"LONG","logic":"MeanReversion","entry":entry,"sl":sl,"tp":tp}
        if (prev["high"] >= prev["BBU"]) and (prev["RSI"] >= self.logic["rsi_overbought"]):
            if float(prev["BBM"]) < entry: sl, tp = entry + 2 * atr, float(prev["BBM"]); return {"signal":"SHORT","logic":"MeanReversion","entry":entry,"sl":sl,"tp":tp}
        if bool(prev2["SQUEEZE_ON"]) and (prev["close"] > prev["BBU"]):
            sl, tp = entry - 2 * atr, entry + rr * (2 * atr); return {"signal":"LONG","logic":"Breakout","entry":entry,"sl":sl,"tp":tp}
        if bool(prev2.get("SQUEEZE_ON", False)) and (prev["close"] < prev["BBL"]): # Aggiunto .get per sicurezza
            sl, tp = entry + 2 * atr, entry - rr * (2 * atr); return {"signal":"SHORT","logic":"Breakout","entry":entry,"sl":sl,"tp":tp}
        return {"signal": "NEUTRAL", "reason": "Nessuna logica corrisponde"}

    def run(self):
        logging.info("[MARK] Avvio analisi su %d assets...", len(self.assets))
        for s in self.assets:
            df = self.fetch_df(s)
            if df is None or df.empty: continue
            df_with_indicators = self.add_indicators(df)
            sig = self.logic_signals(df_with_indicators)
            publish("MARK", s, sig)
            if sig.get("signal") != "NEUTRAL":
                logging.info(f"[MARK] {s} -> {sig['signal']} ({sig.get('logic', 'N/A')})")
