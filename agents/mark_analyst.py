# ===============================================================
# MARK ANALYST v7.1 "Manifesto" — by lcz79
# ===============================================================
# Implementazione della visione strategica di lcz79.
# ✅ Scoperta dinamica degli asset basata sulla tua logica di discovery.
# ✅ Caching efficiente per la lista di asset.
# ✅ Fusione della Hall of Fame con la watchlist dinamica.
# ✅ Strategia di default per i nuovi asset.
# ===============================================================

import pandas as pd
import pandas_ta as ta
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from core.exchange_router import ExchangeRouter
from agents.sara_trader_pro import SaraTrader
from agents.db_handler import DBHandler

# --- HALL OF FAME STRATEGICA (SEMPRE PRIORITARIA) ---
HALL_OF_FAME_DATA = {
    "BTC/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 20, "ema_slow": 100}},
    "ETH/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 10, "ema_slow": 50}},
    "SOL/USDT:USDT": {"strategy": "PULLBACK", "params": {"ema_fast": 30, "ema_slow": 50}},
}

# --- STRATEGIA DI DEFAULT PER ASSET SCOPERTI ---
DEFAULT_STRATEGY = {
    "strategy": "PULLBACK",
    "params": {"ema_fast": 20, "ema_slow": 50}
}

class MarkAnalyst:
    # --- Parametri di Discovery (dalla tua specifica) ---
    _DISCOVERY_MIN_VOL_USDT = 10_000_000
    _DISCOVERY_TOP_N = 40
    _DISCOVERY_TTL_SEC = 6 * 3600  # 6 ore di cache
    _cached_dynamic_list = []
    _last_discovery_ts = 0

    def __init__(self, exchange_router: ExchangeRouter, sara: SaraTrader, db: DBHandler):
        self.router = exchange_router
        self.sara = sara
        self.db = db
        self.exchange = self.router.get("bybit")
        self.watchlist = {}
        self.dedupe_minutes = 30
        
        if not self.exchange:
            raise ConnectionError("❌ Nessun exchange disponibile.")
        
        logging.info(f"✅ MarkAnalyst v7.1 'Manifesto' inizializzato.")
        # La prima discovery viene fatta all'avvio
        self._update_watchlist()

    # --- LOGICA DI DISCOVERY (BASATA SUL TUO CODICE) ---
    def _is_linear_usdt_perp(self, mkt: dict) -> bool:
        try:
            if not mkt.get('active', True): return False
            if not mkt.get('linear', False): return False
            if (mkt.get('settle') or '').upper() != 'USDT': return False
            return mkt.get('type') == 'swap'
        except Exception:
            return False

    def _discover_dynamic_markets(self) -> list[str]:
        now = time.time()
        if (now - self._last_discovery_ts) < self._DISCOVERY_TTL_SEC and self._cached_dynamic_list:
            logging.info("Discovery: uso la lista di asset dalla cache.")
            return self._cached_dynamic_list
        
        logging.info("🔭 Inizio scoperta dinamica degli asset (chiamate API in corso)...")
        try:
            markets = self.exchange.load_markets()
            tickers = self.exchange.fetch_tickers() # Chiamata singola per efficienza
        except Exception as e:
            logging.error(f"Discovery fallita durante il fetch dei dati di mercato: {e}")
            return self._cached_dynamic_list or []

        candidates = []
        for symbol, ticker in tickers.items():
            market = markets.get(symbol)
            if not market or not self._is_linear_usdt_perp(market):
                continue
            
            volume = ticker.get('quoteVolume', 0)
            if volume >= self._DISCOVERY_MIN_VOL_USDT:
                candidates.append((symbol, volume))
        
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_syms = [s for s, _ in candidates[:self._DISCOVERY_TOP_N]]
        
        self._cached_dynamic_list = top_syms
        self._last_discovery_ts = time.time()
        logging.info(f"Discovery completata: trovati {len(top_syms)} mercati liquidi. Top 3: {top_syms[:3]}")
        return top_syms

    def _update_watchlist(self):
        """Fonde la Hall of Fame con la lista dinamica per creare la watchlist finale."""
        hof_symbols = list(HALL_OF_FAME_DATA.keys())
        dynamic_symbols = self._discover_dynamic_markets()
        
        # Unisci le liste dando priorità alla HOF
        final_list = {**{s: DEFAULT_STRATEGY for s in dynamic_symbols}, **HALL_OF_FAME_DATA}
        
        self.watchlist = final_list
        logging.info(f"✅ Watchlist aggiornata: {len(self.watchlist)} asset totali pronti per l'analisi.")

    # ... (Le funzioni di utility e di analisi _fetch_ohlcv, etc. rimangono invariate) ...
    def _fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
        try: ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit); df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]); df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True); return df.dropna()
        except Exception: return pd.DataFrame()
    def _calculate_indicators(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        if df.empty: return df
        try:
            if "ema_fast" in params: df["EMA_F"] = ta.ema(df["close"], length=int(params["ema_fast"]))
            if "ema_slow" in params: df["EMA_S"] = ta.ema(df["close"], length=int(params["ema_slow"]))
            df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
            df.dropna(inplace=True); return df
        except Exception: return df
    def _risk_reward_dynamic(self, entry: float, atr: float, side: str, rr_mult: float = 1.5):
        if side == "LONG": sl, tp = entry - atr, entry + rr_mult * atr
        else: sl, tp = entry + atr, entry - rr_mult * atr
        return sl, tp
    def _sanity_check(self, side, entry, sl, tp): return sl < entry < tp if side == "LONG" else tp < entry < sl
    def _check_pullback(self, df: pd.DataFrame, params: dict, symbol: str):
        if len(df) < 2: return None
        c, p = df.iloc[-1], df.iloc[-2]
        if (c.get("ATR", 0) / c["close"]) > 0.05: return None
        side = None
        if (p["close"] > p["EMA_S"]) and (p["low"] <= p["EMA_F"]) and (c["close"] > c["open"]): side = "LONG"
        elif (p["close"] < p["EMA_S"]) and (p["high"] >= p["EMA_F"]) and (c["close"] < c["open"]): side = "SHORT"
        else: return None
        sl, tp = self._risk_reward_dynamic(float(c["close"]), c["ATR"], side)
        if not self._sanity_check(side, float(c["close"]), sl, tp): return None
        return {"asset": symbol, "timeframe": "1h", "side": side, "entry": float(c["close"]), "sl": float(sl), "tp": float(tp), "strategy": "PULLBACK", "params": json.dumps(params)}

    # --- CICLO PRINCIPALE ---
    def run_analysis(self):
        # La watchlist viene aggiornata all'inizio di ogni grande ciclo.
        self._update_watchlist()
        
        logging.info(f"🔎 Avvio analisi sulla watchlist di {len(self.watchlist)} asset...")
        for symbol, strat in self.watchlist.items():
            try:
                df = self._fetch_ohlcv(symbol, "1h", 250)
                if df.empty: continue
                df = self._calculate_indicators(df, strat["params"])
                if df.empty: continue
                
                last_signal_time = self.db.get_last_signal_time(symbol, strat["strategy"])
                if last_signal_time and (datetime.now(timezone.utc) - last_signal_time) < timedelta(minutes=self.dedupe_minutes):
                    continue

                signal = self._check_pullback(df, strat["params"], symbol) # Semplificato per usare solo PULLBACK
                
                if signal:
                    logging.warning(f"🔥 Nuovo segnale trovato: {signal['asset']} {signal['side']}")
                    self.db.save_signal(signal)
                    self.sara.propose_trade(signal)

                time.sleep(self.exchange.rateLimit / 1000)
            except Exception as e:
                logging.error(f"Errore analisi {symbol}: {e}")

    def start(self):
        """Ciclo di vita dell'analista."""
        while True:
            self.run_analysis()
            logging.info(f"🕓 Ciclo di analisi completato. Attendo 30 minuti...")
            time.sleep(60 * 30)
