import streamlit as st
import pandas as pd

def render_open_positions(positions):
    """Renderizza le posizioni aperte"""
    
    st.markdown("""
    <div class="section-header">
        <span>⚡ POSIZIONI APERTE</span>
        <span class="position-count">{} attive</span>
    </div>
    """.format(len(positions) if positions else 0), unsafe_allow_html=True)
    
    if not positions:
        st.markdown("""
        <div class="empty-state">
            <span class="empty-icon">💤</span>
            <span>Nessuna posizione aperta</span>
        </div>
        """, unsafe_allow_html=True)
        return
    
    for pos in positions:
        pnl = pos.get('unrealized_pnl', 0)
        pnl_pct = pos.get('pnl_pct', 0)
        side_color = "#00ff41" if pos['side'] == "Buy" else "#ff004c"
        pnl_color = "profit" if pnl >= 0 else "loss"
        arrow = "▲" if pnl >= 0 else "▼"
        
        st.markdown(f"""
        <div class="position-card">
            <div class="position-header">
                <span class="symbol">{pos['symbol']}</span>
                <span class="side" style="color: {side_color}">{pos['side'].upper()}</span>
                <span class="leverage">{pos['leverage']}x</span>
            </div>
            <div class="position-body">
                <div class="pos-row">
                    <span class="pos-label">Size:</span>
                    <span class="pos-value">{pos['size']}</span>
                </div>
                <div class="pos-row">
                    <span class="pos-label">Entry:</span>
                    <span class="pos-value">${pos['entry_price']:,.4f}</span>
                </div>
                <div class="pos-row">
                    <span class="pos-label">Mark:</span>
                    <span class="pos-value">${pos['mark_price']:,.4f}</span>
                </div>
                <div class="pos-row">
                    <span class="pos-label">Value:</span>
                    <span class="pos-value">${pos['position_value']:,.2f}</span>
                </div>
            </div>
            <div class="position-pnl {pnl_color}">
                <span class="pnl-amount">{arrow} ${pnl:+,.2f}</span>
                <span class="pnl-pct">{pnl_pct:+.2f}%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

def render_closed_positions(closed_positions):
    """Renderizza lo storico delle posizioni chiuse"""
    
    st.markdown("""
    <div class="section-header">
        <span>📜 STORICO CHIUSURE</span>
        <span class="subtitle">Ultime 10 operazioni</span>
    </div>
    """, unsafe_allow_html=True)
    
    if not closed_positions:
        st.markdown("""
        <div class="empty-state">
            <span class="empty-icon">📭</span>
            <span>Nessuna posizione chiusa recente</span>
        </div>
        """, unsafe_allow_html=True)
        return
    
    # Inverti per mostrare le piu recenti prima
    for trade in reversed(closed_positions[-10:]):
        pnl = trade.get('closed_pnl', 0)
        pnl_color = "profit" if pnl >= 0 else "loss"
        icon = "✅" if pnl >= 0 else "❌"
        
        st.markdown(f"""
        <div class="closed-trade {pnl_color}">
            <div class="trade-icon">{icon}</div>
            <div class="trade-info">
                <span class="trade-symbol">{trade['symbol']}</span>
                <span class="trade-side">{trade['side']}</span>
            </div>
            <div class="trade-prices">
                <span>Entry: ${trade['entry_price']:,.4f}</span>
                <span>Exit: ${trade['exit_price']:,.4f}</span>
            </div>
            <div class="trade-pnl {pnl_color}">
                ${pnl:+,.2f}
            </div>
            <div class="trade-time">{trade['updated_time']}</div>
        </div>
        """, unsafe_allow_html=True)
