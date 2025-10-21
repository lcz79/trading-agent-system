import psycopg2
import pandas as pd
import logging
import os
from datetime import datetime

class DBHandler:
    def __init__(self):
        self.db_url = os.environ.get("DATABASE_URL")
        if not self.db_url:
            raise ValueError("Variabile d'ambiente DATABASE_URL non trovata!")
        self.conn = None
        self._connect() # Tenta la connessione iniziale

    def _connect(self):
        """Stabilisce una nuova connessione al database."""
        try:
            self.conn = psycopg2.connect(self.db_url)
            logging.info("✅ Nuova connessione al database PostgreSQL stabilita.")
            # È buona norma creare la tabella qui se la connessione viene ristabilita
            self.create_table()
        except Exception as e:
            logging.error(f"❌ Fallimento tentativo di connessione a PostgreSQL: {e}")
            self.conn = None

    def _ensure_connection(self):
        """Assicura che la connessione sia attiva, altrimenti si ricollega."""
        try:
            # self.conn.closed è 0 se attiva, non-zero se chiusa.
            if self.conn is None or self.conn.closed != 0:
                logging.warning("🔌 Connessione al DB persa. Tento la riconnessione...")
                self._connect()
        except Exception as e:
            logging.error(f"Errore controllo connessione: {e}. Tento la riconnessione...")
            self._connect()

    def create_table(self):
        self._ensure_connection()
        if not self.conn: return
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS signals (
                        id SERIAL PRIMARY KEY, asset TEXT NOT NULL, timeframe TEXT,
                        side TEXT NOT NULL, entry REAL NOT NULL, sl REAL NOT NULL, tp REAL NOT NULL,
                        strategy TEXT, params TEXT, timestamp TIMESTAMPTZ NOT NULL
                    );
                """)
            self.conn.commit()
        except Exception as e:
            logging.error(f"Errore durante la creazione della tabella 'signals': {e}")

    def save_signal(self, signal: dict):
        self._ensure_connection()
        if not self.conn: return
        try:
            with self.conn.cursor() as cursor:
                query = """
                    INSERT INTO signals (asset, timeframe, side, entry, sl, tp, strategy, params, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(query, (
                    signal.get('asset'), signal.get('timeframe'), signal.get('side'),
                    signal.get('entry'), signal.get('sl'), signal.get('tp'),
                    signal.get('strategy'), signal.get('params'), datetime.utcnow()
                ))
            self.conn.commit()
            logging.info(f"Segnale per {signal.get('asset')} salvato su PostgreSQL.")
        except Exception as e:
            logging.error(f"Errore salvataggio segnale su PostgreSQL: {e}")

    def get_last_signal_time(self, asset: str, strategy: str) -> datetime | None:
        self._ensure_connection()
        if not self.conn: return None
        try:
            with self.conn.cursor() as cursor:
                query = "SELECT MAX(timestamp) FROM signals WHERE asset = %s AND strategy = %s"
                cursor.execute(query, (asset, strategy))
                result = cursor.fetchone()[0]
                return result if result else None
        except Exception:
            return None

    def get_all_signals_as_df(self) -> pd.DataFrame:
        self._ensure_connection()
        if not self.conn: return pd.DataFrame()
        try:
            query = "SELECT * FROM signals ORDER BY timestamp DESC"
            # Ignoriamo il warning di pandas, è solo un avviso
            df = pd.read_sql_query(query, self.conn)
            return df
        except Exception as e:
            logging.error(f"Errore recupero segnali da PostgreSQL: {e}")
            return pd.DataFrame()

    def get_signal_by_id(self, trade_id: int) -> dict | None:
        self._ensure_connection()
        if not self.conn: return None
        try:
            query = "SELECT * FROM signals WHERE id = %s"
            df = pd.read_sql_query(query, self.conn, params=(trade_id,))
            if not df.empty:
                return df.iloc[0].to_dict()
            return None
        except Exception as e:
            logging.error(f"Errore nel recuperare il trade ID {trade_id}: {e}")
            return None
