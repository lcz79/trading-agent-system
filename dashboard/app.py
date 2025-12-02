import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import time

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="AI HEDGE FUND", layout="wide", page_icon="🌌")

# --- STILE CYBERPUNK / NEON ---
st.markdown("""
<style>
    .stApp {
        background-color: #000000;
        background-image: radial-gradient(circle at center, #111 0%, #000 100%);
        color: #e0e0e0;
    }
    div[data-testid="metric-container"] {
        background-color: #0a0a0a;
        border: 1px solid #333;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 0 15px rgba(0, 255, 65, 0.1);
    }
    h1, h2, h3 { color: #00ff41 !important; font-family: 'Courier New', sans-serif; text-shadow: 0 0 5px #00ff41; }
    .news-item {
        background: #0f0f0f; border-left: 3px solid #00ff41; 
        padding: 12px; margin-bottom: 10px; border-radius: 0 6px 6px 0;
        transition: transform 0.2s;
    }
    .stDataFrame { border: 1px solid #222; }
</style>
""", unsafe_allow_html=True)

URL_POS = "http://07_position_manager:8000"

# --- FUNZIONI API ---
def get_api(ep):
    try:
        r = requests.get(f"{URL_POS}/{ep}", timeout=3)
        return r.json() if r.status_code == 200 else None
    except: return None

def get_news():
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN", timeout=5)
        return r.json().get('Data', [])[:5]
    except: return []

# --- HEADER ---
c1, c2 = st.columns([3,1])
c1.title("🌌 HEDGE FUND COMMANDER")
if c2.button("🔄 REFRESH SYSTEM"): st.rerun()

# --- METRICHE ---
wallet = get_api("get_wallet_balance")
if wallet:
    eq = float(wallet.get('equity', 0))
    av = float(wallet.get('available', 0))
    inv = eq - av
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("💰 TOTAL EQUITY", f"${eq:,.2f}")
    m2.metric("💳 DISPONIBILE", f"${av:,.2f}")
    m3.metric("🔒 INVESTITO", f"${inv:,.2f}")
    m4.metric("🧠 AI STATUS", "ACTIVE")
else:
    st.error("⚠️ POSITION MANAGER OFFLINE")
    st.stop()

st.markdown("---")

# --- GRAFICO ---
st.subheader("📈 PERFORMANCE")
hist = get_api("get_history")
if hist and len(hist) > 1:
    df_hist = pd.DataFrame(hist)
    if 'timestamp' in df_hist.columns and 'live_equity' in df_hist.columns:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_hist['timestamp'], y=df_hist['live_equity'], 
                               line=dict(color='#00ff41', width=2), fill='tozeroy'))
        fig.update_layout(template="plotly_dark", height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("⏳ Attesa dati storici...")

# --- POSIZIONI & NEWS ---
col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("⚡ POSIZIONI ATTIVE")
    pos_data = get_api("get_open_positions")
    
    if pos_data and pos_data.get('details'):
        df = pd.DataFrame(pos_data['details'])
        
        # --- IL FIX SALVAVITA ---
        # Se mancano le colonne, le creiamo noi con valori sicuri (0)
        required_cols = ['symbol', 'side', 'size', 'entry_price', 'mark_price', 'pnl', 'pnl_pct']
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0.0 # Placeholder per evitare il crash
        
        # Ora che le colonne esistono, possiamo filtrarle e mostrarle
        cols_to_show = ['symbol', 'side', 'size', 'entry_price', 'pnl', 'pnl_pct']
        
        def color_pnl(val):
            try:
                v = float(str(val).replace('$','').replace('%',''))
                return f'color: {"#00ff41" if v >= 0 else "#ff004c"}; font-weight: bold'
            except: return ''

        st.dataframe(
            df[cols_to_show].style.applymap(color_pnl, subset=['pnl', 'pnl_pct'])
            .format({'entry_price': '{:.4f}', 'pnl': '{:+.2f} $', 'pnl_pct': '{:+.2f} %'}),
            use_container_width=True
        )
    else:
        st.info("💤 Nessuna posizione aperta.")

    # CHIUSURE
    st.subheader("📜 STORICO CHIUSURE")
    closed = get_api("get_closed_positions")
    if closed:
        df_c = pd.DataFrame(closed)
        if not df_c.empty and 'closedPnl' in df_c.columns:
             st.dataframe(
                df_c[['datetime', 'symbol', 'side', 'price', 'closedPnl']]
                .style.format({'closedPnl': '{:+.2f} $'}),
                use_container_width=True
             )

with col_right:
    st.subheader("📰 NEWSFEED")
    news = get_news()
    if news:
        for n in news:
            st.markdown(f"<div class='news-item'><a href='{n['url']}' target='_blank' style='color:white;text-decoration:none'>{n['title']}</a></div>", unsafe_allow_html=True)
    else:
        st.caption("News non disponibili.")

time.sleep(5)
st.rerun()
