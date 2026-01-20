import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime
from config import STARTING_DATE, STARTING_BALANCE

def render_equity_chart(equity_history):
    """Renderizza il grafico dell'equity"""
    
    st.markdown("""
    <div class="section-header">
        <span>📈 PERFORMANCE CHART</span>
        <span class="live-badge">● LIVE</span>
    </div>
    """, unsafe_allow_html=True)
    
    if not equity_history or len(equity_history) < 2:
        st.info("⏳ In attesa di dati sufficienti per il grafico...")
        return
    
    df = pd.DataFrame(equity_history)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    # Calcola P&L percentuale dal punto di partenza
    df['pnl_pct'] = ((df['equity'] / STARTING_BALANCE) - 1) * 100
    
    # Crea figura con subplot
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=('Equity (€)', 'P&L (%)')
    )
    
    # Grafico Equity principale
    fig.add_trace(
        go.Scatter(
            x=df['timestamp'],
            y=df['equity'],
            mode='lines',
            name='Equity',
            line=dict(color='#00ff41', width=2),
            fill='tozeroy',
            fillcolor='rgba(0, 255, 65, 0.1)',
            hovertemplate='<b>%{x}</b><br>Equity: $%{y:,.2f}<extra></extra>'
        ),
        row=1, col=1
    )
    
    # Linea di riferimento saldo iniziale
    fig.add_hline(
        y=STARTING_BALANCE,
        line_dash="dash",
        line_color="#ffaa00",
        annotation_text=f"Saldo Iniziale: ${STARTING_BALANCE:,.2f}",
        annotation_position="right",
        row=1, col=1
    )
    
    # Grafico P&L percentuale
    colors = ['#00ff41' if val >= 0 else '#ff004c' for val in df['pnl_pct']]
    fig.add_trace(
        go.Bar(
            x=df['timestamp'],
            y=df['pnl_pct'],
            name='P&L %',
            marker_color=colors,
            hovertemplate='<b>%{x}</b><br>P&L: %{y:+.2f}%<extra></extra>'
        ),
        row=2, col=1
    )
    
    # Zero line per P&L
    fig.add_hline(y=0, line_color="#555", line_width=1, row=2, col=1)
    
    # Layout
    fig.update_layout(
        template="plotly_dark",
        height=500,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(10,10,10,0.8)',
        font=dict(family="Courier New", color='#e0e0e0'),
        showlegend=False,
        margin=dict(l=60, r=20, t=40, b=20),
        xaxis2=dict(
            rangeslider=dict(visible=False),
            type='date'
        ),
        yaxis=dict(
            gridcolor='rgba(50,50,50,0.5)',
            tickformat='€,.0f'
        ),
        yaxis2=dict(
            gridcolor='rgba(50,50,50,0.5)',
            tickformat='+.2f',
            ticksuffix='%'
        )
    )
    
    # Annotation con stats
    current_equity = df['equity'].iloc[-1]
    current_pnl = current_equity - STARTING_BALANCE
    current_pnl_pct = ((current_equity / STARTING_BALANCE) - 1) * 100
    
    fig.add_annotation(
        x=0.02, y=0.98,
        xref='paper', yref='paper',
        text=f"<b>CURRENT: ${current_equity:,.2f}</b><br>P&L: €{current_pnl:+,.2f} ({current_pnl_pct:+.2f}%)",
        showarrow=False,
        font=dict(size=12, color='#00ff41' if current_pnl >= 0 else '#ff004c'),
        align='left',
        bgcolor='rgba(0,0,0,0.7)',
        bordercolor='#333',
        borderwidth=1,
        borderpad=10
    )
    
    st.plotly_chart(fig, width='stretch')
