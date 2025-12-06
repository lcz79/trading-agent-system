import streamlit as st
from utils.calculations import calculate_performance, calculate_daily_stats, calculate_max_drawdown

def render_account_info(wallet_data, equity_history):
    """Renderizza le informazioni del conto"""
    
    if not wallet_data:
        st.error("⚠️ Impossibile connettersi a Bybit")
        return
    
    equity = wallet_data.get('equity', 0)
    available = wallet_data.get('available', 0)
    unrealized_pnl = wallet_data.get('unrealized_pnl', 0)
    
    # Calcola performance
    perf = calculate_performance(equity)
    daily = calculate_daily_stats(equity_history)
    max_dd = calculate_max_drawdown(equity_history)
    
    # Header con status
    st.markdown("""
    <div class="section-header">
        <span class="pulse-dot"></span>
        <span style="margin-left: 10px;">📊 ACCOUNT OVERVIEW - BYBIT</span>
    </div>
    """, unsafe_allow_html=True)
    
    # Metriche principali
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">💰 EQUITY TOTALE</div>
            <div class="metric-value">${equity:,.2f}</div>
            <div class="metric-sub">Valore totale del conto</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        color = "profit" if perf['profit_loss'] >= 0 else "loss"
        arrow = "▲" if perf['profit_loss'] >= 0 else "▼"
        st.markdown(f"""
        <div class="metric-card {color}">
            <div class="metric-label">📈 P&L TOTALE (dal {perf['starting_date']})</div>
            <div class="metric-value {color}">{arrow} ${perf['profit_loss']:+,.2f}</div>
            <div class="metric-sub {color}">{perf['profit_loss_pct']:+.2f}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        color = "profit" if unrealized_pnl >= 0 else "loss"
        st.markdown(f"""
        <div class="metric-card {color}">
            <div class="metric-label">⚡ P&L NON REALIZZATO</div>
            <div class="metric-value {color}">${unrealized_pnl:+,.2f}</div>
            <div class="metric-sub">Posizioni aperte</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        color = "profit" if daily['daily_change'] >= 0 else "loss"
        st.markdown(f"""
        <div class="metric-card {color}">
            <div class="metric-label">📅 OGGI</div>
            <div class="metric-value {color}">${daily['daily_change']:+,.2f}</div>
            <div class="metric-sub {color}">{daily['daily_change_pct']:+.2f}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Seconda riga metriche
    st.markdown("<br>", unsafe_allow_html=True)
    col5, col6, col7, col8 = st.columns(4)
    
    with col5:
        st.markdown(f"""
        <div class="metric-card-small">
            <div class="metric-label-small">💳 DISPONIBILE</div>
            <div class="metric-value-small">${available:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col6:
        invested = equity - available
        st.markdown(f"""
        <div class="metric-card-small">
            <div class="metric-label-small">🔒 INVESTITO</div>
            <div class="metric-value-small">${invested:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col7:
        st.markdown(f"""
        <div class="metric-card-small">
            <div class="metric-label-small">💵 SALDO INIZIALE</div>
            <div class="metric-value-small">${perf['starting_balance']:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col8:
        st.markdown(f"""
        <div class="metric-card-small loss">
            <div class="metric-label-small">📉 MAX DRAWDOWN</div>
            <div class="metric-value-small loss">-{max_dd:.2f}%</div>
        </div>
        """, unsafe_allow_html=True)
