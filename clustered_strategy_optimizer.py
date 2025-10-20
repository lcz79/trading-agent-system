# ===============================================================
# clustered_strategy_optimizer_v5.py
# Total Explorer: Multi-Strategy & Wide Grid Optimization
# ===============================================================
import os, json, logging, warnings, itertools
import pandas as pd
import pandas_ta as ta
from multiprocessing import Pool, cpu_count
from tqdm import tqdm

warnings.simplefilter(action='ignore', category=FutureWarning)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s] %(message)s')

DATA_DIR = "historical_data"
TIMEFRAME = "1h"
CORES = max(1, cpu_count() - 1)
ASSET_CLUSTERS = {
    "CRYPTO": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"],
    "INDICES": ["SPXUSDT"]
}

# ===============================================================
# GRIGLIA DI OTTIMIZZAZIONE AMPLIATA
# ===============================================================
PARAM_GRID = {
    "PULLBACK": {
        "ema_fast": [10, 20, 30],
        "ema_slow": [50, 100, 200],
        "rr": [1.5, 2.0, 3.0]
    },
    "MEANREV": {
        "bb_len": [20, 30],
        "bb_mult": [2.0, 2.5],
        "rsi_len": [14, 21],
        "rsi_oversold": [25, 30],
        "rsi_overbought": [70, 75]
    }
}
# ... (add_indicators è aggiornato per includere RSI) ...
def add_indicators(df, params):
    if 'ema_fast' in params: df['EMA_F'] = ta.ema(df['close'], length=params['ema_fast'])
    if 'ema_slow' in params: df['EMA_S'] = ta.ema(df['close'], length=params['ema_slow'])
    if 'rsi_len' in params: df['RSI'] = ta.rsi(df['close'], length=params['rsi_len'])
    if 'bb_len' in params:
        bb = ta.bbands(df['close'], length=params['bb_len'], std=params.get('bb_mult', 2.0))
        if bb is not None and not bb.empty:
            df['BBL'], df['BBM'], df['BBU'] = bb.iloc[:,0], bb.iloc[:,1], bb.iloc[:,2]
    return df.dropna()

# ===============================================================
# MOTORE DI BACKTEST V5 (MULTI-STRATEGIA)
# ===============================================================
def backtest(df, params, strategy_type):
    trades = []
    highs, lows = df['high'].to_numpy(), df['low'].to_numpy()
    
    for i in range(1, len(df)):
        c, p = df.iloc[i], df.iloc[i-1]
        entry_price, sl, tp, side = None, None, None, None

        if strategy_type == "PULLBACK":
            if p['close'] > p['EMA_S'] and p['low'] <= p['EMA_F'] and c['close'] > c['open']:
                side = "LONG"; entry_price, sl = c['close'], p['low']; tp = entry_price + (entry_price - sl) * params.get('rr', 1.5)
            elif p['close'] < p['EMA_S'] and p['high'] >= p['EMA_F'] and c['close'] < c['open']:
                side = "SHORT"; entry_price, sl = c['close'], p['high']; tp = entry_price - (sl - entry_price) * params.get('rr', 1.5)
        
        elif strategy_type == "MEANREV":
            if p['close'] < p['BBL'] and p['RSI'] < params['rsi_oversold']:
                side = "LONG"; entry_price, sl, tp = c['close'], p['low'], p['BBM']
            elif p['close'] > p['BBU'] and p['RSI'] > params['rsi_overbought']:
                side = "SHORT"; entry_price, sl, tp = c['close'], p['high'], p['BBM']

        if side:
            outcome = None
            for j in range(i + 1, len(df)):
                if side == "LONG" and highs[j] >= tp: outcome = "WIN"; break
                if side == "LONG" and lows[j] <= sl: outcome = "LOSS"; break
                if side == "SHORT" and lows[j] <= tp: outcome = "WIN"; break
                if side == "SHORT" and highs[j] >= sl: outcome = "LOSS"; break
            if outcome: trades.append({"outcome": outcome, "profit": abs(tp - entry_price), "loss": abs(sl - entry_price)})
            
    if not trades: return {"profit_factor": 0, "total_trades": 0}
    wins = len([t for t in trades if t['outcome'] == 'WIN'])
    gross_win = sum(t['profit'] for t in trades if t['outcome'] == 'WIN')
    gross_loss = sum(t['loss'] for t in trades if t['outcome'] == 'LOSS')
    pf = (gross_win / gross_loss) if gross_loss > 0 else float('inf')
    return {"profit_factor": round(pf, 2), "total_trades": len(trades), "win_rate": round((wins/len(trades)*100),2) if trades else 0}

# ===============================================================
# WORKER V5 (MULTI-STRATEGIA)
# ===============================================================
def run_single_optimization(args):
    cluster, symbol = args
    filepath = os.path.join(DATA_DIR, f"{symbol}_{TIMEFRAME}.csv")
    
    try:
        if not os.path.exists(filepath): return (symbol, None)
        df = pd.read_csv(filepath)
        if df.empty: return (symbol, None)
        
        best_overall_result = {"profit_factor": 0}
        best_overall_info = None

        # Itera su ogni tipo di strategia (PULLBACK, MEANREV)
        for strategy_name, param_grid in PARAM_GRID.items():
            keys, values = zip(*param_grid.items())
            param_combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
            
            for params in param_combinations:
                df_temp = add_indicators(df.copy(), params)
                if df_temp.empty or not all(k in df_temp.columns for k in ['high', 'low', 'close']): continue
                
                res = backtest(df_temp, params, strategy_name)
                
                if res["profit_factor"] > best_overall_result["profit_factor"]:
                    best_overall_result = res
                    best_overall_info = {"symbol": symbol, "strategy": strategy_name, "best_params": params}
        
        if best_overall_info:
            best_overall_result.update(best_overall_info)
            return (symbol, best_overall_result)
        return (symbol, None)

    except Exception:
        return (symbol, None)

# ===============================================================
# MAIN EXECUTION
# ===============================================================
if __name__ == "__main__":
    if not os.path.exists(DATA_DIR):
        logging.error(f"Directory dati '{DATA_DIR}' non trovata.")
    else:
        all_assets = [(cluster, sym) for cluster, syms in ASSET_CLUSTERS.items() for sym in syms]
        logging.info(f"Avvio Total Explorer V5 su {len(all_assets)} asset con {CORES} core...")

        results = {}
        with Pool(CORES) as pool:
            for sym, res in tqdm(pool.imap_unordered(run_single_optimization, all_assets), total=len(all_assets)):
                if res: results[sym] = res

        df_results = pd.DataFrame.from_dict(results, orient='index')
        if not df_results.empty:
            df_results = df_results.dropna(subset=['profit_factor'])
            df_results = df_results[df_results['profit_factor'] > 1.0] # Siamo più esigenti: solo PF > 1.0
            df_results.sort_values(by='profit_factor', ascending=False, inplace=True)

        output_file = "optimization_results_v5.json"
        df_results.to_json(output_file, orient='index', indent=4)
        
        logging.info(f"🏁 Ottimizzazione completata! Risultati salvati in '{output_file}'")
        print("\n--- STRATEGIE PROFITTEVOLI TROVATE (PF > 1.0) ---")
        print(df_results)
