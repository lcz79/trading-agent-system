import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objs as go
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime

# --- CONFIGURAZIONE ---
# Usiamo i nomi host definiti nella rete Docker interna
POSITION_MANAGER_URL = "http://position-manager-agent:8000"
MASTER_AI_URL = "http://master-ai-agent:8000"

app = dash.Dash(__name__, title="Rizzo Bot Dashboard 7.3")
app.layout = html.Div(style={'backgroundColor': '#121212', 'color': '#e0e0e0', 'fontFamily': 'Roboto, sans-serif', 'minHeight': '100vh', 'padding': '20px'}, children=[
    
    # HEADER
    html.Div([
        html.H1("🤖 RIZZO TRADING BOT", style={'textAlign': 'center', 'color': '#00ff88', 'marginBottom': '10px'}),
        html.P("Live Control Center • Strategy: Rizzo (Trend + Volatility)", style={'textAlign': 'center', 'color': '#888'}),
    ], style={'marginBottom': '30px'}),

    # KPI CARDS
    html.Div([
        html.Div([html.H3("WALLET BALANCE"), html.H2(id='balance-text', style={'color': '#fff'})], style={'backgroundColor': '#1e1e1e', 'padding': '20px', 'borderRadius': '10px', 'width': '30%', 'textAlign': 'center'}),
        html.Div([html.H3("ACTIVE TRADES"), html.H2(id='active-trades-text', style={'color': '#00d4ff'})], style={'backgroundColor': '#1e1e1e', 'padding': '20px', 'borderRadius': '10px', 'width': '30%', 'textAlign': 'center'}),
        html.Div([html.H3("AI STATUS"), html.H2(id='ai-status-text', style={'color': '#ff0055'})], style={'backgroundColor': '#1e1e1e', 'padding': '20px', 'borderRadius': '10px', 'width': '30%', 'textAlign': 'center'}),
    ], style={'display': 'flex', 'justifyContent': 'space-between', 'marginBottom': '20px'}),

    # MAIN CONTENT
    html.Div([
        # LEFT: POSITIONS & LOGS
        html.Div([
            html.H3("🔥 LIVE POSITIONS", style={'borderBottom': '2px solid #00ff88', 'paddingBottom': '10px'}),
            html.Div(id='positions-container'),
            
            html.H3("📜 LIVE LOGS", style={'marginTop': '30px', 'borderBottom': '2px solid #666', 'paddingBottom': '10px'}),
            html.Div(id='logs-container', style={'height': '300px', 'overflowY': 'scroll', 'backgroundColor': '#000', 'padding': '10px', 'fontFamily': 'monospace', 'fontSize': '12px', 'color': '#0f0'})
        ], style={'width': '48%'}),

        # RIGHT: AI BRAIN
        html.Div([
            html.H3("🧠 AI REASONING (LAST BATCH)", style={'borderBottom': '2px solid #ff0055', 'paddingBottom': '10px'}),
            html.Div(id='ai-reasoning-container', style={'backgroundColor': '#1e1e1e', 'padding': '15px', 'borderRadius': '5px', 'minHeight': '400px', 'whiteSpace': 'pre-wrap', 'overflowY': 'scroll'})
        ], style={'width': '48%'})

    ], style={'display': 'flex', 'justifyContent': 'space-between'}),

    dcc.Interval(id='interval-component', interval=2000, n_intervals=0)
])

@app.callback(
    [Output('balance-text', 'children'),
     Output('active-trades-text', 'children'),
     Output('ai-status-text', 'children'),
     Output('positions-container', 'children'),
     Output('logs-container', 'children'),
     Output('ai-reasoning-container', 'children')],
    [Input('interval-component', 'n_intervals')]
)
def update_dashboard(n):
    # Defaults
    bal_str = "$ ---"
    trades_str = "0"
    ai_stat = "WAITING..."
    pos_html = html.P("No active positions.", style={'color': '#666'})
    logs_html = []
    ai_html = html.P("No analysis yet.", style={'color': '#666'})

    # 1. POSITION MANAGER DATA
    try:
        # Balance
        try:
            r = requests.get(f"{POSITION_MANAGER_URL}/get_wallet_balance", timeout=1)
            if r.status_code == 200:
                bal = r.json().get('balance', 0)
                bal_str = f"${bal:,.2f}"
        except: bal_str = "ERR"

        # Positions
        try:
            r = requests.get(f"{POSITION_MANAGER_URL}/get_open_positions", timeout=1)
            if r.status_code == 200:
                positions = r.json()
                trades_str = str(len(positions))
                if positions:
                    cards = []
                    for p in positions:
                        pnl = p.get('pnl', 0)
                        color = '#00ff88' if pnl >= 0 else '#ff0055'
                        cards.append(html.Div([
                            html.H4(f"{p['symbol']} ({p['side']})"),
                            html.P(f"Size: {p['size']} | Entry: ${p['entry_price']}"),
                            html.H3(f"PnL: ${pnl:.2f}", style={'color': color})
                        ], style={'backgroundColor': '#2a2a2a', 'padding': '10px', 'marginBottom': '10px', 'borderRadius': '5px', 'borderLeft': f'4px solid {color}'}))
                    pos_html = cards
        except: pass

        # Logs
        try:
            r = requests.get(f"{POSITION_MANAGER_URL}/management_logs", timeout=1)
            if r.status_code == 200:
                logs = r.json().get('logs', [])
                logs_html = [html.P(l, style={'margin': '2px 0'}) for l in reversed(logs)]
        except: pass

    except Exception: pass

    # 2. MASTER AI DATA
    try:
        r = requests.get(f"{MASTER_AI_URL}/latest_reasoning", timeout=1)
        if r.status_code == 200:
            data = r.json()
            ai_stat = "ACTIVE"
            decisions = data.get("decisions", {})
            
            content = []
            for sym, det in decisions.items():
                dec = det.get('decision')
                col = '#00ff88' if "OPEN" in dec else ('#ffaa00' if "CLOSE" in dec else '#888')
                content.append(html.Div([
                    html.H4(f"{sym}: {dec}", style={'color': col}),
                    html.P(f"Reason: {det.get('reasoning')}", style={'fontSize': '14px', 'color': '#ddd'}),
                    html.Hr(style={'borderColor': '#333'})
                ]))
            if content: ai_html = content
    except: ai_stat = "OFFLINE"

    return bal_str, trades_str, ai_stat, pos_html, logs_html, ai_html

if __name__ == '__main__':
    app.run_server(host='0.0.0.0', port=8050, debug=False)
