import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURAZIONE ---
API_BASE_URL = "https://mitragliere-ai-2.onrender.com"

st.set_page_config(
    page_title="Mitragliere A.I. - Dashboard Esecutiva",
    page_icon="🔫",
    layout="wide"
)

st.title("🔫 Mitragliere A.I. - Dashboard Esecutiva")

# Placeholders per messaggi e dati
status_placeholder = st.empty()
data_placeholder = st.empty()

def fetch_data():
    """Recupera le proposte di trade dall'API."""
    try:
        response = requests.get(f"{API_BASE_URL}/proposals")
        response.raise_for_status()
        data = response.json().get("proposals", [])
        if data:
            df = pd.DataFrame(data)
            if 'id' not in df.columns:
                status_placeholder.error("Dati dei segnali incompleti: manca la colonna 'id'.")
                return pd.DataFrame()
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df.sort_values(by="timestamp", ascending=False)
        return pd.DataFrame()
    except Exception as e:
        status_placeholder.error(f"Errore di connessione all'API (GET /proposals): {e}")
        return pd.DataFrame()

def execute_trade_api(trade_id):
    """Chiama l'API per eseguire un trade specifico."""
    try:
        status_placeholder.warning(f"Invio comando di esecuzione per trade ID: {trade_id}...")
        response = requests.post(f"{API_BASE_URL}/execute/{trade_id}")
        response.raise_for_status()
        result = response.json()
        if result.get("status") == "success":
            status_placeholder.success(f"Trade ID {trade_id} eseguito! Dettagli: {result.get('message')}")
        else:
            status_placeholder.error(f"Errore dall'API durante l'esecuzione: {result.get('message')}")
        time.sleep(5)
        return True
    except Exception as e:
        status_placeholder.error(f"Fallimento critico chiamata API (POST /execute): {e}")
        time.sleep(5)
        return False

# --- LOGICA PRINCIPALE (SENZA 'while True') ---

df = fetch_data()

with data_placeholder.container():
    st.subheader("Proposte di Trade Pronte per l'Esecuzione")
    
    if not df.empty:
        df_display = df.copy()
        df_display['esegui'] = False 
        disabled_columns = [col for col in df.columns if col != 'esegui']
        
        # Usiamo una chiave dinamica basata sul timestamp per evitare conflitti
        # Ma la soluzione migliore è il rerun(), quindi la chiave statica va bene
        edited_df = st.data_editor(
            df_display,
            column_config={
                "esegui": st.column_config.CheckboxColumn("Esegui?"),
                "id": st.column_config.NumberColumn("ID Trade", format="%d")
            },
            disabled=disabled_columns,
            hide_index=True,
            width='stretch',
            key="trade_editor" # Questa chiave ora è sicura perché il rerun pulisce tutto
        )
        
        trade_to_execute = edited_df[edited_df["esegui"]]
        if not trade_to_execute.empty:
            trade_id = trade_to_execute.iloc[0]["id"]
            execute_trade_api(trade_id)
            # Forza un refresh completo della pagina per resettare lo stato
            st.rerun()
    else:
        status_placeholder.info("Nessuna proposta di trade dal Cloud. Il sistema sta analizzando il mercato...")

# --- MECCANISMO DI AUTO-AGGIORNAMENTO CORRETTO ---
# Attende 30 secondi e poi dice a Streamlit di rieseguire l'intero script da capo.
time.sleep(30)
st.rerun()
