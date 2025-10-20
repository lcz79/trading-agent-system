# ===============================================================
# MarkAnalyst v5.1 - Master Strategist (HOF-driven, Bybit-ready)
# ===============================================================

import pandas as pd
import pandas_ta as ta
import json, logging, time
from datetime import datetime, timedelta

from core.exchange_router import ExchangeRouter
from agents.sara_trader import SaraTrader
from agents.db_handler import DBHandler

def _normalize_symbol_for_bybit(sym: str) -> str:
    """Converte simboli comuni in formato Bybit CCXT ('BTC/USDT:USDT')."""
    s = sym.strip().upper().replace(":", "/").replace("//", "/")
    # già ok?
    if ":USDT" in s: 
        return s
    # es. BTCUSDT -> BTC/USDT:USDT
    if s.endswith("USDT") and "/" not in s:
        base = s[:-4]
        return f"{base}/USDT:USDT"
    # es. BTC/USDT -> BTC/USDT:USDT
    if s.endswith("/USDT"):
        return s + ":USDT"
    return s  # ultima spiaggia: lascio com’è

def _col_exists(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns

class MarkAnalyst:
    def __init__(self, exchange_router: ExchangeRouter, sara: SaraTrader, db: DBHandler):
        self.router = exchange_router
        self.sara = sara
        self.db = db
        self.exchange = self.router.get("bybit")

        # --- Hall of Fame ---
        try:
            with open("config/hall_of_fame.json", "r") as f:
                raw = json.load(f)
            # normalizzo i simboli per Bybit
            self.hall_of_fame = {}
            for k, v in raw.items():
                norm = _normalize_symbol_for_bybit(k)
                self.hall_of_fame[norm] = v
            logging.info(f"✅ Hall of Fame caricata. {len(self.hall_of_fame)} strategie pronte (Bybit normalized).")
        except FileNotFoundError:
            logging.error("‼️ File 'config/hall_of_fame.json' non trovato. L'agente non può operare.")
            self.hall_of_fame = {}

        # lavoriamo solo sugli asset in HOF
        self.assets = list(self.hall_of_fame.keys())
        self.timeframe = "1h"
        self.dedupe_minutes = 30  # non ripetere lo stesso segnale in X minuti
        self._rate_sleep = max(0.3, (getattr(self.exchange, "rateLimit", 300) or 300) / 1000.0)

        # carica i markets per validare simboli
        try:
            self.exchange.load_markets()
        except Exception as e:
            logging.warning("Impossibile load_markets su Bybit: %s", e)

    # ---------- Helpers ----------
    def _needed_lookback(self, params: dict) -> int:
        """Calcola il lookback minimo in base ai parametri richiesti dagli indicatori."""
        candidates = []
        # EMA
        if "ema_fast" in params: candidates.append(int(params["ema_fast"]))
        if "ema_slow" in params: candidates.append(int(params["ema_slow"]))
        if "ema_trend_len" in params: candidates.append(int(params["ema_trend_len"]))
        # RSI
        if "rsi_len" in params: candidates.append(int(params["rsi_len"]))
        # Bollinger
        if "bb_len" in params: candidates.append(int(params["bb_len"]))
        # un margine extra per dropna e controllo segnali
        if not candidates: 
            return 200
        return max(250, max(candidates) + 20)

    def get_data_and_indicators(self, symbol: str, timeframe: str, params: dict) -> pd.DataFrame:
        """Scarica OHLCV e calcola solo gli indicatori richiesti; ritorna df pulito."""
        try:
            # validazione simbolo sull’exchange
            if hasattr(self.exchange, "symbols") and symbol not in self.exchange.symbols:
                logging.error("❌ Simbolo %s non presente su %s. Skip.", symbol, self.exchange.id)
                return pd.DataFrame()

            limit = self._needed_lookback(params)
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not ohlcv:
                logging.warning("Nessun dato OHLCV per %s.", symbol)
                return pd.DataFrame()
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            for c in ['open','high','low','close','volume']:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df.dropna(inplace=True)
            if df.empty: 
                return df

            # Indicatori in base ai params presenti
            if 'ema_fast' in params:
                df['EMA_F'] = ta.ema(df['close'], length=int(params['ema_fast']))
            if 'ema_slow' in params:
                df['EMA_S'] = ta.ema(df['close'], length=int(params['ema_slow']))
            if 'ema_trend_len' in params and not _col_exists(df, 'EMA_S'):
                # se la strategia usa una singola EMA trend, usiamo EMA_S come trend
                df['EMA_S'] = ta.ema(df['close'], length=int(params['ema_trend_len']))

            if 'rsi_len' in params:
                df['RSI'] = ta.rsi(df['close'], length=int(params['rsi_len']))

            if 'bb_len' in params:
                bb_mult = float(params.get('bb_mult', 2.0))
                bb = ta.bbands(df['close'], length=int(params['bb_len']), std=bb_mult)
                if bb is not None and not bb.empty:
                    df['BBL'], df['BBM'], df['BBU'] = bb.iloc[:,0], bb.iloc[:,1], bb.iloc[:,2]

            df.dropna(inplace=True)
            return df
        except Exception as e:
            logging.error(f"Errore dati/indicatori per {symbol}: {e}")
            return pd.DataFrame()

    def _sanity_sl_tp(self, side: str, entry: float, sl: float, tp: float) -> bool:
        if side == "LONG":
            return (sl < entry) and (tp > entry)
        else:
            return (sl > entry) and (tp < entry)

    def check_signals(self, df: pd.DataFrame, strategy_name: str, params: dict, symbol: str):
        """Controlla il segnale della strategia (PULLBACK / MEANREV)."""
        if df.empty or len(df) < 3:
            return None

        c = df.iloc[-1]  # candela corrente
        p = df.iloc[-2]  # candela precedente

        side = None
        entry = sl = tp = None
        rr = float(params.get('rr', 1.6))

        if strategy_name.upper() == "PULLBACK":
            # richiede EMA_F e EMA_S
            if not (_col_exists(p, 'EMA_F') and _col_exists(p, 'EMA_S')):
                return None
            # LONG: trend up + pullback verso EMA_F + candela verde
            if (p['close'] > p['EMA_S']) and (p['low'] <= p['EMA_F']) and (c['close'] > c['open']):
                side = "LONG"; entry = float(c['close']); sl = float(p['low']); tp = entry + rr * (entry - sl)
            # SHORT: trend down + pullback verso EMA_F + candela rossa
            elif (p['close'] < p['EMA_S']) and (p['high'] >= p['EMA_F']) and (c['close'] < c['open']):
                side = "SHORT"; entry = float(c['close']); sl = float(p['high']); tp = entry - rr * (sl - entry)

        elif strategy_name.upper() == "MEANREV":
            # richiede BBL/BBU/BBM + RSI
            if not all(_col_exists(p, x) for x in ['BBL','BBM','BBU']) or not _col_exists(p,'RSI'):
                return None
            rsi_oversold = float(params.get('rsi_oversold', 30))
            rsi_overbought = float(params.get('rsi_overbought', 70))
            # LONG: tocco banda bassa + RSI oversold → target media
            if (p['close'] <= p['BBL']) and (p['RSI'] <= rsi_oversold):
                side = "LONG"; entry = float(c['close']); sl = min(entry - (p['BBM']-p['BBL']), float(p['low']))
                tp = float(p['BBM'])
            # SHORT: tocco banda alta + RSI overbought → target media
            elif (p['close'] >= p['BBU']) and (p['RSI'] >= rsi_overbought):
                side = "SHORT"; entry = float(c['close']); sl = max(entry + (p['BBU']-p['BBM']), float(p['high']))
                tp = float(p['BBM'])

        else:
            # altre strategie in HOF? per ora ignoro con warning
            logging.warning("Strategia '%s' non riconosciuta per %s. Skip.", strategy_name, symbol)
            return None

        if side and self._sanity_sl_tp(side, entry, sl, tp):
            return {
                "asset": symbol,
                "timeframe": self.timeframe,
                "side": side,
                "entry": float(entry),
                "sl": float(sl),
                "tp": float(tp),
                "strategy": strategy_name.upper(),
                "params": json.dumps(params)
            }
        return None

    def run_analysis(self):
        """Ciclo principale: per ogni asset della HOF, calcola il segnale."""
        if not self.hall_of_fame:
            logging.warning("Nessuna strategia nella Hall of Fame. Analisi sospesa.")
            return

        logging.info(f"Avvio ciclo di analisi su {len(self.assets)} asset dalla Hall of Fame (tf={self.timeframe}).")

        for asset_symbol in self.assets:
            try:
                info = self.hall_of_fame.get(asset_symbol, {})
                strategy_name = str(info.get('strategy', 'PULLBACK')).upper()
                params = info.get('params', {}) or {}

                # dati + indicatori
                df = self.get_data_and_indicators(asset_symbol, self.timeframe, params)
                if df.empty:
                    time.sleep(self._rate_sleep)
                    continue

                # dedupe (per asset+strategia) — se il tuo DBHandler non supporta il 2° arg, rimuovi `strategy_name`
                last_signal_time = self.db.get_last_signal_time(asset_symbol, strategy_name)
                if last_signal_time and (datetime.utcnow() - last_signal_time) < timedelta(minutes=self.dedupe_minutes):
                    logging.info("Segnale recente %s [%s], attendo.", asset_symbol, strategy_name)
                    time.sleep(self._rate_sleep)
                    continue

                signal = self.check_signals(df, strategy_name, params, asset_symbol)
                if signal:
                    logging.warning(f"🔥 SEGNALE TROVATO! {signal}")
                    self.db.save_signal(signal)
                    # SaraTrader si aspetta probabilmente keys: asset, side, entry, sl, tp...
                    self.sara.propose_trade(signal)

                time.sleep(self._rate_sleep)

            except Exception as e:
                logging.error(f"Errore analisi {asset_symbol}: {e}")

    def start(self):
        while True:
            self.run_analysis()
            logging.info("Ciclo di analisi completato. Attendo 15 minuti...")
            time.sleep(60 * 15)
