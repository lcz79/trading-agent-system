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
        """
        Funzione migliorata per recuperare i dati.
        Pulisce il simbolo e tenta diverse varianti per massima compatibilità.
        """
        try:
            # --- LOGICA DI PULIZIA DEL SIMBOLO ---
            clean_symbol = symbol.split(':')[0]
            # ------------------------------------
            
            data = None
            unified_symbol = clean_symbol.replace("/", "")
            
            if unified_symbol in self.ex.markets:
                data = self.ex.fetch_ohlcv(unified_symbol, timeframe=self.tf, limit=limit)
            elif clean_symbol in self.ex.markets:
                data = self.ex.fetch_ohlcv(clean_symbol, timeframe=self.tf, limit=limit)
            elif f"{unified_symbol}.P" in self.ex.markets:
                data = self.ex.fetch_ohlcv(f"{unified_symbol}.P", timeframe=self.tf, limit=limit)
            
            if data is None:
                raise ValueError(f"Nessuna variante del simbolo '{clean_symbol}' trovata sull'exchange.")

            if not data: return None
            df = pd.DataFrame(data, columns=["time","open","high","low","close","volume"])
            df["timestamp"] = pd.to_datetime(df["time"], unit="ms")
            for c in ["open","high","low","close","volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna().reset_index(drop=True)
        except Exception as e:
            # Usiamo 'symbol' originale nel log per capire da dove viene l'errore
            logging.error(f"[MARK] fetch {symbol}: {e}")
            return None

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.ind
        bb = ta.bbands(df["close"], length=p["bb_len"], std=p["bb_mult"])
        if bb is not None: df["BBL"], df["BBM"], df["BBU"] = bb.iloc[:,0], bb.iloc[:,1], bb.iloc[:,2]
        df["RSI"] = ta.rsi(df["close"], length=p["rsi_len"])
        df["EMA_FAST"] = ta.ema(df["close"], length=p["ema_fast"])
        df["EMA_SLOW"] = ta.ema(df["close"], length=p["ema_slow"])
        df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=p["atr_len"])
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=p["adx_len"])
        if adx_df is not None and not adx_df.empty: df["ADX"] = adx_df.iloc[:,0]
        kc = ta.kc(df["high"], df["low"], df["close"], length=p["kc_len"], scalar=p["kc_mult"])
        if kc is not None and not kc.empty: df["KCL"], df["KCU"] = kc.iloc[:,0], kc.iloc[:,2]
        if "BBU" in df and "KCU" in df:
            df["SQUEEZE_ON"] = (df["BBU"] < df["KCU"]) & (df["BBL"] > df["KCL"])
        return df.fillna(0)

    def regime_ok(self, row: pd.Series) -> bool:
        if not all(k in row for k in ["ATR", "ADX", "close"]): return False
        if row["close"] <= 0 or row["ATR"] <= 0: return False
        atr_pct = row["ATR"] / row["close"]
        if not (self.filt["atr_min_pct"] <= atr_pct <= self.filt["atr_max_pct"]): return False
        if row["ADX"] < self.filt["min_adx"]: return False
        return True

    def logic_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        required_cols = ["EMA_FAST", "BBM", "RSI", "BBL", "BBU", "SQUEEZE_ON", "ATR", "ADX"]
        if len(df) < 4 or not all(c in df.columns for c in required_cols):
            return {"signal": "NEUTRAL", "reason": "Dati indicatori insufficienti"}

        prev, now, prev2 = df.iloc[-2], df.iloc[-1], df.iloc[-3]
        if not self.regime_ok(prev): return {"signal": "NEUTRAL", "reason": "Filtro di regime"}

        rr, atr = self.logic["rr"], float(prev["ATR"])
        if atr == 0: return {"signal": "NEUTRAL", "reason": "ATR è zero"}
        
        entry = float(now["close"])

        # Trend Pullback
        if (prev["close"] > prev["EMA_FAST"]) and (prev["RSI"] < self.logic["rsi_buy_level"]) and (prev["low"] <= prev["BBM"]):
            sl = entry - 2 * atr
            tp = entry + rr * (entry - sl)
            return {"signal":"LONG","logic":"TrendPullback","entry":entry,"sl":sl,"tp":tp}
        if (prev["close"] < prev["EMA_FAST"]) and (prev["RSI"] > self.logic["rsi_sell_level"]) and (prev["high"] >= prev["BBM"]):
            sl = entry + 2 * atr
            tp = entry - rr * (sl - entry)
            return {"signal":"SHORT","logic":"TrendPullback","entry":entry,"sl":sl,"tp":tp}

        # Mean Reversion
        if (prev["low"] <= prev["BBL"]) and (prev["RSI"] <= self.logic["rsi_oversold"]):
            sl = entry - 2 * atr
            tp = float(prev["BBM"])
            if tp > entry: return {"signal":"LONG","logic":"MeanReversion","entry":entry,"sl":sl,"tp":tp}
        if (prev["high"] >= prev["BBU"]) and (prev["RSI"] >= self.logic["rsi_overbought"]):
            sl = entry + 2 * atr
            tp = float(prev["BBM"])
            if tp < entry: return {"signal":"SHORT","logic":"MeanReversion","entry":entry,"sl":sl,"tp":tp}

        # Breakout (post-squeeze)
        if bool(prev2["SQUEEZE_ON"]) and (prev["close"] > prev["BBU"]):
            sl = entry - 2 * atr
            tp = entry + rr * (entry - sl)
            return {"signal":"LONG","logic":"Breakout","entry":entry,"sl":sl,"tp":tp}
        if bool(prev2["SQUEEZE_ON"]) and (prev["close"] < prev["BBL"]):
            sl = entry + 2 * atr
            tp = entry - rr * (sl - entry)
            return {"signal":"SHORT","logic":"Breakout","entry":entry,"sl":sl,"tp":tp}

        return {"signal": "NEUTRAL", "reason": "Nessuna logica corrisponde"}

    def run(self):
        logging.info("[MARK] Avvio analisi su %d assets...", len(self.assets))
        for s in self.assets:
            df = self.fetch_df(s)
            if df is None: continue
            df_with_indicators = self.add_indicators(df)
            sig = self.logic_signals(df_with_indicators)
            
            # Pubblichiamo usando il nome pulito del simbolo
            clean_symbol = s.split(':')[0]
            publish("MARK", clean_symbol, sig)
            
            if sig.get("signal") != "NEUTRAL":
                logging.info(f"[MARK] {clean_symbol} -> {sig['signal']} ({sig.get('logic', 'N/A')})")
