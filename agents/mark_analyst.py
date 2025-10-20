# ===============================================================
# MarkAnalyst v7.0 - The Render-Proof Final Version
# ===============================================================

import pandas as pd
import pandas_ta as ta
import json, logging, time, os
from datetime import datetime, timedelta

# Importa i tuoi moduli locali
from core.exchange_router import ExchangeRouter
from agents.sara_trader import SaraTrader
from agents.db_handler import DBHandler

# --- FUNZIONI HELPER ---
def _normalize_symbol_for_bybit(sym: str) -> str:
    s = sym.strip().upper().replace(":", "/").replace("//", "/")
    if ":USDT" in s: return s
    if s.endswith("USDT") and "/" not in s:
        base = s[:-4]
        return f"{base}/USDT:USDT"
    if s.endswith("/USDT"):
        return s + ":USDT"
    return s

def _col_exists(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns

class MarkAnalyst:
    def __init__(self, exchange_router: ExchangeRouter, sara: SaraTrader, db: DBHandler):
        self.router = exchange_router
        self.sara = sara
        self.db = db
        self.exchange = self.router.get("bybit")

        # --- PERCORSO A PROVA DI DEPLOY ---
        # Costruisce un percorso che parte dalla directory dello script corrente
        # e risale per trovare la cartella 'config'.
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'config', 'hall_of_fame.json')
        
        try:
            with open(config_path, "r") as f:
                raw = json.load(f)
            self.hall_of_fame = {}
            for k, v in raw.items():
                norm = _normalize_symbol_for_bybit(k)
                self.hall_of_fame[norm] = v
            logging.info(f"✅ Hall of Fame caricata con successo da: {config_path}")
        except FileNotFoundError:
            logging.error(f"‼️ ERRORE FATALE: File di configurazione non trovato in '{config_path}'.")
            raise SystemExit(f"Impossibile trovare {config_path}. Deploy fallito.")

        # Il resto del codice rimane invariato...
        self.assets = list(self.hall_of_fame.keys())
        self.timeframe = "1h"
        self.dedupe_minutes = 30
        self._rate_sleep = max(0.3, (getattr(self.exchange, "rateLimit", 300) or 300) / 1000.0)

        try:
            self.exchange.load_markets()
        except Exception as e:
            logging.warning("Impossibile caricare i mercati su Bybit: %s", e)

    # ... (TUTTO IL RESTO DEL FILE DA QUI IN POI È IDENTICO E CORRETTO) ...

    def _needed_lookback(self, params: dict) -> int:
        candidates = [int(params.get(k, 0)) for k in ["ema_fast", "ema_slow", "rsi_len", "bb_len"]]
        if not any(candidates): return 200
        return max(250, max(c for c in candidates if c) + 20)

    def get_data_and_indicators(self, symbol: str, timeframe: str, params: dict) -> pd.DataFrame:
        try:
            if hasattr(self.exchange, "symbols") and self.exchange.symbols and symbol not in self.exchange.symbols:
                logging.error(f"❌ Simbolo {symbol} non trovato su {self.exchange.id}. Skip.")
                return pd.DataFrame()
            limit = self._needed_lookback(params)
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not ohlcv: return pd.DataFrame()
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            for c in ['open','high','low','close','volume']:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df.dropna(inplace=True)
            if df.empty: return df
            if 'ema_fast' in params: df['EMA_F'] = ta.ema(df['close'], length=int(params['ema_fast']))
            if 'ema_slow' in params: df['EMA_S'] = ta.ema(df['close'], length=int(params['ema_slow']))
            if 'rsi_len' in params: df['RSI'] = ta.rsi(df['close'], length=int(params['rsi_len']))
            if 'bb_len' in params:
                bb = ta.bbands(df['close'], length=int(params['bb_len']), std=float(params.get('bb_mult', 2.0)))
                if bb is not None and not bb.empty:
                    df['BBL'], df['BBM'], df['BBU'] = bb.iloc[:,0], bb.iloc[:,1], bb.iloc[:,2]
            df.dropna(inplace=True)
            return df
        except Exception as e:
            logging.error(f"Errore dati/indicatori per {symbol}: {e}", exc_info=True)
            return pd.DataFrame()

    def _sanity_sl_tp(self, side: str, entry: float, sl: float, tp: float) -> bool:
        if not all(isinstance(v, (int, float)) for v in [entry, sl, tp]): return False
        if side == "LONG": return (sl < entry) and (tp > entry)
        else: return (sl > entry) and (tp < entry)

    def check_signals(self, df: pd.DataFrame, strategy_name: str, params: dict, symbol: str):
        if df.empty or len(df) < 3: return None
        c, p = df.iloc[-1], df.iloc[-2]
        side, entry, sl, tp = None, None, None, None
        rr = float(params.get('rr', 1.6))
        if strategy_name.upper() == "PULLBACK":
            if not (_col_exists(p, 'EMA_F') and _col_exists(p, 'EMA_S')): return None
            if (p['close'] > p['EMA_S']) and (p['low'] <= p['EMA_F']) and (c['close'] > c['open']):
                side = "LONG"; entry = float(c['close']); sl = float(p['low']); tp = entry + rr * (entry - sl)
            elif (p['close'] < p['EMA_S']) and (p['high'] >= p['EMA_F']) and (c['close'] < c['open']):
                side = "SHORT"; entry = float(c['close']); sl = float(p['high']); tp = entry - rr * (sl - entry)
        elif strategy_name.upper() == "MEANREV":
            if not all(_col_exists(p, x) for x in ['BBL','BBM','BBU','RSI']): return None
            rsi_oversold = float(params.get('rsi_oversold', 30)); rsi_overbought = float(params.get('rsi_overbought', 70))
            if (p['close'] <= p['BBL']) and (p['RSI'] <= rsi_oversold):
                side = "LONG"; entry = float(c['close']); sl = min(entry - (p['BBM']-p['BBL']), float(p['low'])); tp = float(p['BBM'])
            elif (p['close'] >= p['BBU']) and (p['RSI'] >= rsi_overbought):
                side = "SHORT"; entry = float(c['close']); sl = max(entry + (p['BBU']-p['BBM']), float(p['high'])); tp = float(p['BBM'])
        if side and self._sanity_sl_tp(side, entry, sl, tp):
            return {"asset": symbol, "timeframe": self.timeframe, "side": side, "entry": float(entry), "sl": float(sl), "tp": float(tp), "strategy": strategy_name.upper(), "params": json.dumps(params)}
        return None

    def run_analysis(self):
        if not self.hall_of_fame: return
        logging.info(f"Avvio ciclo di analisi su {len(self.assets)} asset dalla Hall of Fame.")
        for asset_symbol in self.assets:
            try:
                info = self.hall_of_fame[asset_symbol]; strategy_name = info['strategy']; params = info['params']
                df = self.get_data_and_indicators(asset_symbol, self.timeframe, params)
                if df.empty: time.sleep(self._rate_sleep); continue
                last_signal_time = self.db.get_last_signal_time(asset_symbol, strategy_name)
                if last_signal_time and (datetime.utcnow() - last_signal_time) < timedelta(minutes=self.dedupe_minutes):
                    time.sleep(self._rate_sleep); continue
                signal = self.check_signals(df, strategy_name, params, asset_symbol)
                if signal:
                    logging.warning(f"🔥 SEGNALE TROVATO! {json.dumps(signal)}")
                    self.db.save_signal(signal); self.sara.propose_trade(signal)
                time.sleep(self._rate_sleep)
            except Exception as e:
                logging.error(f"Errore critico durante l'analisi di {asset_symbol}: {e}", exc_info=True)

    def start(self):
        while True:
            self.run_analysis()
            logging.info("Ciclo di analisi completato. In attesa di 15 minuti...")
            time.sleep(60 * 15)
