import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
from datetime import datetime
from bybit_client import BybitClient

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="NEON TRADER", page_icon="⚡")

# --- CSS NEON/DARK ---
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #e0e0e0; }
    div[data-testid="stMetric"] {
        background-color: #1a1c24; border: 1px solid #333;
        padding: 10px; border-radius: 8px;
        box-shadow: 0 0 10px rgba(0, 255, 65, 0.1);
    }
    h1, h2, h3 { color: #00ff41 !important; }
    /* Nasconde menu hamburger e footer per pulizia */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# --- HEADER ---
c1, c2 = st.columns([4,1])
c1.title("⚡ SYSTEM MONITOR")
c2.caption(f"⏱️ Auto-Refresh attivo: {datetime.now().strftime('%H:%M:%S')}")

# --- CARICAMENTO DATI ---
try:
    client = BybitClient()
    wallet = client.get_wallet_balance()
except Exception as e:
    st.error(f"⚠️ OFFLINE: {e}")
    st.stop()

# --- KPI ---
if wallet:
    col1, col2, col3, col4 = st.columns(4)
    pnl = wallet.get('unrealized_pnl', 0)
    
    col1.metric("TOTAL EQUITY", f"${wallet.get('equity', 0):.2f}")
    col2.metric("WALLET BALANCE", f"${wallet.get('wallet_balance', 0):.2f}")
    col3.metric("AVAILABLE", f"${wallet.get('available', 0):.2f}")
    col4.metric("PNL APERTO", f"${pnl:.2f}", delta_color="normal" if pnl >= 0 else "inverse")
    st.markdown("---")

# --- TABELLE E GRAFICO ---
tab1, tab2 = st.tabs(["🚀 POSIZIONI", "📊 PERFORMANCE & GRAFICO"])

with tab1:
    pos = client.get_open_positions()
    if pos:
        df = pd.DataFrame(pos)
        st.dataframe(
            df, use_container_width=True, hide_index=True,
            column_config={
                "Unrealized PnL": st.column_config.NumberColumn(format="$%.2f"),
                "PnL %": st.column_config.NumberColumn(format="%.2f%%"),
            }
        )
    else:
        st.info("🟢 NESSUNA POSIZIONE ATTIVA")

with tab2:
    hist = client.get_closed_pnl(limit=50)
    if hist:
        df_hist = pd.DataFrame(hist)
        
        # --- GRAFICO PLOTLY ---
        try:
            # Ordiniamo per data crescente per il grafico
            df_chart = df_hist.iloc[::-1].copy()
            df_chart['CumPnL'] = df_chart['Closed PnL'].cumsum()
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                y=df_chart['CumPnL'],
                mode='lines+markers',
                name='Profitto',
                line=dict(color='#00ff41', width=3),
                marker=dict(color='#ffffff', size=5)
            ))
            
            fig.update_layout(
                title="Curva dei Profitti (Realized PnL)",
                template="plotly_dark", # FORZA TEMA SCURO
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=350,
                margin=dict(l=20, r=20, t=40, b=20)
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.warning(f"Impossibile disegnare grafico: {e}")

        # Tabella Storico
        if 'ts' in df_hist.columns: df_hist = df_hist.drop(columns=['ts'])
        st.dataframe(df_hist, use_container_width=True, hide_index=True)
    else:
        st.text("Nessuno storico disponibile.")

# --- AUTO REFRESH LOOP ---
# Questo è il trucco: aspetta 5 secondi e ricarica la pagina
time.sleep(5)
st.rerun()
