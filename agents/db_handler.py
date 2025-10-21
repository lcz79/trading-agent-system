import sqlite3
import pandas as pd
import logging
from datetime import datetime

class DBHandler:
    def __init__(self, db_name="trading_signals.db"):
        self.db_name = db_name
        self.conn = None
        try:
            # check_same_thread=False è fondamentale per usarlo con FastAPI e i thread
            self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
            logging.info("✅ Connessione al database stabilita.")
            self.create_table()
        except Exception as e:
            logging.error(f"❌ Errore di connessione al database: {e}")

    def create_table(self):
        """Crea la tabella dei segnali se non esiste già."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT NOT NULL,
                    timeframe TEXT,
                    side TEXT NOT NULL,
                    entry REAL NOT NULL,
                    sl REAL NOT NULL,
                    tp REAL NOT NULL,
                    strategy TEXT,
                    params TEXT,
                    timestamp DATETIME NOT NULL
                );
            """)
            self.conn.commit()
        except Exception as e:
            logging.error(f"Errore durante la creazione della tabella 'signals': {e}")

    def save_signal(self, signal: dict):
        """Salva un nuovo segnale di trade nel database."""
        try:
            cursor = self.conn.cursor()
            query = """
                INSERT INTO signals (asset, timeframe, side, entry, sl, tp, strategy, params, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(query, (
                signal.get('asset'),
                signal.get('timeframe'),
                signal.get('side'),
                signal.get('entry'),
                signal.get('sl'),
                signal.get('tp'),
                signal.get('strategy'),
                signal.get('params'),
                datetime.utcnow()
            ))
            self.conn.commit()
            logging.info(f"Segnale per {signal.get('asset')} salvato nel database.")
        except Exception as e:
            logging.error(f"Errore durante il salvataggio del segnale: {e}")

    def get_last_signal_time(self, asset: str, strategy: str) -> datetime | None:
        """Recupera il timestamp dell'ultimo segnale per un dato asset e strategia."""
        try:
            cursor = self.conn.cursor()
            query = "SELECT MAX(timestamp) FROM signals WHERE asset = ? AND strategy = ?"
            result = cursor.execute(query, (asset, strategy)).fetchone()[0]
            if result:
                return datetime.fromisoformat(result)
            return None
        except Exception:
            return None

    # --- FUNZIONE MANCANTE AGGIUNTA QUI ---
    def get_all_signals_as_df(self) -> pd.DataFrame:
        """
        Recupera tutti i segnali dal database e li restituisce come DataFrame pandas.
        """
        try:
            if not self.conn:
                raise ConnectionError("Connessione al database non disponibile.")
                
            query = "SELECT * FROM signals ORDER BY timestamp DESC"
            df = pd.read_sql_query(query, self.conn)
            return df
        except Exception as e:
            logging.error(f"Errore nel recuperare tutti i segnali: {e}")
            return pd.DataFrame() # Restituisce un DataFrame vuoto in caso di errore
