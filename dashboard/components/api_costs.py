"""
Component per tracciare e visualizzare costi API DeepSeek
"""
import streamlit as st
import json
import os
from datetime import datetime, timedelta
from typing import Dict

# NEW
from utils.reset_manager import get_reset_date_iso


# Path del file di log dei costi API
# Nota: Il volume shared_data è montato in /data/ per tutti i containers
API_COSTS_FILE = "/data/api_costs.json"

# DeepSeek pricing (basato su pricing pubblico DeepSeek)
DEEPSEEK_INPUT_COST = 0.14 / 1_000_000  # $0.14 per 1M tokens input
DEEPSEEK_OUTPUT_COST = 0.28 / 1_000_000  # $0.28 per 1M tokens output


def load_api_costs():
    """Carica i dati dei costi API dal file JSON"""
    if os.path.exists(API_COSTS_FILE):
        try:
            with open(API_COSTS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading API costs: {e}")
            return {'calls': []}
    return {'calls': []}



def _parse_iso(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.fromisoformat(ts.replace("Z", ""))
        except Exception:
            return None

@st.cache_data(ttl=3600)  # Cache 1 ora
def calculate_api_costs() -> Dict[str, Dict[str, float]]:
    """
    Calcola i costi API aggregati per periodo.
    
    Returns:
        Dict con struttura:
        {
            'today': {'cost': float, 'calls': int},
            'week': {'cost': float, 'calls': int},
            'month': {'cost': float, 'calls': int},
            'total': {'cost': float, 'calls': int}
        }
    """
    data = load_api_costs()
    calls = data.get('calls', [])
    
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    reset_iso = get_reset_date_iso()
    reset_dt = _parse_iso(reset_iso)
    if reset_dt:
        # clamp: i periodi non possono iniziare prima del reset
        base = reset_dt.replace(tzinfo=None) if reset_dt.tzinfo else reset_dt
        today_start = max(today_start, base)
        week_start = max(week_start, base)
        month_start = max(month_start, base)
    
    costs = {
        'today': {'cost': 0.0, 'calls': 0},
        'week': {'cost': 0.0, 'calls': 0},
        'month': {'cost': 0.0, 'calls': 0},
        'total': {'cost': 0.0, 'calls': 0}
    }
    
    for call in calls:
        try:
            call_time = _parse_iso(call['timestamp'])
            if not call_time:
                continue

            # baseline filter: prima del reset NON conta mai
            if reset_dt and call_time < reset_dt:
                continue
            cost = (call['tokens_in'] * DEEPSEEK_INPUT_COST + 
                    call['tokens_out'] * DEEPSEEK_OUTPUT_COST)
            
            costs['total']['cost'] += cost
            costs['total']['calls'] += 1
            
            if call_time >= month_start:
                costs['month']['cost'] += cost
                costs['month']['calls'] += 1
            if call_time >= week_start:
                costs['week']['cost'] += cost
                costs['week']['calls'] += 1
            if call_time >= today_start:
                costs['today']['cost'] += cost
                costs['today']['calls'] += 1
        except Exception as e:
            print(f"Error processing API call: {e}")
            continue
    
    return costs


def render_api_costs_section():
    """Renderizza la sezione costi API DeepSeek"""
    st.markdown('<div class="section-title">🤖 Costi API DeepSeek</div>', unsafe_allow_html=True)
    
    costs = calculate_api_costs()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Oggi", 
            f"€{costs['today']['cost']:.4f}",
            f"{costs['today']['calls']} chiamate"
        )
    
    with col2:
        st.metric(
            "Settimana", 
            f"€{costs['week']['cost']:.4f}",
            f"{costs['week']['calls']} chiamate"
        )
    
    with col3:
        st.metric(
            "Mese", 
            f"€{costs['month']['cost']:.4f}",
            f"{costs['month']['calls']} chiamate"
        )
    
    with col4:
        st.metric(
            "Totale (da reset)", 
            f"€{costs['total']['cost']:.4f}",
            f"{costs['total']['calls']} chiamate"
        )
