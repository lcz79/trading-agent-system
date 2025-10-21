# ===============================================================================
# MITRAGLIERE A.I. — LEO OPTIMIZER v2 (Auto-Backtest + Auto-HOF)
# ===============================================================================
# Autore: lcz79 & Copilot
# Data: 2025-10-21
# Scopo: Ottimizzare automaticamente i parametri per ogni asset (Bybit),
#        usando multiprocessing, metriche robuste e aggiornando la Hall of Fame.
# ===============================================================================

import argparse
import json
import logging
import time
import pandas as pd
import pandas_ta as ta
import numpy as np
from multiprocessing import Pool, cpu_count
from itertools import product
import ccxt

# Configurazione del logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# --- DEFINIZIONE STRATEGIE (per il backtesting) ---

def _get_indicators(df, params):
    """Calcola gli indicatori necessari per tutte le strategie."""
    # Pullback
    if "ema_fast" in params and "ema_slow" in params:
        df[f'EMA_{params["ema_fast"]}'] = ta.ema(df["close"], length=params["ema_fast"])
        df[f'EMA_{params["ema_slow"]}'] = ta.ema(df["close"], length=params["ema_slow"])
    # Mean Reversion
    if "bb_len" in params and "rsi_len" in params:
        bb = ta.bbands(df["close"], length=params["bb_len"], std=2)
        df["BBL"], df["BBM"], df["BBU"] = bb.iloc[:, 0], bb.iloc[:, 1], bb.iloc[:, 2]
        df["RSI"] = ta.rsi(df["close"], length=params["rsi_len"])
    # Comune
    df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    return df.dropna()

def backtest_runner(args):
    """Esegue un singolo backtest per una combinazione. Progettato per il multiprocessing."""
    df_full, strategy_name, params = args
    df = df_full.copy()

    # Calcolo indicatori
    try:
        df = _get_indicators(df, params)
        if df.empty: return None
    except Exception:
        return None

    # Simulazione trade
    trades = []
    position = None
    for i in range(1, len(df)):
        c = df.iloc[i] # Candela corrente
        p = df.iloc[i-1] # Candela precedente

        # Logica di entrata
        if not position:
            side = None
            if strategy_name == "PULLBACK":
                if p[f'EMA_{params["ema_fast"]}'] > p[f'EMA_{params["ema_slow"]}'] and p['low'] <= p[f'EMA_{params["ema_fast"]}'] and c['close'] > c['open']: side = "LONG"
                elif p[f'EMA_{params["ema_fast"]}'] < p[f'EMA_{params["ema_slow"]}'] and p['high'] >= p[f'EMA_{params["ema_fast"]}'] and c['close'] < c['open']: side = "SHORT"
            
            if side:
                entry_price = c['close']
                sl = entry_price - c['ATR'] if side == "LONG" else entry_price + c['ATR']
                tp = entry_price + 1.5 * c['ATR'] if side == "LONG" else entry_price - 1.5 * c['ATR']
                position = {'side': side, 'entry': entry_price, 'sl': sl, 'tp': tp}

        # Logica di uscita
        if position:
            if position['side'] == 'LONG':
                if c['low'] <= position['sl']: trades.append(-1); position = None
                elif c['high'] >= position['tp']: trades.append(1); position = None
            elif position['side'] == 'SHORT':
                if c['high'] >= position['sl']: trades.append(-1); position = None
                elif c['low'] <= position['tp']: trades.append(1); position = None

    # Calcolo metriche
    if not trades: return {"strategy": strategy_name, "params": params, "pnl": 0, "trades": 0, "win_rate": 0, "score": 0}
    
    pnl = sum(trades)
    win_rate = (trades.count(1) / len(trades)) * 100
    score = pnl * np.sqrt(len(trades)) # Score che bilancia profitti e numero di trade
    
    return {"strategy": strategy_name, "params": params, "pnl": pnl, "trades": len(trades), "win_rate": win_rate, "score": score}

# --- CLASSE PRINCIPALE LEO OPTIMIZER ---

