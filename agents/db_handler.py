import psycopg2
import pandas as pd
import logging
import os
from datetime import datetime

class DBHandler:
    def __init__(self):
        self.conn = None
        try:
            # Legge l'URL del database dalle variabili d'ambiente di Render
            db_url = os.environ.get("DATABASE_URL")
            if not db_url:
                raise ValueError("Variabile d'ambiente DATABASE_URL non trovata!")
            
            self.conn = psycopg2.connect(db_url)
            logging.info("✅ Connessione al database PostgreSQL stabilita con successo.")
            self.create_table()
        except Exception as e:
            logging.error(f"❌ Errore di connessione a PostgreSQL: {e}")
            self.conn = None

    def create_table(self):
        if not self.conn: return
        try:
            with self.conn.cursor() as cursor:
                # La sintassi è leggermente diversa per PostgreSQL
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS signals (
                        id SERIAL PRIMARY KEY,
                        asset TEXT NOT NULL,
                        timeframe TEXT,
                        side TEXT NOT NULL,
                        entry REAL NOT NULL,
                        sl REAL NOT NULL,
                        tp REAL NOT NULL,
                        strategy TEXT,
                        params TEXT,
                        timestamp TIMESTAMPTZ NOT NULL
                    );
                """)
            self.conn.commit()
        except Exception as e:
            logging.error(f"Errore durante la creazione della tabella 'signals': {e}")

    def save_signal(self, signal: dict):
        if not self.conn: return
        try:
            with self.conn.cursor() as cursor:
                # La sintassi per i parametri è %s invece di ?
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
            logging.error(f"Errore durante il salvataggio del segnale su PostgreSQL: {e}")

    def get_last_signal_time(self, asset: str, strategy: str) -> datetime | None:
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
        if not self.conn: return pd.DataFrame()
        try:
            query = "SELECT * FROM signals ORDER BY timestamp DESC"
            df = pd.read_sql_query(query, self.conn)
            return df
        except Exception as e:
            logging.error(f"Errore nel recuperare tutti i segnali da PostgreSQL: {e}")
            return pd.DataFrame()
