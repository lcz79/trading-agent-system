"""
Component per tracciare e visualizzare commissioni trading Bybit
"""
import streamlit as st
from datetime import datetime, timedelta, timezone
from typing import Dict
import sys
import os

# Aggiungi il path del dashboard per importare bybit_client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bybit_client import BybitClient


def safe_float(value, default=0.0):
    """Conversione sicura a float"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


@st.cache_data(ttl=3600)  # Cache 1 ora
def get_trading_fees() -> Dict[str, float]:
    """
    Recupera commissioni da Bybit analizzando le posizioni chiuse.
    Filtra solo trade dal 9 dicembre 2025 in poi.
    
    Returns:
        Dict con chiavi: today, week, month, total
    """
    try:
        client = BybitClient()
        
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        
        # Data minima filtro: 9 dicembre 2025
        min_date = datetime(2025, 12, 9, 0, 0, 0, tzinfo=timezone.utc)
        
        # Recupera closed PnL con fee breakdown - con filtro data
        all_trades = client.get_closed_pnl(limit=200, start_date=min_date)
        
        fees = {'today': 0.0, 'week': 0.0, 'month': 0.0, 'total': 0.0}
        
        for trade in all_trades:
            # Le commissioni sono nel campo closedPnl breakdown
            fee = 0.0
            
            # Prova a ottenere il fee da diversi campi possibili
            if 'exec_fee' in trade and trade['exec_fee'] is not None:
                fee = abs(safe_float(trade.get('exec_fee', 0)))
            elif 'fee' in trade and trade['fee'] is not None:
                fee = abs(safe_float(trade.get('fee', 0)))
            
            # Se non abbiamo fee esplicito, stimiamo basandoci sul valore della posizione
            # Bybit carica ~0.055% per maker e ~0.06% per taker (media ~0.0575%)
            if fee == 0.0:
                closed_pnl = safe_float(trade.get('Closed PnL', 0))
                # Stima molto conservativa: assumiamo fee dello 0.06% sul valore totale
                # (il closed PnL è solo la differenza, non il valore totale, quindi skippiamo)
                continue
            
            trade_time = datetime.fromtimestamp(trade.get('ts', 0) / 1000)
            
            fees['total'] += fee
            if trade_time >= month_start:
                fees['month'] += fee
            if trade_time >= week_start:
                fees['week'] += fee
            if trade_time >= today_start:
                fees['today'] += fee
        
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
        st.metric("Oggi", f"${fees['today']:.2f}")
    
    with col2:
        st.metric("Settimana", f"${fees['week']:.2f}")
    
    with col3:
        st.metric("Mese", f"${fees['month']:.2f}")
    
    with col4:
        st.metric("Totale", f"${fees['total']:.2f}")