class LeoOptimizerV2:
    def __init__(self, args):
        self.args = args
        self.exchange = ccxt.bybit({'options': {'defaultType': 'swap'}})
        self.hall_of_fame_path = args.hof
        logging.info(f"🦁 LeoOptimizer v2 inizializzato. Processi: {args.processes}. Output HOF: {args.hof}")

    def _discover_assets(self):
        """Scopre i TOP N asset più liquidi."""
        logging.info(f"🔭 Scopro i top {self.args.top} asset per volume...")
        try:
            markets = self.exchange.fetch_markets()
            tickers = self.exchange.fetch_tickers()
            
            candidates = []
            for m in markets:
                if m.get('linear') and m.get('settle') == 'USDT' and m.get('active'):
                    symbol = m['symbol']
                    ticker = tickers.get(symbol)
                    if ticker and ticker.get('quoteVolume'):
                        candidates.append((symbol, ticker['quoteVolume']))

            candidates.sort(key=lambda x: x[1], reverse=True)
            return [s for s, v in candidates[:self.args.top]]
        except Exception as e:
            logging.error(f"Errore durante la scoperta degli asset: {e}")
            return []

    def _get_history(self, asset):
        """Scarica lo storico per un asset."""
        try:
            logging.info(f"💾 Scarico storico per {asset} ({self.args.months} mesi, timeframe {self.args.timeframe})...")
            since = self.exchange.parse8601((pd.Timestamp.now(tz='UTC') - pd.DateOffset(months=self.args.months)).isoformat())
            limit = 5000 # Un numero alto per sicurezza
            ohlcv = self.exchange.fetch_ohlcv(asset, self.args.timeframe, since=since, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logging.error(f"Impossibile scaricare lo storico per {asset}: {e}")
            return pd.DataFrame()

    def _generate_param_grid(self):
        """Genera la griglia di parametri da testare."""
        pb_emas_fast = [10, 20, 30, 50]
        pb_emas_slow = [50, 100, 150, 200]
        
        grid = []
        for fast, slow in product(pb_emas_fast, pb_emas_slow):
            if fast >= slow: continue
            grid.append(("PULLBACK", {"ema_fast": fast, "ema_slow": slow}))
        # Qui in futuro si aggiungerà la griglia per MEANREV
        return grid

    def _update_hof(self, best_strategies):
        """Aggiorna il file JSON della Hall of Fame."""
        try:
            with open(self.hall_of_fame_path, 'r') as f:
                hof_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            hof_data = {}
            
        for asset, result in best_strategies.items():
            logging.warning(f"🏆 Aggiornamento HOF per {asset}: {result['strategy']} con Score {result['score']:.2f}")
            hof_data[asset] = {"strategy": result['strategy'], "params": result['params']}
            
        with open(self.hall_of_fame_path, 'w') as f:
            json.dump(hof_data, f, indent=4, sort_keys=True)
        logging.info(f"✅ Hall of Fame salvata in '{self.hall_of_fame_path}'.")

    def run(self):
        """Esegue il ciclo di ottimizzazione."""
        if self.args.mode == 'discover':
            assets_to_test = self._discover_assets()
        else:
            assets_to_test = [a.strip() for a in self.args.assets.split(',')]

        if not assets_to_test:
            logging.error("Nessun asset da analizzare. Termino.")
            return

        logging.info(f"Inizio ottimizzazione per {len(assets_to_test)} asset: {assets_to_test[:5]}...")
        
        best_strategies_found = {}
        param_grid = self._generate_param_grid()

        for asset in assets_to_test:
            df_history = self._get_history(asset)
            if df_history.empty or len(df_history) < 200:
                logging.warning(f"Dati insufficienti per {asset}. Salto.")
                continue

            tasks = [(df_history, name, params) for name, params in param_grid]
            
            logging.info(f"🚀 Avvio di {len(tasks)} backtest paralleli per {asset} su {self.args.processes} core...")
            start_time = time.time()
            with Pool(self.args.processes) as pool:
                results = pool.map(backtest_runner, tasks)
            duration = time.time() - start_time
            logging.info(f"⏱️  Ottimizzazione per {asset} completata in {duration:.2f} secondi.")

            valid_results = [r for r in results if r and r['trades'] >= self.args.mintrades]
            if not valid_results:
                logging.warning(f"Nessuna configurazione valida trovata per {asset} (min {self.args.mintrades} trade).")
                continue

            best_result = max(valid_results, key=lambda x: x['score'])
            best_strategies_found[asset] = best_result
        
        if best_strategies_found:
            self._update_hof(best_strategies_found)

# --- Esecuzione da riga di comando ---
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Leo Optimizer V2 - Backtester Parallelo")
    parser.add_argument('--mode', type=str, choices=['discover', 'manual'], default='discover', help="Modalità di selezione asset")
    parser.add_argument('--top', type=int, default=30, help="Numero di asset da scoprire per volume")
    parser.add_argument('--assets', type=str, help="Lista di asset manuale, separati da virgola")
    parser.add_argument('--timeframe', type=str, default='1h', help="Timeframe per l'analisi")
    parser.add_argument('--months', type=int, default=9, help="Mesi di storico da analizzare")
    parser.add_argument('--mintrades', type=int, default=12, help="Numero minimo di trade per considerare una strategia valida")
    parser.add_argument('--processes', type=int, default=max(1, cpu_count() - 1), help="Numero di processi paralleli")
    parser.add_argument('--hof', type=str, default='config/hall_of_fame.json', help="Path del file Hall of Fame da aggiornare")
    
    args = parser.parse_args()
    
    if args.mode == 'manual' and not args.assets:
        parser.error("--assets è richiesto per la modalità 'manual'")

    optimizer = LeoOptimizerV2(args)
    optimizer.run()