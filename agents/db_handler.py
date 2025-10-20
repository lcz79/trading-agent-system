import sqlite3
from datetime import datetime
import logging

class DBHandler:
    def __init__(self, db_name="trading_signals.db"):
        self.db_name = db_name
        self.conn = None
        try:
            self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
            self.create_tables()
            logging.info("✅ Connessione al database stabilita.")
        except sqlite3.Error as e:
            logging.error(f"Errore di connessione al database: {e}")

    def create_tables(self):
        """Crea le tabelle se non esistono già."""
        try:
            cursor = self.conn.cursor()
            # --- MODIFICA CHIAVE: Aggiunta colonna 'strategy' ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT NOT NULL,
                    strategy TEXT NOT NULL, 
                    side TEXT NOT NULL,
                    entry REAL,
                    sl REAL,
                    tp REAL,
                    params TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Errore nella creazione delle tabelle: {e}")

    def save_signal(self, signal_data: dict):
        """Salva un nuovo segnale nel database."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO signals (asset, strategy, side, entry, sl, tp, params, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal_data.get('asset'),
                signal_data.get('strategy'), # Nuovo campo
                signal_data.get('side'),
                signal_data.get('entry'),
                signal_data.get('sl'),
                signal_data.get('tp'),
                signal_data.get('params'),
                datetime.utcnow()
            ))
            self.conn.commit()
            logging.info(f"Segnale per {signal_data.get('asset')} [{signal_data.get('strategy')}] salvato nel DB.")
        except sqlite3.Error as e:
            logging.error(f"Errore nel salvataggio del segnale: {e}")

    def get_last_signal_time(self, asset: str, strategy: str) -> datetime or None:
        """
        Recupera il timestamp dell'ultimo segnale per un dato asset E strategia.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT timestamp FROM signals 
                WHERE asset = ? AND strategy = ?
                ORDER BY timestamp DESC 
                LIMIT 1
            """, (asset, strategy))
            result = cursor.fetchone()
            if result:
                return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
            return None
        except sqlite3.Error as e:
            logging.error(f"Errore nel recupero dell'ultimo segnale: {e}")
            return None

    def __del__(self):
        if self.conn:
            self.conn.close()