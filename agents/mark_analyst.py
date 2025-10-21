# ===============================================================
# MARK ANALYST v6.1 - Robust Data Check
# ===============================================================
# Aggiunto controllo di sicurezza per prevenire errori 'out-of-bounds'
# quando i dati post-indicatori sono insufficienti.
# ===============================================================

import pandas as pd
import pandas_ta as ta
import json, logging, time
from datetime import datetime, timedelta, timezone

from core.exchange_router import ExchangeRouter
from agents.sara_trader_pro import SaraTrader # Assumendo che usi la versione PRO
from agents.db_handler import DBHandler

# --- HALL OF FAME (invariata) ---
HALL_OF_FAME_DATA = {
    "BTC/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 20, "ema_slow": 100}},
    "ETH/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 10, "ema_slow": 50}},
    "SOL/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 30, "ema_slow": 50}},
    "XRP/USDT:USDT": {"strategy": "MEANREV", "params": {"bb_len": 30, "rsi_len": 21, "rsi_oversold": 25, "rsi_overbought": 75}},
    "AVAX/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 30, "ema_slow": 200}},
    "LINK/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 30, "ema_slow": 50}},
    "DOGE/USDT:USDT": {"strategy": "MEANREV", "params": {"bb_len": 25, "rsi_len": 14, "rsi_oversold": 30, "rsi_overbought": 70}},
}

