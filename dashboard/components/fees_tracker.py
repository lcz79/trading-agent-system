"""
Component per tracciare e visualizzare commissioni trading Bybit
"""
import streamlit as st
from typing import Dict
import sys
import os

# Aggiungi il path del dashboard per importare bybit_client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bybit_client import BybitClient


@st.cache_data(ttl=3600)  # Cache 1 ora
def get_trading_fees() -> Dict[str, float]:
    """
    Recupera commissioni da Bybit usando l'API executions.
    Filtra solo trade dal 9 dicembre 2025 in poi.
    
    Returns:
        Dict con chiavi: today, week, month, total
    """
    try:
        client = BybitClient()
        
        # Chiama il nuovo metodo che usa l'API executions
        fees = client.get_execution_fees()
        
        return fees
    except Exception as e:
        print(f"Error retrieving fees: {e}")
        return {'today': 0.0, 'week': 0.0, 'month': 0.0, 'total': 0.0}


def render_fees_section():
    """Renderizza la sezione commissioni trading"""
    st.markdown('<div class="section-title">💰 Commissioni Trading Bybit</div>', unsafe_allow_html=True)
    
    fees = get_trading_fees()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Oggi", f"${fees['today']:.4f}")
    
    with col2:
        st.metric("Settimana", f"${fees['week']:.4f}")
    
    with col3:
        st.metric("Mese", f"${fees['month']:.4f}")
    
    with col4:
        st.metric("Totale", f"${fees['total']:.4f}")
