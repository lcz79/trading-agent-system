# ===============================================================
# MARK ANALYST v8.0 — ESECUTORE PURO
# ===============================================================
# Semplificato: non fa più discovery.
# Il suo unico compito è leggere la Hall of Fame (ottimizzata da Leo)
# ed eseguire le strategie in tempo reale.
# ===============================================================

import pandas as pd
import pandas_ta as ta
import logging
import time
import json
from datetime import datetime, timedelta, timezone

from core.exchange_router import ExchangeRouter
from agents.sara_trader_pro import SaraTrader
from agents.db_handler import DBHandler
from agents.strategies import STRATEGY_MAP

class MarkAnalyst:
    def __init__(self, exchange_router: ExchangeRouter, sara: SaraTrader, db: DBHandler):
        self.router = exchange_router; self.sara = sara; self.db = db
        self.exchange = self.router.get("bybit")
        self.hall_of_fame_path = "config/hall_of_fame.json"
        self.watchlist = {}
        self.dedupe_minutes = 30
        
        if not self.exchange: raise ConnectionError("❌ Nessun exchange disponibile.")
        
        logging.info(f"✅ MarkAnalyst v8.0 'Esecutore Puro' inizializzato.")
        self._load_watchlist_from_hof()

    def _load_watchlist_from_hof(self):
        """Carica la watchlist direttamente dal file Hall of Fame JSON."""
        try:
            with open(self.hall_of_fame_path, 'r') as f:
                self.watchlist = json.load(f)
            logging.info(f"✅ Caricata Hall of Fame con {len(self.watchlist)} strategie ottimizzate.")
        except (FileNotFoundError, json.JSONDecodeError):
            logging.error(f"‼️ HALL OF FAME '{self.hall_of_fame_path}' non trovata o corrotta! Il bot non analizzerà nulla.")
            self.watchlist = {}

    # ... (le funzioni di calcolo indicatori e fetch ohlcv rimangono le stesse) ...
    def _calculate_indicators(self, df: pd.DataFrame, strategy: str, params: dict) -> pd.DataFrame:
        if df.empty: return df
        try:
            df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
            if strategy == "PULLBACK":
                df["EMA_F"] = ta.ema(df["close"], length=int(params["ema_fast"]))
                df["EMA_S"] = ta.ema(df["close"], length=int(params["ema_slow"]))
            elif strategy == "MEANREV":
                df["RSI"] = ta.rsi(df["close"], length=int(params["rsi_len"]))
                bb = ta.bbands(df["close"], length=int(params["bb_len"]), std=2.0)
                df["BBL"], df["BBM"], df["BBU"] = bb.iloc[:, 0], bb.iloc[:, 1], bb.iloc[:, 2]
            df.dropna(inplace=True); return df
        except Exception as e: logging.error(f"Errore indicatori: {e}"); return pd.DataFrame()
    def _fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
        try: ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit); df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]); df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True); return df.dropna()
        except Exception: return pd.DataFrame()

    def run_analysis(self):
        self._load_watchlist_from_hof() # Ricarica ad ogni ciclo per recepire aggiornamenti
        if not self.watchlist:
            logging.warning("Watchlist vuota. Nessuna analisi da eseguire.")
            return
            
        logging.info(f"🔎 Avvio analisi sulla Hall of Fame di {len(self.watchlist)} asset...")
        for symbol, strat_config in self.watchlist.items():
            try:
                strategy_name = strat_config["strategy"]; params = strat_config["params"]
                df = self._fetch_ohlcv(symbol, "1h", 250)
                if df.empty: continue
                df = self._calculate_indicators(df, strategy_name, params)
                if df.empty: continue
                
                last_signal_time = self.db.get_last_signal_time(symbol, strategy_name)
                if last_signal_time and (datetime.now(timezone.utc) - last_signal_time) < timedelta(minutes=self.dedupe_minutes): continue
                
                strategy_function = STRATEGY_MAP.get(strategy_name)
                if not strategy_function: continue
                
                signal = strategy_function(df, params)
                if signal:
                    signal['asset'] = symbol; signal['timeframe'] = "1h"
                    logging.warning(f"🔥 Nuovo segnale: {signal['asset']} {signal['side']}")
                    self.db.save_signal(signal); self.sara.propose_trade(signal)
                
                time.sleep(self.exchange.rateLimit / 1000)
            except Exception as e: logging.error(f"Errore analisi {symbol}: {e}")

    def start(self):
        while True:
            self.run_analysis()
            logging.info(f"🕓 Ciclo analisi completato. Attendo 15 minuti...")
            time.sleep(60 * 15)