class MarkAnalyst:
    def __init__(self, exchange_router: ExchangeRouter, sara: SaraTrader, db: DBHandler):
        self.router = exchange_router
        self.sara = sara
        self.db = db
        self.exchange = self.router.get("bybit")
        self.timeframes = ["15m", "1h"]
        self.hall_of_fame = HALL_OF_FAME_DATA
        self.dedupe_minutes = 30
        if not self.exchange: raise ConnectionError("❌ Nessun exchange disponibile.")
        try:
            self.exchange.load_markets()
        except Exception as e:
            logging.warning(f"⚠️ Impossibile caricare i mercati: {e}")
        logging.info(f"✅ MarkAnalyst v6.1 inizializzato con {len(self.hall_of_fame)} asset.")

    # ... (tutte le funzioni di utility rimangono invariate) ...
    def _fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.dropna()
            return df
        except Exception as e:
            logging.error(f"Errore fetch_ohlcv {symbol} [{timeframe}]: {e}")
            return pd.DataFrame()
    def _calculate_indicators(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        if df.empty: return df
        try:
            if "ema_fast" in params: df["EMA_F"] = ta.ema(df["close"], length=int(params["ema_fast"]))
            if "ema_slow" in params: df["EMA_S"] = ta.ema(df["close"], length=int(params["ema_slow"]))
            if "rsi_len" in params: df["RSI"] = ta.rsi(df["close"], length=int(params["rsi_len"]))
            if "bb_len" in params:
                bb = ta.bbands(df["close"], length=int(params["bb_len"]), std=2.0)
                df["BBL"], df["BBM"], df["BBU"] = bb.iloc[:, 0], bb.iloc[:, 1], bb.iloc[:, 2]
            df["ADX"] = ta.adx(df["high"], df["low"], df["close"], length=14).iloc[:, 0]
            df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
            df.dropna(inplace=True)
            return df
        except Exception as e:
            logging.error(f"Errore calcolo indicatori: {e}")
            return df
    def _multi_timeframe_confirmation(self, symbol: str, params: dict) -> bool:
        df_15m = self._fetch_ohlcv(symbol, "15m", 100)
        df_1h = self._fetch_ohlcv(symbol, "1h", 100)
        if df_15m.empty or df_1h.empty: return False
        df_15m = self._calculate_indicators(df_15m, params)
        df_1h = self._calculate_indicators(df_1h, params)
        if df_15m.empty or df_1h.empty: return False # Aggiunto controllo post-indicatori
        if "EMA_F" not in df_1h or "EMA_S" not in df_1h: return True
        last_15, last_1h = df_15m.iloc[-1], df_1h.iloc[-1]
        return (last_15["EMA_F"] > last_15["EMA_S"]) == (last_1h["EMA_F"] > last_1h["EMA_S"])
    def _risk_reward_dynamic(self, entry: float, atr: float, side: str, rr_mult: float = 1.5):
        if side == "LONG": sl, tp = entry - atr, entry + rr_mult * atr
        else: sl, tp = entry + atr, entry - rr_mult * atr
        return sl, tp
    def _sanity_check(self, side, entry, sl, tp):
        if side == "LONG": return sl < entry < tp
        else: return tp < entry < sl

    # ------------------------- LOGICA STRATEGICA (CON FIX) -------------------------

    def _check_pullback(self, df: pd.DataFrame, params: dict, symbol: str):
        # --- FIX: CONTROLLO DI SICUREZZA ---
        if len(df) < 2:
            logging.info(f"[{symbol}] Dati insufficienti per analisi Pullback (righe: {len(df)}).")
            return None
        # -----------------------------------
        c, p = df.iloc[-1], df.iloc[-2]
        adx, atr = c["ADX"], c["ATR"]
        if adx < 15:
            logging.info(f"[{symbol}] ADX troppo basso ({adx:.1f}), nessun trend.")
            return None
        if atr / c["close"] > 0.05:
            logging.info(f"[{symbol}] Volatilità eccessiva ({atr/c['close']:.2%}), skip.")
            return None
        if (p["close"] > p["EMA_S"]) and (p["low"] <= p["EMA_F"]) and (c["close"] > c["open"]):
            side = "LONG"
        elif (p["close"] < p["EMA_S"]) and (p["high"] >= p["EMA_F"]) and (c["close"] < c["open"]):
            side = "SHORT"
        else: return None
        sl, tp = self._risk_reward_dynamic(float(c["close"]), atr, side)
        if not self._sanity_check(side, float(c["close"]), sl, tp): return None
        return {"asset": symbol, "timeframe": "1h", "side": side, "entry": float(c["close"]), "sl": float(sl), "tp": float(tp), "strategy": "PULLBACK", "params": json.dumps(params)}

    def _check_meanrev(self, df: pd.DataFrame, params: dict, symbol: str):
        # --- FIX: CONTROLLO DI SICUREZZA ---
        if len(df) < 2:
            logging.info(f"[{symbol}] Dati insufficienti per analisi MeanRev (righe: {len(df)}).")
            return None
        # -----------------------------------
        c, p = df.iloc[-1], df.iloc[-2]
        atr = c["ATR"]
        if (p["close"] <= p["BBL"]) and (p["RSI"] <= params["rsi_oversold"]):
            side = "LONG"
        elif (p["close"] >= p["BBU"]) and (p["RSI"] >= params["rsi_overbought"]):
            side = "SHORT"
        else: return None
        sl, tp = self._risk_reward_dynamic(float(c["close"]), atr, side)
        if not self._sanity_check(side, float(c["close"]), sl, tp): return None
        return {"asset": symbol, "timeframe": "1h", "side": side, "entry": float(c["close"]), "sl": float(sl), "tp": float(tp), "strategy": "MEANREV", "params": json.dumps(params)}

    # ------------------------- CICLO PRINCIPALE (invariato) -------------------------

    def run_analysis(self):
        logging.info(f"🔎 Avvio analisi su {len(self.hall_of_fame)} asset...")
        for symbol, strat in self.hall_of_fame.items():
            try:
                df = self._fetch_ohlcv(symbol, "1h", 250)
                if df.empty:
                    logging.warning(f"[{symbol}] Nessun dato disponibile.")
                    continue
                df = self._calculate_indicators(df, strat["params"])
                if df.empty: continue
                if not self._multi_timeframe_confirmation(symbol, strat["params"]):
                    logging.info(f"[{symbol}] Nessuna conferma multi-timeframe.")
                    continue
                last_signal_time = self.db.get_last_signal_time(symbol, strat["strategy"])
                if last_signal_time and (datetime.now(timezone.utc) - last_signal_time) < timedelta(minutes=self.dedupe_minutes):
                    logging.info(f"[{symbol}] Segnale recente, skip.")
                    continue
                signal = None
                if strat["strategy"].upper() == "PULLBACK":
                    signal = self._check_pullback(df, strat["params"], symbol)
                elif strat["strategy"].upper() == "MEANREV":
                    signal = self._check_meanrev(df, strat["params"], symbol)
                if signal:
                    logging.warning(f"🔥 Nuovo segnale trovato: {signal}")
                    self.db.save_signal(signal)
                    self.sara.propose_trade(signal)
                time.sleep(self.exchange.rateLimit / 1000)
            except Exception as e:
                logging.error(f"Errore analisi {symbol}: {e}", exc_info=True)

    def start(self):
        while True:
            self.run_analysis()
            logging.info("🕓 Analisi completata. Attendo 10 minuti...")
            time.sleep(60 * 10)
