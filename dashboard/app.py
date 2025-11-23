import streamlit as st
import pandas as pd
import json
import os
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# CONFIGURAZIONE PAGINA
st.set_page_config(
    page_title="AI Trading Control Room",
    page_icon="🦅",
    layout="wide"
)

# PERCORSI DATI CONDIVISI
DATA_DIR = "/app/data"
CONFIG_FILE = f"{DATA_DIR}/config.json"
LOGS_FILE = f"{DATA_DIR}/logs.json"
ACTIONS_FILE = f"{DATA_DIR}/actions.json"
EQUITY_FILE = f"{DATA_DIR}/equity.json"

# --- FUNZIONI DI UTILITÀ ---
def load_data(file_path, default=None):
    """Carica un file JSON in modo sicuro"""
    if default is None: default = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f: return json.load(f)
        except: pass
    return default

def save_config(config):
    """Salva la configurazione su file"""
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)

# Carica configurazione o usa default
default_conf = {"risk_per_trade": 1.0, "strategy": "intraday", "active": True, "initial_budget": 1000.0}
config = load_data(CONFIG_FILE, default_conf)

# --- SIDEBAR (LA TUA PLANCIA DI COMANDO) ---
st.sidebar.title("🎛️ Control Room")

# 1. Interruttore Generale
st.sidebar.subheader("Stato Sistema")
active = st.sidebar.toggle("SYSTEM ACTIVE", value=config.get("active", True))
if active != config.get("active"):
    config["active"] = active
    save_config(config)
    st.rerun()

st.sidebar.divider()

# 2. Strategia
st.sidebar.subheader("Strategia")
strategy = st.sidebar.selectbox(
    "Modalità Operativa",
    ["intraday", "swing"],
    index=0 if config.get("strategy") == "intraday" else 1,
    help="Intraday: Priorità grafico 15m. Swing: Priorità grafico 4h."
)

# 3. Gestione Rischio
st.sidebar.subheader("Gestione Rischio")
risk = st.sidebar.slider(
    "Rischio per Trade (%)", 
    min_value=0.5, max_value=5.0, 
    value=float(config.get("risk_per_trade", 1.0)),
    step=0.5
)

# 4. Budget (Visuale)
budget = st.sidebar.number_input("Budget Iniziale ($)", value=float(config.get("initial_budget", 1000.0)))

# Pulsante SALVA
if st.sidebar.button("✅ APPLICA MODIFICHE"):
    config["strategy"] = strategy
    config["risk_per_trade"] = risk
    config["initial_budget"] = budget
    save_config(config)
    st.sidebar.success("Configurazione salvata! L'AI la userà al prossimo ciclo.")

# --- PAGINA PRINCIPALE ---
st.title("🦅 AI Trading Agent - Dashboard")

# KPI IN ALTO
equity_data = load_data(EQUITY_FILE)
# Se abbiamo dati reali usiamo l'ultimo, altrimenti il budget iniziale
current_equity = equity_data[-1]['equity'] if equity_data else budget
pnl = current_equity - budget
pnl_pct = (pnl / budget) * 100 if budget > 0 else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Equity Attuale", f"${current_equity:,.2f}", f"{pnl_pct:.2f}%")
col2.metric("Budget Iniziale", f"${budget:,.2f}")
col3.metric("Strategia Attiva", strategy.upper())
col4.metric("Rischio Rischio", f"{risk}% / trade")

st.divider()

# SEZIONE 1: GRAFICO EQUITY
st.subheader("📈 Curva dei Profitti")
if equity_data:
    df_eq = pd.DataFrame(equity_data)
    df_eq['timestamp'] = pd.to_datetime(df_eq['timestamp'])
    
    # Grafico interattivo
    fig = px.line(df_eq, x='timestamp', y='equity', title="Equity vs Tempo", markers=True)
    fig.add_hline(y=budget, line_dash="dash", line_color="red", annotation_text="Budget Iniziale")
    fig.update_layout(xaxis_title="Orario", yaxis_title="Capitale ($)")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("⏳ In attesa del primo dato sul saldo (max 15 min)...")

# SEZIONE 2: TABELLA DECISIONI AI
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("🧠 Ultime Analisi AI")
    logs = load_data(LOGS_FILE)
    
    if logs:
        df_logs = pd.DataFrame(logs)
        # Ordina dal più recente
        df_logs = df_logs.sort_values('timestamp', ascending=False).head(20)
        
        for idx, row in df_logs.iterrows():
            # Colore in base alla decisione
            emoji = "🟡"
            if row['decision'] == "OPEN_LONG": emoji = "🟢"
            elif row['decision'] == "OPEN_SHORT": emoji = "🔴"
            
            with st.expander(f"{emoji} {row['timestamp']} | {row['symbol']} | {row['decision']}"):
                st.markdown(f"**Strategia usata:** `{row.get('strategy_used', 'N/A')}`")
                st.markdown(f"**Analisi:** {row['reason']}")
    else:
        st.info("Nessuna analisi salvata ancora. Attendi il prossimo ciclo.")

# SEZIONE 3: AZIONI ESEGUITE (Trailing Stop)
with col_right:
    st.subheader("🛡️ Log Operativo (Trailing Stop)")
    actions = load_data(ACTIONS_FILE)
    
    if actions:
        df_actions = pd.DataFrame(actions).sort_values('timestamp', ascending=False).head(20)
        st.dataframe(
            df_actions[['timestamp', 'symbol', 'details']], 
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Nessun movimento di Stop Loss recente.")
