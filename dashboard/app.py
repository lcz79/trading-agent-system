"""
🎯 MITRAGLIERE - Trading Bot AI System
Dashboard con Design NEON/Cyberpunk
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import time
from datetime import datetime, timezone
from bybit_client import BybitClient
from components.fees_tracker import render_fees_section, get_trading_fees
from components.api_costs import render_api_costs_section, calculate_api_costs
from components.ai_reasoning import render_ai_reasoning
import numpy as np

# --- COSTANTI ---
DEFAULT_INITIAL_CAPITAL = 1000  # Capital iniziale di default per calcoli ROI
TRADING_DAYS_PER_YEAR = 252     # Giorni di trading annuali per Sharpe Ratio

# --- CONFIGURAZIONE ---
st.set_page_config(
    layout="wide", 
    page_title="MITRAGLIERE - Trading Bot", 
    page_icon="🎯",
    initial_sidebar_state="expanded"
)

# --- CSS NEON/CYBERPUNK ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;700;900&family=Rajdhani:wght@300;400;600;700&display=swap');
    
    /* Base - Dark Cyberpunk */
    .stApp {
        background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 100%);
        font-family: 'Rajdhani', -apple-system, sans-serif;
        color: #e0e0e0;
    }
    
    /* Animazioni Neon */
    @keyframes neon-glow {
        0%, 100% { 
            text-shadow: 0 0 10px #00ff9d, 0 0 20px #00ff9d, 0 0 30px #00ff9d, 0 0 40px #00ff9d;
            filter: brightness(1);
        }
        50% { 
            text-shadow: 0 0 20px #00ff9d, 0 0 40px #00ff9d, 0 0 60px #00ff9d, 0 0 80px #00ff9d;
            filter: brightness(1.2);
        }
    }
    
    @keyframes pulse {
        0%, 100% { transform: scale(1); opacity: 1; }
        50% { transform: scale(1.03); opacity: 0.95; }
    }
    
    @keyframes border-glow {
        0%, 100% { 
            box-shadow: 0 0 10px #00f3ff, inset 0 0 10px rgba(0,243,255,0.1);
        }
        50% { 
            box-shadow: 0 0 25px #00f3ff, 0 0 40px #00f3ff, inset 0 0 15px rgba(0,243,255,0.2);
        }
    }
    
    @keyframes glow-rotate {
        0% { filter: hue-rotate(0deg) brightness(1); }
        50% { filter: hue-rotate(20deg) brightness(1.2); }
        100% { filter: hue-rotate(0deg) brightness(1); }
    }
    
    /* Header MITRAGLIERE */
    .mitragliere-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 2px solid #00f3ff;
        border-radius: 15px;
        padding: 25px;
        margin-bottom: 30px;
        animation: border-glow 3s ease-in-out infinite;
        position: relative;
        overflow: hidden;
    }
    
    .mitragliere-header::before {
        content: '';
        position: absolute;
        top: -50%;
        left: -50%;
        width: 200%;
        height: 200%;
        background: radial-gradient(circle, rgba(0,243,255,0.1) 0%, transparent 70%);
        animation: glow-rotate 8s linear infinite;
    }
    
    .mitragliere-title {
        font-family: 'Orbitron', monospace;
        font-size: 48px;
        font-weight: 900;
        color: #00ff9d;
        text-align: center;
        letter-spacing: 8px;
        margin: 0;
        animation: neon-glow 2s ease-in-out infinite;
        position: relative;
        z-index: 1;
    }
    
    .mitragliere-subtitle {
        font-family: 'Rajdhani', sans-serif;
        font-size: 18px;
        color: #00f3ff;
        text-align: center;
        letter-spacing: 4px;
        margin-top: 5px;
        text-transform: uppercase;
        opacity: 0.9;
        position: relative;
        z-index: 1;
    }
    
    .status-badge {
        display: inline-block;
        padding: 8px 20px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 14px;
        letter-spacing: 2px;
        animation: pulse 2s ease-in-out infinite;
        position: relative;
        z-index: 1;
    }
    
    .status-online {
        background: linear-gradient(135deg, #00ff9d 0%, #00d97e 100%);
        color: #0a0a0f;
        box-shadow: 0 0 20px #00ff9d;
    }
    
    .status-offline {
        background: linear-gradient(135deg, #ff2a6d 0%, #e01e5a 100%);
        color: #ffffff;
        box-shadow: 0 0 20px #ff2a6d;
    }
    
    /* Cards Neon */
    .neon-card {
        background: linear-gradient(135deg, rgba(26,26,46,0.9) 0%, rgba(22,33,62,0.9) 100%);
        border: 2px solid #bf00ff;
        border-radius: 15px;
        padding: 20px;
        margin-bottom: 20px;
        animation: border-glow 4s ease-in-out infinite;
        backdrop-filter: blur(10px);
        transition: all 0.3s ease;
    }
    
    .neon-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 10px 40px rgba(191,0,255,0.4);
        border-color: #00f3ff;
    }
    
    /* Metriche con Pulse */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(26,26,46,0.95) 0%, rgba(22,33,62,0.95) 100%);
        border: 2px solid #00f3ff;
        padding: 20px;
        border-radius: 12px;
        animation: pulse 3s ease-in-out infinite;
        box-shadow: 0 0 15px rgba(0,243,255,0.3);
        transition: all 0.3s ease;
    }
    
    div[data-testid="stMetric"]:hover {
        transform: scale(1.05);
        box-shadow: 0 0 30px rgba(0,243,255,0.6);
    }
    
    div[data-testid="stMetric"] label {
        color: #00f3ff !important;
        font-size: 14px !important;
        font-weight: 700 !important;
        text-transform: uppercase;
        letter-spacing: 2px;
        font-family: 'Orbitron', monospace !important;
    }
    
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #00ff9d !important;
        font-size: 32px !important;
        font-weight: 900 !important;
        font-family: 'Orbitron', monospace !important;
        text-shadow: 0 0 10px #00ff9d;
    }
    
    div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
        font-weight: 700 !important;
        font-size: 16px !important;
    }
    
    /* Section Headers */
    .section-title {
        font-family: 'Orbitron', monospace;
        font-size: 24px;
        font-weight: 700;
        color: #00f3ff;
        margin: 20px 0 15px 0;
        padding: 12px 20px;
        background: linear-gradient(90deg, rgba(0,243,255,0.2) 0%, transparent 100%);
        border-left: 4px solid #00f3ff;
        border-radius: 5px;
        letter-spacing: 2px;
        text-transform: uppercase;
        text-shadow: 0 0 10px #00f3ff;
    }
    
    /* Tabs Neon Style */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        background: transparent;
    }
    
    .stTabs [data-baseweb="tab"] {
        background: linear-gradient(135deg, rgba(26,26,46,0.8) 0%, rgba(22,33,62,0.8) 100%);
        border: 2px solid #bf00ff;
        border-radius: 10px;
        padding: 12px 24px;
        color: #bf00ff;
        font-weight: 700;
        font-family: 'Rajdhani', sans-serif;
        letter-spacing: 1px;
        transition: all 0.3s ease;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background: linear-gradient(135deg, rgba(191,0,255,0.3) 0%, rgba(0,243,255,0.3) 100%);
        box-shadow: 0 0 20px rgba(191,0,255,0.5);
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #bf00ff 0%, #00f3ff 100%) !important;
        color: #ffffff !important;
        box-shadow: 0 0 25px rgba(191,0,255,0.8);
        text-shadow: 0 0 10px #ffffff;
    }
    
    /* Tables */
    .dataframe {
        background: rgba(26,26,46,0.6) !important;
        border: 1px solid #00f3ff !important;
        color: #e0e0e0 !important;
    }
    
    .dataframe th {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%) !important;
        color: #00f3ff !important;
        font-weight: 700 !important;
        border-bottom: 2px solid #00f3ff !important;
    }
    
    .dataframe td {
        border-bottom: 1px solid rgba(0,243,255,0.2) !important;
    }
    
    /* Profit/Loss Colors */
    .profit { 
        color: #00ff9d !important; 
        text-shadow: 0 0 5px #00ff9d;
        font-weight: 700;
    }
    .loss { 
        color: #ff2a6d !important; 
        text-shadow: 0 0 5px #ff2a6d;
        font-weight: 700;
    }
    
    /* Info Boxes Neon */
    .info-box {
        background: linear-gradient(135deg, rgba(0,243,255,0.1) 0%, rgba(0,243,255,0.05) 100%);
        border: 2px solid #00f3ff;
        border-left: 6px solid #00f3ff;
        padding: 15px;
        border-radius: 10px;
        margin: 16px 0;
        color: #00f3ff;
        font-weight: 600;
        box-shadow: 0 0 15px rgba(0,243,255,0.2);
    }
    
    .success-box {
        background: linear-gradient(135deg, rgba(0,255,157,0.1) 0%, rgba(0,255,157,0.05) 100%);
        border: 2px solid #00ff9d;
        border-left: 6px solid #00ff9d;
        padding: 15px;
        border-radius: 10px;
        margin: 16px 0;
        color: #00ff9d;
        font-weight: 600;
        box-shadow: 0 0 15px rgba(0,255,157,0.2);
    }
    
    .warning-box {
        background: linear-gradient(135deg, rgba(255,42,109,0.1) 0%, rgba(255,42,109,0.05) 100%);
        border: 2px solid #ff2a6d;
        border-left: 6px solid #ff2a6d;
        padding: 15px;
        border-radius: 10px;
        margin: 16px 0;
        color: #ff2a6d;
        font-weight: 600;
        box-shadow: 0 0 15px rgba(255,42,109,0.2);
    }
    
    /* Expander Neon */
    .streamlit-expanderHeader {
        background: linear-gradient(135deg, rgba(26,26,46,0.9) 0%, rgba(22,33,62,0.9) 100%) !important;
        border: 2px solid #bf00ff !important;
        border-radius: 10px !important;
        color: #bf00ff !important;
        font-weight: 700 !important;
    }
    
    /* Hide Streamlit Elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}
    header {visibility: hidden;}
    
    /* Scrollbar Neon */
    ::-webkit-scrollbar {
        width: 12px;
        height: 12px;
    }
    
    ::-webkit-scrollbar-track {
        background: #1a1a2e;
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #bf00ff 0%, #00f3ff 100%);
        border-radius: 10px;
        box-shadow: 0 0 10px rgba(191,0,255,0.5);
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(135deg, #00f3ff 0%, #bf00ff 100%);
        box-shadow: 0 0 20px rgba(0,243,255,0.8);
    }
    
    /* AI Decision Cards */
    .ai-decision-card {
        background: linear-gradient(135deg, rgba(26,26,46,0.95) 0%, rgba(22,33,62,0.95) 100%);
        border: 2px solid #bf00ff;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 15px;
        backdrop-filter: blur(10px);
        transition: all 0.3s ease;
        box-shadow: 0 0 15px rgba(191,0,255,0.3);
    }
    
    .ai-decision-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 5px 25px rgba(191,0,255,0.5);
        border-color: #00f3ff;
    }
    
    .decision-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
        padding-bottom: 10px;
        border-bottom: 1px solid rgba(0,243,255,0.3);
    }
    
    .decision-time {
        color: #00f3ff;
        font-family: 'Rajdhani', sans-serif;
        font-size: 14px;
        font-weight: 600;
        opacity: 0.8;
    }
    
    .decision-action {
        font-family: 'Orbitron', monospace;
        font-size: 16px;
        font-weight: 700;
        letter-spacing: 1px;
    }
    
    .decision-symbol {
        font-family: 'Orbitron', monospace;
        font-size: 16px;
        font-weight: 700;
    }
    
    .decision-reasoning {
        color: #e0e0e0;
        font-family: 'Rajdhani', sans-serif;
        font-size: 15px;
        line-height: 1.6;
    }
    
    .decision-reasoning p {
        margin: 8px 0;
    }
    
    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-family: 'Orbitron', monospace;
        font-size: 24px;
        font-weight: 700;
        color: #00f3ff;
        margin: 20px 0 15px 0;
        padding: 12px 20px;
        background: linear-gradient(90deg, rgba(0,243,255,0.2) 0%, transparent 100%);
        border-left: 4px solid #00f3ff;
        border-radius: 5px;
        text-shadow: 0 0 10px #00f3ff;
    }
    
    .ai-status {
        color: #00ff9d;
        font-size: 14px;
        animation: pulse 2s ease-in-out infinite;
    }
    
    .empty-state {
        text-align: center;
        padding: 40px;
        color: #808080;
        font-family: 'Rajdhani', sans-serif;
    }
    
    .empty-icon {
        font-size: 48px;
        display: block;
        margin-bottom: 16px;
    }
</style>
""", unsafe_allow_html=True)

