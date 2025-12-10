import json
import os
from datetime import datetime
from config import DATA_DIR, EQUITY_HISTORY_FILE, CLOSED_POSITIONS_FILE, AI_DECISIONS_FILE, STARTING_DATE, STARTING_BALANCE, SHARED_DATA_DIR

def ensure_data_dir():
    """Crea la directory data se non esiste"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def ensure_shared_data_dir():
    """Assicura che la directory shared data esista (per sviluppo locale)"""
    if not os.path.exists(SHARED_DATA_DIR):
        try:
            os.makedirs(SHARED_DATA_DIR)
        except:
            pass  # In Docker, la directory esiste già come volume mount

def load_json(filepath, default=None):
    """Carica un file JSON"""
    ensure_data_dir()
    ensure_shared_data_dir()
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except:
            return default if default else []
    return default if default else []

def save_json(filepath, data):
    """Salva dati in un file JSON"""
    ensure_data_dir()
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, default=str)

def get_equity_history():
    """Ottiene lo storico dell'equity"""
    history = load_json(EQUITY_HISTORY_FILE, [])
    
    # Aggiungi il punto di partenza se la lista è vuota
    if not history:
        history = [{
            'timestamp': f"{STARTING_DATE}T00:00:00",
            'equity': STARTING_BALANCE,
            'available': STARTING_BALANCE,
            'unrealized_pnl': 0
        }]
        save_json(EQUITY_HISTORY_FILE, history)
    
    return history

def add_equity_snapshot(wallet_data):
    """Aggiunge uno snapshot dell'equity"""
    if not wallet_data:
        return
    
    history = load_json(EQUITY_HISTORY_FILE, [])
    
    # Evita duplicati troppo ravvicinati (minimo 1 minuto)
    if history:
        last_time = datetime.fromisoformat(history[-1]['timestamp']. replace('Z', ''))
        now = datetime.now()
        if (now - last_time).seconds < 60:
            return
    
    snapshot = {
        'timestamp': datetime.now().isoformat(),
        'equity': wallet_data.get('equity', 0),
        'available': wallet_data.get('available', 0),
        'unrealized_pnl': wallet_data. get('unrealized_pnl', 0)
    }
    
    history.append(snapshot)
    
    # Mantieni solo gli ultimi 30 giorni di dati
    if len(history) > 50000:
        history = history[-50000:]
    
    save_json(EQUITY_HISTORY_FILE, history)

def get_closed_positions_history():
    """Ottiene lo storico delle posizioni chiuse (ultime 10)"""
    return load_json(CLOSED_POSITIONS_FILE, [])[-10:]

def update_closed_positions(new_positions):
    """Aggiorna lo storico delle posizioni chiuse"""
    if not new_positions:
        return
    
    existing = load_json(CLOSED_POSITIONS_FILE, [])
    existing_ids = set(f"{p['symbol']}_{p. get('updated_time', '')}" for p in existing)
    
    for pos in new_positions:
        pos_id = f"{pos['symbol']}_{pos.get('updated_time', '')}"
        if pos_id not in existing_ids:
            existing.append(pos)
    
    # Mantieni solo le ultime 100
    existing = existing[-100:]
    save_json(CLOSED_POSITIONS_FILE, existing)

def get_ai_decisions():
    """Ottiene le decisioni dell'AI"""
    return load_json(AI_DECISIONS_FILE, [])

def add_ai_decision(decision_data):
    """Aggiunge una decisione AI"""
    decisions = load_json(AI_DECISIONS_FILE, [])
    decisions.append({
        'timestamp': datetime.now().isoformat(),
        **decision_data
    })
    # Mantieni solo le ultime 50
    decisions = decisions[-50:]
    save_json(AI_DECISIONS_FILE, decisions)
