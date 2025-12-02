import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
import time

st.set_page_config(page_title="NEON TRADER AI", layout="wide", page_icon="💎")

# URL AGGIORNATI CON I NOMI DEI NUOVI CONTAINER
URLS = {
    "manager": "http://07_position_manager:8000",
    "sentiment": "http://06_news_sentiment_agent:8000"
}

# --- STILE NEON ---
st.markdown("""
    <style>
    .stApp {
        background-color: #050505;
        background-image: radial-gradient(circle at center, #111111 0%, #000000 100%);
        color: white;
    }
    div[data-testid="stMetric"] {
        background-color: #0f0f0f;
        border: 1px solid #333;
        box-shadow: 0 0 15px rgba(0, 255, 157, 0.15);
        padding: 15px;
        border-radius: 8px;
    }
    label[data-testid="stMetricLabel"] { color: #00ff9d !important; font-family: monospace; }
    div[data-testid="stMetricValue"] { color: #ffffff !important; text-shadow: 0 0 10px rgba(255, 255, 255, 0.5); }
    h1, h2, h3 { color: #e0e0e0 !important; text-transform: uppercase; letter-spacing: 2px; }
    div[data-testid="stDataFrame"] { background-color: #111; border: 1px solid #333; }
    </style>
    """, unsafe_allow_html=True)

def fetch(url, endpoint, default=None):
    try:
        r = requests.get(f"{url}{endpoint}", timeout=3)
        if r.status_code == 200: return r.json()
    except: pass
    return default

def get_coingecko_news():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/news", timeout=3)
        if r.status_code == 200: return r.json().get('data', [])[:3]
    except: pass
    return []

# Fetch Data
wallet = fetch(URLS['manager'], "/get_wallet_balance", {})
positions = fetch(URLS['manager'], "/get_open_positions", [])
equity_hist = fetch(URLS['manager'], "/equity_history", [])
logs = fetch(URLS['manager'], "/management_logs", [])

balance = wallet.get("balance", 0.0)
pos_list = positions if isinstance(positions, list) else []
active_pnl = sum(p.get('pnl', 0) for p in pos_list)
equity = balance + active_pnl

st.title("💎 NEON TRADER AI")

# KPI Section
c1, c2, c3 = st.columns(3)
c1.metric("WALLET BALANCE", f"${balance:,.2f}")
c2.metric("LIVE EQUITY", f"${equity:,.2f}", delta=f"{active_pnl:+.2f}")
c3.metric("OPEN POSITIONS", len(pos_list))

st.markdown("---")

# Chart Section
if equity_hist and isinstance(equity_hist, list) and len(equity_hist) > 0:
    df_eq = pd.DataFrame(equity_hist)
    if 'equity' in df_eq.columns:
        fig = go.Figure()
        # Linea Equity (Verde Neon)
        fig.add_trace(go.Scatter(
            y=df_eq['equity'], 
            mode='lines', 
            name='Live Equity', 
            line=dict(color='#00ff9d', width=3),
            fill='tozeroy',
            fillcolor='rgba(0, 255, 157, 0.05)'
        ))
        # Linea Balance (Blu, fissa)
        fig.add_trace(go.Scatter(
            x=[0, len(df_eq)-1], 
            y=[balance, balance], 
            mode='lines', 
            name='Realized Balance', 
            line=dict(color='#00d4ff', width=2, dash='dash')
        ))
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', 
            plot_bgcolor='rgba(10,10,10,0.5)', 
            font=dict(color='#a0a0a0'), 
            height=400,
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis=dict(showgrid=False),
            yaxis=dict(gridcolor='#222')
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Waiting for market data stream...")

# Lists Section
col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("⚡ ACTIVE POSITIONS")
    if pos_list:
        df = pd.DataFrame(pos_list)
        cols = ['symbol', 'side', 'size', 'entry_price', 'pnl']
        valid_cols = [c for c in cols if c in df.columns]
        st.dataframe(df[valid_cols], use_container_width=True)
    else:
        st.info("Scanning for entry points...")

with col_right:
    st.subheader("📰 MARKET INTEL")
    news = get_coingecko_news()
    if news:
        for n in news:
            st.markdown(f"**[{n.get('title')}]({n.get('url')})**")
            st.caption(f"{n.get('author', 'Source')}")
            st.markdown("---")
    else:
        st.caption("Connecting to news feed...")

    st.subheader("📜 SYSTEM LOGS")
    if logs:
        for l in logs[:10]:
            color = "#00ff9d" if l.get('status') == 'success' else "#ff0055" if l.get('status') == 'error' else "#ccc"
            st.markdown(f"<span style='color:{color}'>{l.get('time', '')} | {l.get('action', '')}</span>", unsafe_allow_html=True)

time.sleep(5)
st.rerun()
