from datetime import datetime
from config import STARTING_BALANCE, STARTING_DATE

def calculate_performance(current_equity, starting_balance=STARTING_BALANCE):
    """Calcola le metriche di performance"""
    profit_loss = current_equity - starting_balance
    profit_loss_pct = ((current_equity / starting_balance) - 1) * 100 if starting_balance > 0 else 0
    
    return {
        'current_equity': current_equity,
        'starting_balance': starting_balance,
        'profit_loss': profit_loss,
        'profit_loss_pct': profit_loss_pct,
        'starting_date': STARTING_DATE
    }

def calculate_daily_stats(equity_history):
    """Calcola statistiche giornaliere"""
    if len(equity_history) < 2:
        return {'daily_change': 0, 'daily_change_pct': 0}
    
    today = datetime.now(). date()
    today_data = [e for e in equity_history if datetime.fromisoformat(e['timestamp']. replace('Z', '')).date() == today]
    
    if today_data:
        first_today = today_data[0]['equity']
        last_today = today_data[-1]['equity']
        daily_change = last_today - first_today
        daily_change_pct = ((last_today / first_today) - 1) * 100 if first_today > 0 else 0
        return {'daily_change': daily_change, 'daily_change_pct': daily_change_pct}
    
    return {'daily_change': 0, 'daily_change_pct': 0}

def calculate_max_drawdown(equity_history):
    """Calcola il maximum drawdown"""
    if len(equity_history) < 2:
        return 0
    
    equities = [e['equity'] for e in equity_history]
    peak = equities[0]
    max_dd = 0
    
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    
    return max_dd