# --- HEADER MITRAGLIERE ---
st.markdown('<div class="mitragliere-header">', unsafe_allow_html=True)
st.markdown('<h1 class="mitragliere-title">🎯 M I T R A G L I E R E</h1>', unsafe_allow_html=True)
st.markdown('<p class="mitragliere-subtitle">Trading Bot AI System</p>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    current_time = datetime.now().strftime("%H:%M:%S")
    st.markdown(f'<div style="text-align: center; margin-top: 10px;">', unsafe_allow_html=True)
    
    # Carica stato sistema
    try:
        client = BybitClient()
        wallet = client.get_wallet_balance()
        system_online = True
        status_html = f'<span class="status-badge status-online">🟢 ONLINE</span> <span style="color: #00f3ff; font-family: Orbitron; margin-left: 20px;">⏱️ {current_time}</span>'
    except Exception as e:
        system_online = False
        wallet = None
        status_html = f'<span class="status-badge status-offline">🔴 OFFLINE</span> <span style="color: #ff2a6d; font-family: Orbitron; margin-left: 20px;">⏱️ {current_time}</span>'
    
    st.markdown(status_html, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

# Stop se sistema offline
if not system_online:
    st.error(f"⚠️ Sistema OFFLINE - Impossibile connettersi a Bybit")
    st.stop()

# --- KPI PRINCIPALI ---
if wallet:
    st.markdown('<div class="section-title">⚡ KEY PERFORMANCE INDICATORS</div>', unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    equity = wallet.get('equity', 0)
    balance = wallet.get('wallet_balance', 0)
    available = wallet.get('available', 0)
    pnl = wallet.get('unrealized_pnl', 0)
    
    with col1:
        st.metric("💰 TOTAL EQUITY", f"${equity:.2f}")
    
    with col2:
        st.metric("💵 WALLET BALANCE", f"${balance:.2f}")
    
    with col3:
        st.metric("✅ AVAILABLE", f"${available:.2f}")
    
    with col4:
        pnl_color = "normal" if pnl >= 0 else "inverse"
        # Calculate PnL as percentage of total equity
        pnl_pct_of_balance = (pnl / equity * 100) if equity > 0 else 0
        st.metric("📊 PNL APERTO", f"${pnl:.2f} ({pnl_pct_of_balance:+.2f}%)", delta=f"{pnl:.2f}", delta_color=pnl_color)
    
    st.markdown("---")

# --- COMMISSIONI BYBIT ---
try:
    render_fees_section()
    st.markdown("---")
except Exception as e:
    st.warning(f"⚠️ Impossibile caricare commissioni: {e}")

# --- COSTI API DEEPSEEK ---
try:
    render_api_costs_section()
    st.markdown("---")
except Exception as e:
    st.warning(f"⚠️ Impossibile caricare costi API: {e}")

# --- TABS PRINCIPALI ---
tab1, tab2, tab3 = st.tabs(["⚡ POSIZIONI APERTE", "📊 PERFORMANCE & GRAFICI", "📜 STORICO TRADING"])

with tab1:
    st.markdown('<div class="section-title">🎯 POSIZIONI ATTIVE</div>', unsafe_allow_html=True)
    
    positions = client.get_open_positions()
    
    if positions:
        df_pos = pd.DataFrame(positions)
        
        st.dataframe(
            df_pos, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Unrealized PnL": st.column_config.NumberColumn(format="$%.2f"),
                "PnL %": st.column_config.NumberColumn(format="%.2f%%"),
                "Entry Price": st.column_config.NumberColumn(format="$%.2f"),
            }
        )
        
        # Grafici per ogni posizione
        st.markdown('<div class="section-title">📈 GRAFICI POSIZIONI</div>', unsafe_allow_html=True)
        
        for idx, pos in enumerate(positions):
            with st.expander(f"🎯 {pos['Symbol']} - {pos['Side']} - PnL: ${pos['Unrealized PnL']:.2f}"):
                # Gauge meter per PnL %
                pnl_pct = pos['PnL %']
                
                fig_gauge = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=pnl_pct,
                    title={'text': f"PnL % - {pos['Symbol']}", 'font': {'size': 20, 'color': '#00f3ff', 'family': 'Orbitron'}},
                    delta={'reference': 0, 'font': {'size': 18}},
                    gauge={
                        'axis': {'range': [-10, 10], 'tickcolor': '#00f3ff'},
                        'bar': {'color': "#00ff9d" if pnl_pct >= 0 else "#ff2a6d", 'thickness': 0.8},
                        'bgcolor': 'rgba(26,26,46,0.5)',
                        'borderwidth': 2,
                        'bordercolor': '#00f3ff',
                        'steps': [
                            {'range': [-10, -5], 'color': "rgba(255,42,109,0.3)"},
                            {'range': [-5, 0], 'color': "rgba(255,42,109,0.1)"},
                            {'range': [0, 5], 'color': "rgba(0,255,157,0.1)"},
                            {'range': [5, 10], 'color': "rgba(0,255,157,0.3)"}
                        ],
                        'threshold': {
                            'line': {'color': "#bf00ff", 'width': 4},
                            'thickness': 0.8,
                            'value': pnl_pct
                        }
                    },
                    number={'font': {'size': 40, 'color': '#00ff9d' if pnl_pct >= 0 else '#ff2a6d', 'family': 'Orbitron'}}
                ))
                
                fig_gauge.update_layout(
                    height=300,
                    margin=dict(l=20, r=20, t=60, b=20),
                    paper_bgcolor='rgba(26,26,46,0.5)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font={'color': '#e0e0e0', 'family': 'Rajdhani'}
                )
                
                st.plotly_chart(fig_gauge, use_container_width=True)
    else:
        st.markdown('<div class="success-box">🟢 Nessuna posizione attiva al momento</div>', unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="section-title">📈 EQUITY CURVE</div>', unsafe_allow_html=True)
    
    # Filtra dati dal 9 dicembre 2025
    start_date = datetime(2025, 12, 9, 0, 0, 0, tzinfo=timezone.utc)
    hist = client.get_closed_pnl(limit=200, start_date=start_date)
    
    if hist and len(hist) > 0:
        df_hist = pd.DataFrame(hist)
        
        # === 4.1 EQUITY CURVE MIGLIORATO ===
        df_chart = df_hist.iloc[::-1].copy()
        df_chart['CumPnL'] = df_chart['Closed PnL'].cumsum()
        df_chart['Trade'] = range(1, len(df_chart) + 1)
        
        fig_equity = go.Figure()
        
        # Area chart con gradient neon
        fig_equity.add_trace(go.Scatter(
            x=df_chart['Trade'],
            y=df_chart['CumPnL'],
            mode='lines+markers',
            name='Profitto Cumulativo',
            line=dict(color='#00ff9d', width=3, shape='spline'),
            fill='tozeroy',
            fillcolor='rgba(0,255,157,0.2)',
            marker=dict(
                size=6,
                color=df_chart['Closed PnL'].apply(lambda x: '#00ff9d' if x >= 0 else '#ff2a6d'),
                line=dict(color='#00f3ff', width=2)
            ),
            hovertemplate='<b>Trade #%{x}</b><br>PnL Cumulativo: $%{y:.2f}<extra></extra>'
        ))
        
        # Annotazioni su massimi/minimi
        max_idx = df_chart['CumPnL'].idxmax()
        min_idx = df_chart['CumPnL'].idxmin()
        
        fig_equity.add_annotation(
            x=df_chart.loc[max_idx, 'Trade'],
            y=df_chart.loc[max_idx, 'CumPnL'],
            text=f"Max: ${df_chart.loc[max_idx, 'CumPnL']:.2f}",
            showarrow=True,
            arrowhead=2,
            arrowcolor='#00ff9d',
            font=dict(color='#00ff9d', size=12, family='Orbitron'),
            bgcolor='rgba(0,255,157,0.2)',
            bordercolor='#00ff9d',
            borderwidth=2
        )
        
        fig_equity.add_annotation(
            x=df_chart.loc[min_idx, 'Trade'],
            y=df_chart.loc[min_idx, 'CumPnL'],
            text=f"Min: ${df_chart.loc[min_idx, 'CumPnL']:.2f}",
            showarrow=True,
            arrowhead=2,
            arrowcolor='#ff2a6d',
            font=dict(color='#ff2a6d', size=12, family='Orbitron'),
            bgcolor='rgba(255,42,109,0.2)',
            bordercolor='#ff2a6d',
            borderwidth=2
        )
        
        fig_equity.update_layout(
            title=dict(
                text="CURVA PROFITTI CUMULATIVA",
                font=dict(size=24, color='#00f3ff', family='Orbitron'),
                x=0.5,
                xanchor='center'
            ),
            template="plotly_dark",
            paper_bgcolor='rgba(26,26,46,0.5)',
            plot_bgcolor='rgba(10,10,15,0.8)',
            height=450,
            margin=dict(l=40, r=40, t=60, b=40),
            xaxis=dict(
                title="Trade #",
                title_font=dict(color='#00f3ff', size=14, family='Orbitron'),
                tickfont=dict(color='#00f3ff'),
                gridcolor='rgba(0,243,255,0.1)',
                showgrid=True
            ),
            yaxis=dict(
                title="PnL Cumulativo ($)",
                title_font=dict(color='#00f3ff', size=14, family='Orbitron'),
                tickfont=dict(color='#00f3ff'),
                gridcolor='rgba(0,243,255,0.1)',
                showgrid=True,
                zeroline=True,
                zerolinecolor='rgba(255,255,255,0.3)',
                zerolinewidth=2
            ),
            font={'color': '#e0e0e0', 'family': 'Rajdhani'},
            hovermode='x unified',
            showlegend=False
        )
        
        st.plotly_chart(fig_equity, use_container_width=True)
        
        # === 4.2 GRAFICO PNL GIORNALIERO ===
        st.markdown('<div class="section-title">📊 PNL GIORNALIERO</div>', unsafe_allow_html=True)
        
        # Converti timestamp a date
        df_hist['date'] = pd.to_datetime(df_hist['ts'], unit='ms').dt.date
        daily_pnl = df_hist.groupby('date')['Closed PnL'].sum().reset_index()
        daily_pnl.columns = ['Date', 'PnL']
        daily_pnl['MA7'] = daily_pnl['PnL'].rolling(window=min(7, len(daily_pnl)), min_periods=1).mean()
        
        fig_daily = go.Figure()
        
        # Barre colorate
        colors = ['#00ff9d' if pnl >= 0 else '#ff2a6d' for pnl in daily_pnl['PnL']]
        
        fig_daily.add_trace(go.Bar(
            x=daily_pnl['Date'],
            y=daily_pnl['PnL'],
            name='PnL Giornaliero',
            marker=dict(
                color=colors,
                line=dict(color='#00f3ff', width=1)
            ),
            hovertemplate='<b>%{x}</b><br>PnL: $%{y:.2f}<extra></extra>'
        ))
        
        # Media mobile 7 giorni
        fig_daily.add_trace(go.Scatter(
            x=daily_pnl['Date'],
            y=daily_pnl['MA7'],
            name='Media Mobile 7gg',
            line=dict(color='#bf00ff', width=3, dash='dash'),
            hovertemplate='<b>%{x}</b><br>MA7: $%{y:.2f}<extra></extra>'
        ))
        
        fig_daily.update_layout(
            title=dict(
                text="PNL GIORNALIERO + MEDIA MOBILE 7 GIORNI",
                font=dict(size=24, color='#00f3ff', family='Orbitron'),
                x=0.5,
                xanchor='center'
            ),
            template="plotly_dark",
            paper_bgcolor='rgba(26,26,46,0.5)',
            plot_bgcolor='rgba(10,10,15,0.8)',
            height=400,
            margin=dict(l=40, r=40, t=60, b=40),
            xaxis=dict(
                title="Data",
                title_font=dict(color='#00f3ff', size=14, family='Orbitron'),
                tickfont=dict(color='#00f3ff'),
                gridcolor='rgba(0,243,255,0.1)'
            ),
            yaxis=dict(
                title="PnL ($)",
                title_font=dict(color='#00f3ff', size=14, family='Orbitron'),
                tickfont=dict(color='#00f3ff'),
                gridcolor='rgba(0,243,255,0.1)',
                zeroline=True,
                zerolinecolor='rgba(255,255,255,0.3)',
                zerolinewidth=2
            ),
            font={'color': '#e0e0e0', 'family': 'Rajdhani'},
            hovermode='x unified',
            showlegend=True,
            legend=dict(
                bgcolor='rgba(26,26,46,0.8)',
                bordercolor='#00f3ff',
                borderwidth=1,
                font=dict(color='#00f3ff')
            )
        )
        
        st.plotly_chart(fig_daily, use_container_width=True)
        
        # === 4.3 HEATMAP PERFORMANCE PER ORA ===
        st.markdown('<div class="section-title">🔥 HEATMAP PERFORMANCE PER ORA</div>', unsafe_allow_html=True)
        
        df_hist['hour'] = pd.to_datetime(df_hist['ts'], unit='ms').dt.hour
        df_hist['day_of_week'] = pd.to_datetime(df_hist['ts'], unit='ms').dt.day_name()
        
        # Pivot per heatmap
        heatmap_data = df_hist.pivot_table(
            values='Closed PnL',
            index='day_of_week',
            columns='hour',
            aggfunc='sum',
            fill_value=0
        )
        
        # Ordina i giorni della settimana
        days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        heatmap_data = heatmap_data.reindex([d for d in days_order if d in heatmap_data.index])
        
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=heatmap_data.values,
            x=heatmap_data.columns,
            y=heatmap_data.index,
            colorscale=[
                [0, '#ff2a6d'],
                [0.5, '#1a1a2e'],
                [1, '#00ff9d']
            ],
            text=heatmap_data.values,
            texttemplate='$%{text:.1f}',
            textfont={"size": 10, "color": "white", "family": "Orbitron"},
            hovertemplate='<b>%{y} - Ora %{x}</b><br>PnL: $%{z:.2f}<extra></extra>',
            colorbar=dict(
                title="PnL ($)",
                title_font=dict(color='#00f3ff', family='Orbitron'),
                tickfont=dict(color='#00f3ff')
            )
        ))
        
        fig_heatmap.update_layout(
            title=dict(
                text="PERFORMANCE PER ORA DEL GIORNO",
                font=dict(size=24, color='#00f3ff', family='Orbitron'),
                x=0.5,
                xanchor='center'
            ),
            template="plotly_dark",
            paper_bgcolor='rgba(26,26,46,0.5)',
            plot_bgcolor='rgba(10,10,15,0.8)',
            height=400,
            margin=dict(l=40, r=40, t=60, b=40),
            xaxis=dict(
                title="Ora del Giorno",
                title_font=dict(color='#00f3ff', size=14, family='Orbitron'),
                tickfont=dict(color='#00f3ff'),
                side='bottom'
            ),
            yaxis=dict(
                title="Giorno della Settimana",
                title_font=dict(color='#00f3ff', size=14, family='Orbitron'),
                tickfont=dict(color='#00f3ff')
            ),
            font={'color': '#e0e0e0', 'family': 'Rajdhani'}
        )
        
        st.plotly_chart(fig_heatmap, use_container_width=True)
        
        # === 4.4 & 4.5 STATISTICHE AVANZATE + GAUGE METERS ===
        st.markdown('<div class="section-title">📊 STATISTICHE PERFORMANCE AVANZATE</div>', unsafe_allow_html=True)
        
        total_trades = len(df_hist)
        winning_trades = len(df_hist[df_hist['Closed PnL'] > 0])
        losing_trades = len(df_hist[df_hist['Closed PnL'] < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        total_pnl = df_hist['Closed PnL'].sum()
        avg_win = df_hist[df_hist['Closed PnL'] > 0]['Closed PnL'].mean() if winning_trades > 0 else 0
        avg_loss = df_hist[df_hist['Closed PnL'] < 0]['Closed PnL'].mean() if losing_trades > 0 else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        # Calcoli aggiuntivi
        best_trade = df_hist['Closed PnL'].max()
        worst_trade = df_hist['Closed PnL'].min()
        
        # Max Drawdown
        cum_pnl = df_hist.iloc[::-1]['Closed PnL'].cumsum()
        running_max = cum_pnl.expanding().max()
        drawdown = cum_pnl - running_max
        max_drawdown = drawdown.min()
        max_drawdown_pct = (max_drawdown / running_max.max() * 100) if running_max.max() > 0 else 0
        
        # ROI totale (assumendo capital iniziale come max equity - total pnl)
        initial_capital = max(DEFAULT_INITIAL_CAPITAL, equity - total_pnl) if wallet else DEFAULT_INITIAL_CAPITAL
        roi_pct = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0
        
        # Sharpe Ratio (stima semplificata: media/std dei trade)
        sharpe_ratio = (df_hist['Closed PnL'].mean() / df_hist['Closed PnL'].std()) if df_hist['Closed PnL'].std() > 0 else 0
        sharpe_ratio_annualized = sharpe_ratio * np.sqrt(TRADING_DAYS_PER_YEAR)  # Annualizzato
        
        # Average Trade Duration (placeholder - non abbiamo dati di entry time)
        avg_duration = "N/A"
        
        # Current Streak
        df_sorted = df_hist.iloc[::-1]
        current_streak = 0
        if len(df_sorted) > 0:
            last_result = df_sorted.iloc[-1]['Closed PnL'] > 0
            for pnl in reversed(df_sorted['Closed PnL'].values):
                if (pnl > 0) == last_result:
                    current_streak += 1
                else:
                    break
            current_streak = current_streak if last_result else -current_streak
        
        # Metriche base
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("🎯 TOTAL TRADES", total_trades)
        
        with col2:
            st.metric("✅ WIN RATE", f"{win_rate:.1f}%")
        
        with col3:
            pnl_delta_color = "normal" if total_pnl >= 0 else "inverse"
            st.metric("💰 TOTAL PNL", f"${total_pnl:.2f}", delta=f"${total_pnl:.2f}", delta_color=pnl_delta_color)
        
        with col4:
            st.metric("📈 PROFIT FACTOR", f"{profit_factor:.2f}")
        
        with col5:
            streak_emoji = "🔥" if current_streak > 0 else "❄️"
            streak_text = f"+{current_streak} W" if current_streak > 0 else f"{current_streak} L" if current_streak < 0 else "0"
            st.metric(f"{streak_emoji} STREAK", streak_text)
        
        # Metriche aggiuntive
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("🏆 BEST TRADE", f"${best_trade:.2f}")
        
        with col2:
            st.metric("💥 WORST TRADE", f"${worst_trade:.2f}")
        
        with col3:
            st.metric("📉 MAX DRAWDOWN", f"${max_drawdown:.2f}")
        
        with col4:
            st.metric("📊 SHARPE RATIO", f"{sharpe_ratio_annualized:.2f}")
        
        with col5:
            st.metric("⏱️ AVG DURATION", avg_duration)
        
        st.markdown("---")
        
        # === GAUGE METERS ANIMATI ===
        st.markdown('<div class="section-title">🎛️ GAUGE METERS</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # ROI Gauge
            fig_roi = go.Figure(go.Indicator(
                mode="gauge+number",
                value=roi_pct,
                title={'text': "ROI TOTALE %", 'font': {'size': 20, 'color': '#00ff9d', 'family': 'Orbitron'}},
                gauge={
                    'axis': {'range': [-50, 100], 'tickcolor': '#00f3ff'},
                    'bar': {'color': "#00ff9d" if roi_pct >= 0 else "#ff2a6d", 'thickness': 0.7},
                    'bgcolor': 'rgba(26,26,46,0.5)',
                    'borderwidth': 3,
                    'bordercolor': '#00f3ff',
                    'steps': [
                        {'range': [-50, 0], 'color': "rgba(255,42,109,0.2)"},
                        {'range': [0, 50], 'color': "rgba(0,255,157,0.2)"},
                        {'range': [50, 100], 'color': "rgba(0,255,157,0.4)"}
                    ],
                    'threshold': {
                        'line': {'color': "#bf00ff", 'width': 4},
                        'thickness': 0.8,
                        'value': roi_pct
                    }
                },
                number={'suffix': "%", 'font': {'size': 40, 'color': '#00ff9d' if roi_pct >= 0 else '#ff2a6d', 'family': 'Orbitron'}}
            ))
            
            fig_roi.update_layout(
                height=300,
                margin=dict(l=10, r=10, t=60, b=10),
                paper_bgcolor='rgba(26,26,46,0.5)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#e0e0e0', 'family': 'Rajdhani'}
            )
            
            st.plotly_chart(fig_roi, use_container_width=True)
        
        with col2:
            # Drawdown Gauge
            fig_dd = go.Figure(go.Indicator(
                mode="gauge+number",
                value=abs(max_drawdown_pct),
                title={'text': "DRAWDOWN %", 'font': {'size': 20, 'color': '#ff2a6d', 'family': 'Orbitron'}},
                gauge={
                    'axis': {'range': [0, 50], 'tickcolor': '#00f3ff'},
                    'bar': {'color': "#ff2a6d", 'thickness': 0.7},
                    'bgcolor': 'rgba(26,26,46,0.5)',
                    'borderwidth': 3,
                    'bordercolor': '#00f3ff',
                    'steps': [
                        {'range': [0, 10], 'color': "rgba(0,255,157,0.2)"},
                        {'range': [10, 25], 'color': "rgba(255,165,0,0.2)"},
                        {'range': [25, 50], 'color': "rgba(255,42,109,0.3)"}
                    ],
                    'threshold': {
                        'line': {'color': "#bf00ff", 'width': 4},
                        'thickness': 0.8,
                        'value': abs(max_drawdown_pct)
                    }
                },
                number={'suffix': "%", 'font': {'size': 40, 'color': '#ff2a6d', 'family': 'Orbitron'}}
            ))
            
            fig_dd.update_layout(
                height=300,
                margin=dict(l=10, r=10, t=60, b=10),
                paper_bgcolor='rgba(26,26,46,0.5)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#e0e0e0', 'family': 'Rajdhani'}
            )
            
            st.plotly_chart(fig_dd, use_container_width=True)
        
        with col3:
            # Risk Score (Win Rate gauge)
            risk_score = win_rate
            
            fig_risk = go.Figure(go.Indicator(
                mode="gauge+number",
                value=risk_score,
                title={'text': "WIN RATE %", 'font': {'size': 20, 'color': '#00f3ff', 'family': 'Orbitron'}},
                gauge={
                    'axis': {'range': [0, 100], 'tickcolor': '#00f3ff'},
                    'bar': {'color': "#00ff9d" if risk_score >= 50 else "#ff2a6d", 'thickness': 0.7},
                    'bgcolor': 'rgba(26,26,46,0.5)',
                    'borderwidth': 3,
                    'bordercolor': '#00f3ff',
                    'steps': [
                        {'range': [0, 30], 'color': "rgba(255,42,109,0.3)"},
                        {'range': [30, 50], 'color': "rgba(255,165,0,0.2)"},
                        {'range': [50, 70], 'color': "rgba(0,255,157,0.2)"},
                        {'range': [70, 100], 'color': "rgba(0,255,157,0.4)"}
                    ],
                    'threshold': {
                        'line': {'color': "#bf00ff", 'width': 4},
                        'thickness': 0.8,
                        'value': risk_score
                    }
                },
                number={'suffix': "%", 'font': {'size': 40, 'color': '#00ff9d' if risk_score >= 50 else '#ff2a6d', 'family': 'Orbitron'}}
            ))
            
            fig_risk.update_layout(
                height=300,
                margin=dict(l=10, r=10, t=60, b=10),
                paper_bgcolor='rgba(26,26,46,0.5)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#e0e0e0', 'family': 'Rajdhani'}
            )
            
            st.plotly_chart(fig_risk, use_container_width=True)
        
        # Pie chart distribuzione wins/losses
        st.markdown('<div class="section-title">🥧 DISTRIBUZIONE WIN/LOSS</div>', unsafe_allow_html=True)
        
        fig_pie = go.Figure(data=[go.Pie(
            labels=['Winning Trades', 'Losing Trades'],
            values=[winning_trades, losing_trades],
            marker=dict(
                colors=['#00ff9d', '#ff2a6d'],
                line=dict(color='#00f3ff', width=2)
            ),
            hole=0.5,
            textfont=dict(size=16, color='white', family='Orbitron'),
            hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>'
        )])
        
        fig_pie.update_layout(
            title=dict(
                text="WIN/LOSS DISTRIBUTION",
                font=dict(size=24, color='#00f3ff', family='Orbitron'),
                x=0.5,
                xanchor='center'
            ),
            height=400,
            margin=dict(l=20, r=20, t=60, b=20),
            paper_bgcolor='rgba(26,26,46,0.5)',
            plot_bgcolor='rgba(0,0,0,0)',
            font={'color': '#e0e0e0', 'family': 'Rajdhani'},
            showlegend=True,
            legend=dict(
                bgcolor='rgba(26,26,46,0.8)',
                bordercolor='#00f3ff',
                borderwidth=1,
                font=dict(color='#00f3ff', size=14)
            )
        )
        
        st.plotly_chart(fig_pie, use_container_width=True)
        
    else:
        st.markdown('<div class="info-box">ℹ️ Nessuno storico disponibile dal 9 dicembre 2025</div>', unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="section-title">📜 STORICO POSIZIONI CHIUSE</div>', unsafe_allow_html=True)
    
    # Filtra dati dal 9 dicembre 2025
    start_date = datetime(2025, 12, 9, 0, 0, 0, tzinfo=timezone.utc)
    hist = client.get_closed_pnl(limit=50, start_date=start_date)
    
    if hist:
        df_hist = pd.DataFrame(hist)
        
        # Rimuovi colonne non necessarie per la visualizzazione
        display_cols = ['Symbol', 'Side', 'Closed PnL', 'Exit Time']
        if 'exec_fee' in df_hist.columns:
            display_cols.insert(3, 'exec_fee')
            df_hist = df_hist.rename(columns={'exec_fee': 'Fee'})
        
        df_display = df_hist[[col for col in display_cols if col in df_hist.columns or col == 'Fee']]
        
        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Closed PnL": st.column_config.NumberColumn(format="$%.2f"),
                "Fee": st.column_config.NumberColumn(format="$%.4f"),
            }
        )
    else:
        st.markdown('<div class="info-box">ℹ️ Nessuno storico disponibile dal 9 dicembre 2025</div>', unsafe_allow_html=True)

# --- AI DECISION LOG ---
st.markdown("---")
render_ai_reasoning()

# --- FOOTER ---
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    status_text = "🟢 Sistema Online" if system_online else "🔴 Sistema Offline"
    st.markdown(f'<p style="color: #00ff9d; font-family: Orbitron; font-weight: 700;">{status_text}</p>', unsafe_allow_html=True)
with col2:
    st.markdown(f'<p style="color: #00f3ff; font-family: Rajdhani;">Ultimo aggiornamento: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>', unsafe_allow_html=True)
with col3:
    st.markdown('<p style="color: #bf00ff; font-family: Orbitron; font-weight: 700;">Auto-refresh: 5 secondi</p>', unsafe_allow_html=True)

# --- AUTO REFRESH ---
time.sleep(5)
st.rerun()
