import streamlit as st
import json
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
            action_emoji = '⏸️'
            action_color = '#808080'
            action_text = 'HOLD'
        
        # Formatta timestamp
        timestamp = decision.get('timestamp', 'N/A')
        if timestamp != 'N/A':
            timestamp = timestamp[:19].replace('T', ' ')
        
        symbol = decision.get('symbol', 'N/A')
        rationale = decision.get('rationale', 'N/A')
        leverage = decision.get('leverage', 1)
        size_pct = decision.get('size_pct', 0)
        analysis_summary = decision.get('analysis_summary', '')
        
        st.markdown(f"""
        <div class="ai-decision-card">
            <div class="decision-header">
                <span class="decision-time">{timestamp}</span>
                <span class="decision-action" style="color: {action_color}; text-shadow: 0 0 10px {action_color};">
                    {action_emoji} {action_text}
                </span>
                <span class="decision-symbol" style="color: #00d4ff; font-weight: 700;">{symbol}</span>
            </div>
            <div class="decision-reasoning">
                <p><strong style="color: #00ff9d;">💡 Rationale:</strong> {rationale}</p>
                {f'<p><strong style="color: #ff6b9d;">📊 Analysis:</strong> {analysis_summary}</p>' if analysis_summary else ''}
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
