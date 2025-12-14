import streamlit as st
import json
import html
from utils.data_manager import get_ai_decisions

def render_ai_reasoning():
    """Renderizza i ragionamenti dell'AI"""
    
    st.markdown("""
    <div class="section-header">
        <span>🧠 AI DECISION LOG</span>
        <span class="ai-status">● SISTEMA ATTIVO</span>
    </div>
    """, unsafe_allow_html=True)
    
    decisions = get_ai_decisions()
    
    if not decisions:
        st.markdown("""
        <div class="empty-state">
            <span class="empty-icon">🤖</span>
            <span>Nessuna decisione AI registrata</span>
        </div>
        """, unsafe_allow_html=True)
        return
    
    # Mostra le ultime 10 decisioni
    for decision in reversed(decisions[-10:]):
        action = decision.get('action', 'HOLD')
        symbol = decision.get('symbol', 'N/A')
        
        # Determina emoji e colore in base all'azione
        if action == 'OPEN_LONG':
            action_emoji = '🟢'
            action_color = '#00ff41'
            action_text = 'OPEN LONG'
        elif action == 'OPEN_SHORT':
            action_emoji = '🔴'
            action_color = '#ff004c'
            action_text = 'OPEN SHORT'
        elif action == 'CLOSE':
            action_emoji = '⛔'
            action_color = '#ffaa00'
            action_text = 'CLOSE'
        else:
            # HOLD
            if symbol == 'PORTFOLIO':
                action_emoji = '📊'
                action_color = '#4da6ff'
                action_text = 'MONITORING'
            else:
                action_emoji = '⏸️'
                action_color = '#808080'
                action_text = 'HOLD'
        
        # Formatta timestamp
        timestamp = decision.get('timestamp', 'N/A')
        if timestamp != 'N/A':
            timestamp = timestamp[:19].replace('T', ' ')
        
        rationale = html.escape(decision.get('rationale', 'N/A'))
        leverage = decision.get('leverage', 1)
        size_pct = decision.get('size_pct', 0)
        analysis_summary = html.escape(decision.get('analysis_summary', ''))
        
        # New structured fields
        setup_confirmations = decision.get('setup_confirmations', [])
        blocked_by = decision.get('blocked_by', [])
        direction_considered = decision.get('direction_considered', 'NONE')
        
        # Gestione speciale per decisioni PORTFOLIO
        if symbol == 'PORTFOLIO':
            positions = decision.get('positions', [])
            positions_html = ''
            if positions:
                positions_html = '<div style="margin-top: 10px;"><strong style="color: #ffa500;">📈 Posizioni Attive:</strong><ul style="margin: 5px 0; padding-left: 20px;">'
                for pos in positions:
                    pos_symbol = html.escape(pos.get('symbol', 'N/A'))
                    pos_side = html.escape(pos.get('side', 'N/A'))
                    pos_pnl = pos.get('pnl', 0)
                    pos_pnl_pct = pos.get('pnl_pct', 0)
                    pnl_color = '#00ff41' if pos_pnl >= 0 else '#ff004c'
                    positions_html += f'<li><strong>{pos_symbol}</strong> ({pos_side}): <span style="color: {pnl_color};">${pos_pnl:.2f} ({pos_pnl_pct:+.2f}%)</span></li>'
                positions_html += '</ul></div>'
            
            # Renderizza blocked_by e direction se presenti
            blocked_html = ''
            if blocked_by:
                blocked_reasons = ', '.join(html.escape(str(b)) for b in blocked_by)
                blocked_html = f'<p><strong style="color: #ff6b6b;">🚫 Blocked By:</strong> {blocked_reasons}</p>'
            
            direction_html = ''
            if direction_considered and direction_considered != 'NONE':
                direction_color = '#00ff41' if direction_considered == 'LONG' else '#ff004c'
                direction_html = f'<p><strong style="color: #00d4ff;">🎯 Direction Considered:</strong> <span style="color: {direction_color};">{html.escape(direction_considered)}</span></p>'
            
            st.markdown(f"""
            <div class="ai-decision-card">
                <div class="decision-header">
                    <span class="decision-time">{timestamp}</span>
                    <span class="decision-action" style="color: {action_color}; text-shadow: 0 0 10px {action_color};">
                        {action_emoji} {action_text}
                    </span>
                    <span class="decision-symbol" style="color: #00d4ff; font-weight: 700;">{html.escape(symbol)}</span>
                </div>
                <div class="decision-reasoning">
                    <p><strong style="color: #00ff9d;">💡 Rationale:</strong> {rationale}</p>
                    {f'<p><strong style="color: #ff6b9d;">📊 Status:</strong> {analysis_summary}</p>' if analysis_summary else ''}
                    {blocked_html}
                    {direction_html}
                    {positions_html}
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            # Decisione normale su singolo asset
            # Renderizza setup_confirmations se presenti
            setup_conf_html = ''
            if setup_confirmations:
                setup_items = ''.join(f'<li>{html.escape(conf)}</li>' for conf in setup_confirmations)
                setup_conf_html = f'<div style="margin-top: 10px;"><strong style="color: #00ff9d;">✅ Setup Confirmations:</strong><ul style="margin: 5px 0; padding-left: 20px;">{setup_items}</ul></div>'
            
            # Renderizza blocked_by se presente
            blocked_html = ''
            if blocked_by:
                blocked_reasons = ', '.join(html.escape(str(b)) for b in blocked_by)
                blocked_html = f'<p><strong style="color: #ff6b6b;">🚫 Blocked By:</strong> {blocked_reasons}</p>'
            
            # Renderizza direction_considered se presente
            direction_html = ''
            if direction_considered and direction_considered != 'NONE':
                direction_color = '#00ff41' if direction_considered == 'LONG' else '#ff004c'
                direction_html = f'<p><strong style="color: #00d4ff;">🎯 Direction Considered:</strong> <span style="color: {direction_color};">{html.escape(direction_considered)}</span></p>'
            
            st.markdown(f"""
            <div class="ai-decision-card">
                <div class="decision-header">
                    <span class="decision-time">{timestamp}</span>
                    <span class="decision-action" style="color: {action_color}; text-shadow: 0 0 10px {action_color};">
                        {action_emoji} {action_text}
                    </span>
                    <span class="decision-symbol" style="color: #00d4ff; font-weight: 700;">{html.escape(symbol)}</span>
                </div>
                <div class="decision-reasoning">
                    <p><strong style="color: #00ff9d;">💡 Rationale:</strong> {rationale}</p>
                    {f'<p><strong style="color: #ff6b9d;">📊 Analysis:</strong> {analysis_summary}</p>' if analysis_summary else ''}
                    {direction_html}
                    {blocked_html}
                    {setup_conf_html}
                    {f'<p><strong style="color: #ffa500;">⚡ Leverage:</strong> {leverage}x | <strong style="color: #ffa500;">📈 Size:</strong> {size_pct*100:.1f}%</p>' if action in ['OPEN_LONG', 'OPEN_SHORT'] else ''}
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        # Expander per JSON completo
        with st.expander(f"📄 JSON Completo - {symbol}"):
            st.json(decision)

def add_manual_decision_input():
    """Input manuale per aggiungere decisioni AI (per test)"""
    with st.expander("➕ Aggiungi Decisione AI (Debug)"):
        col1, col2 = st.columns(2)
        with col1:
            symbol = st.text_input("Symbol", "BTCUSDT")
            action = st.selectbox("Action", ["BUY", "SELL", "HOLD"])
            confidence = st.slider("Confidence", 0.0, 1.0, 0.8)
        with col2:
            analysis = st.text_area("Analisi", "Trend rialzista confermato...")
            reasoning = st.text_area("Motivazione", "RSI oversold, supporto testato...")
        
        if st.button("💾 Salva Decisione"):
            from utils.data_manager import add_ai_decision
            add_ai_decision({
                'symbol': symbol,
                'action': action,
                'confidence': confidence,
                'analysis': analysis,
                'reasoning': reasoning
            })
            st.success("✅ Decisione salvata!")
            st.rerun()
