import ccxt
import pandas as pd
import os
import time
import json
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s] %(message)s')

# --- CONFIGURAZIONE ---
CONFIG_FILE = "config/agents_config.json"
OUTPUT_DIR = "historical_data"
TIMEFRAME = '1h'
# ▼▼▼ MODIFICA CHIAVE ▼▼▼
DAYS_TO_DOWNLOAD = 365 * 4  # Scarichiamo 4 anni di dati
# ▲▲▲ MODIFICA CHIAVE ▲▲▲

def get_assets_from_config(config_path):
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return [asset.replace('/', '') for asset in config.get("assets", [])]
    except FileNotFoundError:
        logging.error(f"File di configurazione '{config_path}' non trovato.")
        return []

def download_data_for_asset(exchange, symbol, timeframe, days):
    logging.info(f"--- Inizio download di 4 ANNI per {symbol} ---")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        logging.info(f"Creata directory: {OUTPUT_DIR}")

    filepath = os.path.join(OUTPUT_DIR, f"{symbol}_{timeframe}.csv")
    
    # Utilizzo di datetime.now(datetime.UTC) per evitare il DeprecationWarning
    since_dt = datetime.now(__import__('datetime').timezone.utc) - timedelta(days=days)
    since = exchange.parse8601(since_dt.isoformat())
    
    all_ohlcv = []
    
    try:
        while True:
            logging.info(f"Recupero dati per {symbol} dal {exchange.iso8601(since)}...")
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
            
            if not ohlcv:
                logging.info(f"Nessun dato ulteriore per {symbol}. Download completato.")
                break
            
            if len(all_ohlcv) > 0 and ohlcv[0][0] <= all_ohlcv[-1][0]:
                logging.info("Dati duplicati ricevuti. Interruzione.")
                break

            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + (60 * 60 * 1000)
            
            time.sleep(exchange.rateLimit / 1000)

        if not all_ohlcv:
            logging.warning(f"Nessun dato scaricato per {symbol}.")
            return

        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.to_csv(filepath, index=False)
        logging.info(f"✅ Dati per {symbol} salvati in '{filepath}' ({len(df)} righe).")

    except Exception as e:
        logging.error(f"Errore durante il download per {symbol}: {e}")

if __name__ == "__main__":
    logging.info("Avvio del Collezionista di Dati Storici (4 ANNI)...")
    exchange = ccxt.bybit({'options': {'defaultType': 'swap'}})
    assets_to_download = get_assets_from_config(CONFIG_FILE)
    
    if not assets_to_download:
        logging.error("Nessun asset da scaricare.")
    else:
        logging.info(f"Trovati {len(assets_to_download)} asset da scaricare.")
        for asset in assets_to_download:
            download_data_for_asset(exchange, asset, TIMEFRAME, DAYS_TO_DOWNLOAD)
            
    logging.info("--- Processo di download di 4 anni completato. ---")
