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
    
    # Mostra le ultime 5 decisioni
    for decision in reversed(decisions[-5:]):
        action_color = "#00ff41" if decision.get('action') == 'BUY' else "#ff004c" if decision.get('action') == 'SELL' else "#ffaa00"
        
        st.markdown(f"""
        <div class="ai-decision-card">
            <div class="decision-header">
                <span class="decision-time">{decision.get('timestamp', 'N/A')[:19]}</span>
                <span class="decision-action" style="color: {action_color}">{decision.get('action', 'HOLD')}</span>
                <span class="decision-symbol">{decision.get('symbol', 'N/A')}</span>
            </div>
            <div class="decision-reasoning">
                <p><strong>📊 Analisi:</strong> {decision.get('analysis', 'N/A')}</p>
                <p><strong>💡 Motivazione:</strong> {decision.get('reasoning', 'N/A')}</p>
                <p><strong>🎯 Confidenza:</strong> {decision.get('confidence', 0)*100:.0f}%</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Expander per JSON completo
        with st.expander(f"📄 JSON Completo - {decision.get('symbol', 'N/A')}"):
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
