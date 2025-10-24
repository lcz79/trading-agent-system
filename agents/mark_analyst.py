# ===============================================================
# MARK ANALYST v12.0 — Esecutore Adattivo PRO
# ===============================================================
# Logica:
# 1. Carica lo "Strategy Book PRO" generato da Leo v4.5.
# 2. Per ogni asset, determina il regime di mercato attuale (UP/DOWN/RANGE).
# 3. Cerca nel libro la strategia più performante (score più alto)
#    che sia adatta al regime corrente.
# 4. Se la trova, propone il trade. Altrimenti, non fa nulla.
# ===============================================================

import pandas as pd
import logging
import time
import json
import os
from datetime import datetime, timedelta, timezone

from core.exchange_router import ExchangeRouter
from agents.sara_trader_pro import SaraTrader
from agents.db_handler import DBHandler

# --- Importazione diretta dal motore di ricerca v4.5 PRO ---
from tools.leo_optimizer_v4_5_pro import (
    STRATEGY_GEN_MAP,
    ensure_indicators,
    classify_regime
)

class MarkAnalyst:
    def __init__(self, exchange_router: ExchangeRouter, sara: SaraTrader, db: DBHandler):
        self.router = exchange_router
        self.sara = sara
        self.db = db
        self.exchange = self.router.get("bybit")
        self.strategy_book_path = "config/strategy_book_pro.json"
        self.strategy_book = {}
        self.dedupe_minutes = 60  # Aumentato per evitare segnali troppo ravvicinati

        if not self.exchange:
            raise ConnectionError("❌ Nessun exchange disponibile.")
        
        logging.info("✅ MarkAnalyst v12.0 'Esecutore Adattivo PRO' inizializzato.")

    def _load_strategy_book(self):
        try:
            with open(self.strategy_book_path, 'r') as f:
                self.strategy_book = json.load(f)
            logging.info(f"✅ Caricato Strategy Book PRO con {len(self.strategy_book)} asset.")
        except (FileNotFoundError, json.JSONDecodeError):
            logging.error(f"‼️ STRATEGY BOOK '{self.strategy_book_path}' non trovato o corrotto!")
            self.strategy_book = {}

    def _fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 400) -> pd.DataFrame:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            return df.dropna()
        except Exception as e:
            logging.error(f"Errore fetch OHLCV per {symbol} {timeframe}: {e}")
            return pd.DataFrame()

    def _find_best_strategy_for_regime(self, available_strategies: List[Dict], current_regime: str) -> Dict:
        """
        Cerca tra le strategie disponibili quella migliore per il regime attuale.
        - PULLBACK & VOLBREAK -> UP/DOWN
        - MEANREV & RSI_DIV -> RANGE
        """
        candidates = []
        for strat in available_strategies:
            strat_type = strat.get("strategy")
            is_match = False
            if current_regime in ["UP", "DOWN"] and strat_type in ["PULLBACK", "VOLBREAK"]:
                is_match = True
            elif current_regime == "RANGE" and strat_type in ["MEANREV", "RSI_DIV"]:
                is_match = True
            
            if is_match:
                candidates.append(strat)
        
        if not candidates:
            return {}
        
        # Ritorna il candidato con lo score più alto
        return max(candidates, key=lambda s: s.get("quality_test", {}).get("score", 0))

    def run_analysis(self):
        self._load_strategy_book()
        if not self.strategy_book:
            logging.warning("Strategy Book vuoto. In attesa che Leo lo popoli.")
            return
            
        logging.info(f"🔎 Avvio analisi regime-aware su {len(self.strategy_book)} asset...")
        
        for symbol, available_strategies in self.strategy_book.items():
            if not available_strategies:
                continue

            try:
                # Per determinare il regime, usiamo il timeframe più comune o il più lungo (es. 1h)
                # tra le strategie disponibili per quell'asset.
                tf_for_regime = available_strategies[0].get("timeframe", "1h")
                df_regime = self._fetch_ohlcv(symbol, tf_for_regime, limit=300)
                if df_regime.empty:
                    continue
                
                # Calcola indicatori di regime e determina il regime attuale (ultima candela completa)
                df_regime = ensure_indicators(df_regime, {}) # Calcola indicatori base
                current_regime = classify_regime(df_regime.iloc[-2])
                logging.info(f"🔍 {symbol} | Regime attuale ({tf_for_regime}): {current_regime}")

                # Trova la migliore strategia per questo regime
                best_strat = self._find_best_strategy_for_regime(available_strategies, current_regime)
                
                if not best_strat:
                    logging.info(f"  -> Nessuna strategia adatta al regime {current_regime} per {symbol}.")
                    continue

                # Ora abbiamo la strategia da usare. Verifichiamo se c'è un segnale.
                strategy_name = best_strat["strategy"]
                params = best_strat["params"]
                timeframe = best_strat["timeframe"]
                strategy_id = best_strat["strategy_id"]

                last_signal_time = self.db.get_last_signal_time(symbol, strategy_id)
                if last_signal_time and (datetime.now(timezone.utc) - last_signal_time) < timedelta(minutes=self.dedupe_minutes):
                    continue

                df_signal = self._fetch_ohlcv(symbol, timeframe, limit=400)
                if df_signal.empty:
                    continue
                
                df_signal = ensure_indicators(df_signal.copy(), params)
                df_signal["REGIME"] = df_signal.apply(classify_regime, axis=1)

                strategy_function = STRATEGY_GEN_MAP.get(strategy_name)
                if not strategy_function:
                    continue
                
                all_signals = strategy_function(df_signal, params)

                if all_signals:
                    last_signal_entry = all_signals[-1]
                    if last_signal_entry[0] >= len(df_signal) - 2: # Segnale fresco
                        _, side, entry, sl, tp = last_signal_entry
                        
                        signal = {
                            "asset": symbol, "timeframe": timeframe, "side": side,
                            "entry": entry, "sl": sl, "tp": tp,
                            "strategy": strategy_id, # Usiamo l'ID univoco
                            "params": json.dumps(params)
                        }
                        
                        logging.warning(f"🔥 SEGNALE SCELTO: {signal['asset']} | {signal['strategy']} | {signal['side']}")
                        self.db.save_signal(signal)
                        self.sara.propose_trade(signal)
                
                time.sleep(self.exchange.rateLimit / 1000)

            except Exception as e:
                logging.error(f"Errore fatale analisi {symbol}: {e}", exc_info=True)

    def start(self):
        while True:
            self.run_analysis()
            logging.info(f"🕓 Ciclo analisi completato. Attendo 15 minuti...")
            time.sleep(60 * 15)
