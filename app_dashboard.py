import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURAZIONE ---
# Inserisci qui l'URL del tuo servizio API (quello appena creato)
# Lo trovi nella dashboard di Render del servizio 'mitragliere-ai'
API_BASE_URL = "https://mitragliere-ai.onrender.com" # <--- CAMBIA QUESTO!

st.set_page_config(
    page_title="Mitragliere A.I. - Dashboard",
    page_icon="🔫",
    layout="wide"
)

st.title("🔫 Mitragliere A.I. Dashboard")

# Placeholder per i dati
data_placeholder = st.empty()

def fetch_data():
    """Recupera le proposte di trade dall'API del backend."""
    try:
        # L'endpoint che hai definito nel tuo piano
        response = requests.get(f"{API_BASE_URL}/proposals")
        response.raise_for_status() # Lancia un errore se la richiesta fallisce
        
        # Il tuo piano restituisce i dati sotto la chiave "proposals"
        data = response.json()
        proposals = data.get("proposals", {}).get("data", {}).get("trades", [])
        
        if proposals:
            df = pd.DataFrame(proposals)
            # Seleziona e ordina le colonne per una migliore visualizzazione
            cols = ['asset', 'side', 'entry', 'sl', 'tp', 'strategy', 'timestamp']
            df = df[[c for c in cols if c in df.columns]]
            return df
        else:
            return pd.DataFrame()
            
    except requests.exceptions.RequestException as e:
        st.error(f"Errore di connessione all'API: {e}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Errore nell'elaborazione dei dati: {e}")
        return pd.DataFrame()

while True:
    df = fetch_data()
    
    with data_placeholder.container():
        st.subheader("Proposte di Trade Attuali")
        
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Nessuna proposta di trade dal Cloud. Il sistema sta analizzando il mercato...")

    time.sleep(30) # Aggiorna ogni 30 secondi
