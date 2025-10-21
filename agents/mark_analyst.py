# ===============================================================
# MARK ANALYST v7.2 — Architettura Modulare
# ===============================================================
# Ora usa l'arsenale strategico centralizzato da 'strategies.py'.
# Il codice è più pulito e pronto per l'ottimizzatore.
# ===============================================================

import pandas as pd
import pandas_ta as ta
import logging
import time
from datetime import datetime, timedelta, timezone

from core.exchange_router import ExchangeRouter
from agents.sara_trader_pro import SaraTrader
from agents.db_handler import DBHandler
# --- NUOVA IMPORTAZIONE ---
from agents.strategies import STRATEGY_MAP

# ... (HALL_OF_FAME_DATA e DEFAULT_STRATEGY rimangono invariati) ...
HALL_OF_FAME_DATA = {
    "BTC/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 20, "ema_slow": 100}},
    "ETH/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 10, "ema_slow": 50}},
    "SOL/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 30, "ema_slow": 50}},
}
DEFAULT_STRATEGY = {"strategy": "PULLBACK", "params": {"ema_fast": 20, "ema_slow": 50}}


class MarkAnalyst:
    # ... (Tutta la parte di __init__ e di DISCOVERY rimane invariata) ...
    _DISCOVERY_MIN_VOL_USDT = 10_000_000; _DISCOVERY_TOP_N = 40; _DISCOVERY_TTL_SEC = 6 * 3600
    _cached_dynamic_list = []; _last_discovery_ts = 0

    def __init__(self, exchange_router: ExchangeRouter, sara: SaraTrader, db: DBHandler):
        self.router = exchange_router; self.sara = sara; self.db = db
        self.exchange = self.router.get("bybit"); self.watchlist = {}; self.dedupe_minutes = 30
        if not self.exchange: raise ConnectionError("❌ Nessun exchange disponibile.")
        logging.info(f"✅ MarkAnalyst v7.2 'Architettura Modulare' inizializzato.")
        self._update_watchlist()

    def _is_linear_usdt_perp(self, mkt: dict) -> bool:
        try:
            if not mkt.get('active', True): return False
            if not mkt.get('linear', False): return False
            if (mkt.get('settle') or '').upper() != 'USDT': return False
            return mkt.get('type') == 'swap'
        except Exception: return False
    def _discover_dynamic_markets(self) -> list[str]:
        now = time.time()
        if (now - self._last_discovery_ts) < self._DISCOVERY_TTL_SEC and self._cached_dynamic_list:
            return self._cached_dynamic_list
        logging.info("🔭 Inizio scoperta dinamica degli asset..."); try: markets = self.exchange.load_markets(); tickers = self.exchange.fetch_tickers()
        except Exception as e: logging.error(f"Discovery fallita: {e}"); return self._cached_dynamic_list or []
        candidates = []; 
        for symbol, ticker in tickers.items():
            market = markets.get(symbol)
            if not market or not self._is_linear_usdt_perp(market): continue
            volume = ticker.get('quoteVolume', 0)
            if volume >= self._DISCOVERY_MIN_VOL_USDT: candidates.append((symbol, volume))
        candidates.sort(key=lambda x: x[1], reverse=True); top_syms = [s for s, _ in candidates[:self._DISCOVERY_TOP_N]]
        self._cached_dynamic_list = top_syms; self._last_discovery_ts = time.time()
        logging.info(f"Discovery: trovati {len(top_syms)} mercati liquidi.")
        return top_syms
    def _update_watchlist(self):
        dynamic_symbols = self._discover_dynamic_markets()
        final_list = {**{s: DEFAULT_STRATEGY for s in dynamic_symbols}, **HALL_OF_FAME_DATA}
        self.watchlist = final_list
        logging.info(f"✅ Watchlist aggiornata: {len(self.watchlist)} asset pronti.")

    # --- FUNZIONI DI CALCOLO INDICATORI (MODIFICATE) ---
    def _calculate_indicators(self, df: pd.DataFrame, strategy: str, params: dict) -> pd.DataFrame:
        """Calcola solo gli indicatori necessari per una data strategia."""
        if df.empty: return df
        try:
            # Indicatori comuni
            df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
            
            # Indicatori specifici
            if strategy == "PULLBACK":
                df["EMA_F"] = ta.ema(df["close"], length=int(params["ema_fast"]))
                df["EMA_S"] = ta.ema(df["close"], length=int(params["ema_slow"]))
            elif strategy == "MEANREV":
                df["RSI"] = ta.rsi(df["close"], length=int(params["rsi_len"]))
                bb = ta.bbands(df["close"], length=int(params["bb_len"]), std=2.0)
                df["BBL"], df["BBM"], df["BBU"] = bb.iloc[:, 0], bb.iloc[:, 1], bb.iloc[:, 2]

            df.dropna(inplace=True)
            return df
        except Exception as e:
            logging.error(f"Errore calcolo indicatori: {e}")
            return pd.DataFrame()

    def _fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
        try: ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit); df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]); df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True); return df.dropna()
        except Exception: return pd.DataFrame()

    # --- CICLO PRINCIPALE (MODIFICATO) ---
    def run_analysis(self):
        self._update_watchlist()
        logging.info(f"🔎 Avvio analisi sulla watchlist di {len(self.watchlist)} asset...")
        for symbol, strat_config in self.watchlist.items():
            try:
                strategy_name = strat_config["strategy"]
                params = strat_config["params"]
                
                df = self._fetch_ohlcv(symbol, "1h", 250)
                if df.empty: continue
                
                # Calcola solo gli indicatori necessari
                df = self._calculate_indicators(df, strategy_name, params)
                if df.empty: continue
                
                last_signal_time = self.db.get_last_signal_time(symbol, strategy_name)
                if last_signal_time and (datetime.now(timezone.utc) - last_signal_time) < timedelta(minutes=self.dedupe_minutes):
                    continue

                # --- CHIAMA LA STRATEGIA DALLA MAPPA ---
                strategy_function = STRATEGY_MAP.get(strategy_name)
                if not strategy_function:
                    continue
                
                signal = strategy_function(df, params)
                
                if signal:
                    # Aggiunge il simbolo al segnale prima di salvarlo
                    signal['asset'] = symbol
                    signal['timeframe'] = "1h"
                    
                    logging.warning(f"🔥 Nuovo segnale trovato: {signal['asset']} {signal['side']}")
                    self.db.save_signal(signal)
                    self.sara.propose_trade(signal)

                time.sleep(self.exchange.rateLimit / 1000)
            except Exception as e:
                logging.error(f"Errore analisi {symbol}: {e}")

    def start(self):
        while True:
            self.run_analysis()
            logging.info(f"🕓 Ciclo di analisi completato. Attendo 30 minuti...")
            time.sleep(60 * 30)
