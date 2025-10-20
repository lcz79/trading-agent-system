import streamlit as st
import requests
import pandas as pd
import time
import os
from dotenv import load_dotenv

# --- CONFIGURAZIONE SICURA ---
load_dotenv() # Carica le variabili da .env
API_URL = "http://127.0.0.1:8000"
API_KEY = os.getenv("API_KEY") # Legge la chiave segreta
REFRESH_INTERVAL_SECONDS = 15

# Prepara l'header di autenticazione
AUTH_HEADER = {"x-api-key": API_KEY}

st.set_page_config(
    page_title="Mitragliere A.I. - Pannello di Controllo V2",
    page_icon="🛡️",
    layout="wide"
)

# --- FUNZIONI DI COMUNICAZIONE CON L'API (con autenticazione) ---
def fetch_proposals():
    try:
        response = requests.get(f"{API_URL}/proposals", headers=AUTH_HEADER)
        response.raise_for_status()
        data = response.json()
        return data.get("trades", []) # La nuova API restituisce 'trades' direttamente
    except requests.exceptions.RequestException as e:
        st.toast(f"⚠️ Errore di connessione: {e}", icon="🔥")
        return []

def execute_trade(symbol: str):
    try:
        encoded_symbol = symbol.replace('/', '%2F')
        response = requests.post(f"{API_URL}/execute/{encoded_symbol}", headers=AUTH_HEADER)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Errore durante l'invio dell'ordine: {e}")
        return None

# Il resto dello script rimane quasi identico...
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = time.time()

def refresh_page():
    st.session_state.last_refresh = time.time()
    st.rerun()

col1, col2 = st.columns([4, 1])
with col1:
    st.title("🛡️ Mitragliere A.I. - Pannello V2")
    st.caption("Comunicazione sicura con il backend LIVE.")
with col2:
    if st.button("🔄 Aggiorna Ora", use_container_width=True):
        refresh_page()

status_placeholder = st.empty()
proposals = fetch_proposals()

if not proposals:
    st.info("Nessuna proposta di trade al momento. Il sistema sta analizzando il mercato...")
else:
    st.subheader(f"Trovate {len(proposals)} proposte di trade:")
    df = pd.DataFrame(proposals)
    df_display = df[['symbol', 'side', 'logic', 'score', 'entry', 'sl', 'tp', 'qty_est']]
    def color_side(val):
        color = 'rgba(144, 238, 144, 0.4)' if val == 'LONG' else 'rgba(250, 128, 114, 0.4)'
        return f'background-color: {color}'
    st.dataframe(df_display.style.applymap(color_side, subset=['side']), use_container_width=True, hide_index=True)

    st.subheader("Azioni Rapide:")
    num_proposals = len(proposals)
    cols = st.columns(num_proposals if num_proposals > 0 else 1)
    for i, proposal in enumerate(proposals):
        symbol = proposal['symbol']
        with cols[i]:
            if st.button(f"Esegui {symbol}", key=symbol, use_container_width=True, type="primary"):
                with st.spinner(f"Invio ordine per {symbol}..."):
                    result = execute_trade(symbol)
                    if result:
                        status_placeholder.success(f"✅ Comando di esecuzione per {symbol} inviato con successo!")
                    else:
                        status_placeholder.error(f"❌ Fallimento invio comando per {symbol}.")
                time.sleep(2)
                refresh_page()

if time.time() - st.session_state.last_refresh > REFRESH_INTERVAL_SECONDS:
    refresh_page()

time_since_refresh = int(time.time() - st.session_state.last_refresh)
st.markdown("---")
st.markdown(f"<small>Ultimo aggiornamento: {time_since_refresh}s fa. Prossimo aggiornamento automatico tra {max(0, REFRESH_INTERVAL_SECONDS - time_since_refresh)}s.</small>", unsafe_allow_html=True)
