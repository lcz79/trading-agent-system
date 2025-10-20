# ===============================================================
# MarkAnalyst v5 - Master Strategist
# Agente di analisi che utilizza la Hall of Fame per decisioni
# basate su backtest a lungo termine.
# ===============================================================

import pandas as pd
import pandas_ta as ta
import json, logging, time
from datetime import datetime, timedelta

from core.exchange_router import ExchangeRouter
from agents.sara_trader import SaraTrader
from agents.db_handler import DBHandler

class MarkAnalyst:
    def __init__(self, exchange_router: ExchangeRouter, sara: SaraTrader, db: DBHandler):
        self.router = exchange_router
        self.sara = sara
        self.db = db
        self.exchange = self.router.get("bybit")
        
        # --- MODIFICA CHIAVE: CARICA LA HALL OF FAME ---
        try:
            with open("config/hall_of_fame.json", "r") as f:
                self.hall_of_fame = json.load(f)
            logging.info(f"✅ Hall of Fame caricata. {len(self.hall_of_fame)} strategie vincenti pronte.")
        except FileNotFoundError:
            logging.error("‼️ File 'config/hall_of_fame.json' non trovato. L'agente non può operare.")
            self.hall_of_fame = {}

        # Gli asset da analizzare sono solo quelli nella Hall of Fame
        self.assets = list(self.hall_of_fame.keys())
        self.timeframe = "1h"
        self.dedupe_minutes = 30 # Non inviare lo stesso segnale per 30 minuti

    def get_data_and_indicators(self, symbol, timeframe, params):
        """Recupera i dati e calcola solo gli indicatori necessari per la strategia."""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=250)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Calcolo dinamico degli indicatori in base ai parametri richiesti
            if 'ema_fast' in params: df['EMA_F'] = ta.ema(df['close'], length=params['ema_fast'])
            if 'ema_slow' in params: df['EMA_S'] = ta.ema(df['close'], length=params['ema_slow'])
            if 'rsi_len' in params: df['RSI'] = ta.rsi(df['close'], length=params['rsi_len'])
            if 'bb_len' in params:
                bb = ta.bbands(df['close'], length=params['bb_len'], std=params.get('bb_mult', 2.0))
                if bb is not None and not bb.empty:
                    df['BBL'], df['BBM'], df['BBU'] = bb.iloc[:,0], bb.iloc[:,1], bb.iloc[:,2]
            
            return df.dropna()
        except Exception as e:
            logging.error(f"Errore nel recupero dati/indicatori per {symbol}: {e}")
            return pd.DataFrame()

    def check_signals(self, df, strategy_name, params):
        """Controlla i segnali di trading in base alla strategia specifica."""
        if df.empty or len(df) < 2: return None
        
        c = df.iloc[-1] # Candela corrente
        p = df.iloc[-2] # Candela precedente
        
        side, entry, sl, tp = None, None, None, None

        if strategy_name == "PULLBACK":
            if p['close'] > p['EMA_S'] and p['low'] <= p['EMA_F'] and c['close'] > c['open']:
                side = "LONG"
                entry, sl = c['close'], p['low']
                tp = entry + (entry - sl) * params.get('rr', 1.5)
            elif p['close'] < p['EMA_S'] and p['high'] >= p['EMA_F'] and c['close'] < c['open']:
                side = "SHORT"
                entry, sl = c['close'], p['high']
                tp = entry - (sl - entry) * params.get('rr', 1.5)

        elif strategy_name == "MEANREV":
            if p['close'] < p['BBL'] and p['RSI'] < params['rsi_oversold']:
                side = "LONG"
                entry, sl, tp = c['close'], p['low'], p['BBM']
            elif p['close'] > p['BBU'] and p['RSI'] > params['rsi_overbought']:
                side = "SHORT"
                entry, sl, tp = c['close'], p['high'], p['BBM']

        if side:
            return {
                "asset": c['symbol'], "timeframe": self.timeframe, "side": side,
                "entry": entry, "sl": sl, "tp": tp,
                "strategy": strategy_name, "params": json.dumps(params)
            }
        return None

    def run_analysis(self):
        """Ciclo principale di analisi: usa la strategia giusta per ogni asset."""
        if not self.hall_of_fame:
            logging.warning("Nessuna strategia nella Hall of Fame. L'analisi è sospesa.")
            return

        logging.info(f"Avvio ciclo di analisi su {len(self.assets)} asset dalla Hall of Fame.")
        
        for asset_symbol in self.assets:
            try:
                # Recupera la strategia e i parametri specifici per l'asset
                strategy_info = self.hall_of_fame[asset_symbol]
                strategy_name = strategy_info['strategy']
                params = strategy_info['params']

                logging.info(f"Analizzo {asset_symbol} con strategia '{strategy_name}'...")
                
                df = self.get_data_and_indicators(asset_symbol, self.timeframe, params)
                if df.empty: continue
                df['symbol'] = asset_symbol

                # Controlla se abbiamo già inviato un segnale recente per questo asset
                last_signal_time = self.db.get_last_signal_time(asset_symbol)
                if last_signal_time and (datetime.utcnow() - last_signal_time) < timedelta(minutes=self.dedupe_minutes):
                    logging.info(f"Segnale recente per {asset_symbol}, attendo.")
                    continue

                signal = self.check_signals(df, strategy_name, params)

                if signal:
                    logging.warning(f"🔥 SEGNALE TROVATO! {signal}")
                    self.db.save_signal(signal)
                    self.sara.propose_trade(signal)
                
                time.sleep(self.exchange.rateLimit / 1000) # Rispetta i rate limit

            except Exception as e:
                logging.error(f"Errore critico durante l'analisi di {asset_symbol}: {e}")

    def start(self):
        while True:
            self.run_analysis()
            logging.info("Ciclo di analisi completato. In attesa di 15 minuti...")
            time.sleep(60 * 15)
