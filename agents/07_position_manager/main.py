import os
import ccxt
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

API_KEY = os.getenv('BYBIT_API_KEY')
API_SECRET = os.getenv('BYBIT_API_SECRET')
IS_TESTNET = os.getenv('BYBIT_TESTNET', 'true').lower() == 'true'

exchange = None
if API_KEY and API_SECRET:
    try:
        exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
        })
        if IS_TESTNET: exchange.set_sandbox_mode(True)
        print(f"🔌 Position Manager: Connesso a Bybit (Testnet: {IS_TESTNET})")
    except Exception as e: print(f"⚠️ Errore Connessione: {e}")

class OrderRequest(BaseModel):
    symbol: str
    side: str = "buy"
    leverage: float = 1.0
    size_pct: float = 0.0

class CloseRequest(BaseModel):
    symbol: str

def clean_symbol(s: str) -> str:
    """Converte 'BTC/USDT:USDT' in 'BTCUSDT'"""
    return s.split(':')[0].replace('/', '')

def fetch_active_positions_safe():
    if not exchange: return []
    try:
        # category='linear' è il segreto per vedere le posizioni USDT
        raw = exchange.fetch_positions(None, params={'category': 'linear'})
        active = []
        for p in raw:
            if float(p['contracts'] or 0) > 0:
                # Puliamo il nome qui per uniformità
                p['symbol'] = clean_symbol(p['symbol'])
                active.append(p)
                print(f"✅ ATTIVA: {p['symbol']} Size: {p['contracts']}")
        return active
    except Exception as e:
        print(f"❌ Errore fetch: {e}")
        return []

@app.get("/get_wallet_balance")
def get_balance():
    if not exchange: return {"equity": 0}
    try:
        bal = exchange.fetch_balance(params={'type': 'swap'})
        u = bal.get('USDT', {})
        return {"equity": u.get('total', 0), "available": u.get('free', 0)}
    except: return {"equity": 0}

@app.get("/get_open_positions")
def get_positions():
    active_list = fetch_active_positions_safe()
    symbols = [p['symbol'] for p in active_list]
    
    details = []
    for p in active_list:
        details.append({
            "symbol": p['symbol'],
            "side": p['side'],
            "size": float(p['contracts']),
            "entry_price": float(p['entryPrice']),
            "pnl": float(p['unrealizedPnl'] or 0),
            "leverage": p.get('leverage', 1)
        })
    return {"active": symbols, "details": details}

@app.post("/open_position")
def open_position(order: OrderRequest):
    if not exchange: return {"status": "simulated"}
    try:
        sym = order.symbol # Arriva già pulito come BTCUSDT
        # CCXT gestisce la conversione inversa se necessario, ma per sicurezza:
        # Su Bybit 'BTCUSDT' funziona per linear.
        exchange.set_leverage(int(order.leverage), sym)
        bal = exchange.fetch_balance(params={'type': 'swap'})['USDT']['free']
        qty = (bal * order.size_pct * order.leverage) / float(exchange.fetch_ticker(sym)['last'])
        res = exchange.create_order(sym, 'market', 'buy' if 'long' in order.side else 'sell', qty)
        return {"status": "executed", "id": res['id']}
    except Exception as e: return {"status": "error", "msg": str(e)}

@app.post("/close_position")
def close_position(req: CloseRequest):
    # Dummy function (Tanto abbiamo disabilitato l'auto-close nell'orchestrator)
    return {"status": "manual_only"}

@app.post("/manage_active_positions")
def manage(): return {"status": "ok"}
