import os
import ccxt
import json
import time
import math
import sqlite3
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from fastapi import FastAPI
from pydantic import BaseModel
from threading import Thread, Lock

app = FastAPI()

# --- CONFIGURAZIONE ---
HISTORY_FILE = "equity_history.json"
DB_PATH = os.getenv('DB_PATH', './data/trading_history.db')
DATA_DIR = './data'  # Default data directory for database files
API_KEY = os.getenv('BYBIT_API_KEY')
API_SECRET = os.getenv('BYBIT_API_SECRET')
IS_TESTNET = os.getenv('BYBIT_TESTNET', 'false').lower() == 'true'

# --- PARAMETRI TRAILING STOP ---
TRAILING_ACTIVATION_PCT = 0.018  # Attiva se profitto > 1.8%
TRAILING_DISTANCE_PCT = 0.010    # Mantieni stop a 1% di distanza
DEFAULT_INITIAL_SL_PCT = 0.04    # Stop Loss Iniziale
MONITOR_INTERVAL = int(os.getenv('MONITOR_INTERVAL', '60'))  # 60 seconds

file_lock = Lock()
db_lock = Lock()

# --- DATABASE INITIALIZATION ---
def init_database():
    """Initialize SQLite database for closed positions tracking"""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    elif not db_dir:
        # If DB_PATH has no directory component, ensure data directory exists
        os.makedirs(DATA_DIR, exist_ok=True)
    
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create closed_positions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS closed_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                size REAL NOT NULL,
                leverage REAL NOT NULL,
                pnl REAL NOT NULL,
                pnl_percentage REAL NOT NULL,
                duration_seconds INTEGER,
                open_time TEXT NOT NULL,
                close_time TEXT NOT NULL,
                close_reason TEXT,
                was_reversed BOOLEAN DEFAULT 0,
                strategy_used TEXT,
                market_conditions TEXT
            )
        ''')
        
        # Create index for faster queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_symbol_close_time 
            ON closed_positions(symbol, close_time)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_pnl 
            ON closed_positions(pnl)
        ''')
        
        conn.commit()
        conn.close()
        print(f"✅ Database initialized at {DB_PATH}")

def save_closed_position(position_data):
    """Save closed position to database"""
    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO closed_positions 
                (symbol, side, entry_price, exit_price, size, leverage, pnl, pnl_percentage,
                 duration_seconds, open_time, close_time, close_reason, was_reversed, 
                 strategy_used, market_conditions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                position_data.get('symbol'),
                position_data.get('side'),
                position_data.get('entry_price'),
                position_data.get('exit_price'),
                position_data.get('size'),
                position_data.get('leverage'),
                position_data.get('pnl'),
                position_data.get('pnl_percentage'),
                position_data.get('duration_seconds'),
                position_data.get('open_time'),
                position_data.get('close_time'),
                position_data.get('close_reason'),
                position_data.get('was_reversed', False),
                position_data.get('strategy_used'),
                position_data.get('market_conditions')
            ))
            
            conn.commit()
            conn.close()
            print(f"✅ Saved closed position to DB: {position_data.get('symbol')} PnL: {position_data.get('pnl')}")
        except Exception as e:
            print(f"❌ Error saving to database: {e}")

# Initialize database on startup
init_database()

# Management logs storage
management_logs = []
management_logs_lock = Lock()

exchange = None
if API_KEY and API_SECRET:
    try:
        exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'options': {
                'defaultType': 'swap',
                'adjustForTimeDifference': True
            }
        })
        if IS_TESTNET:
            exchange.set_sandbox_mode(True)
        exchange.load_markets()
        print(f"🔌 Position Manager: Connesso (Testnet: {IS_TESTNET})")
    except Exception as e:
        print(f"⚠️ Errore Connessione: {e}")

# --- MEMORY ---
def load_json(f, d=[]):
    with file_lock:
        if os.path.exists(f):
            try:
                with open(f, 'r') as file: return json.load(file)
            except: return d
        return d

def save_json(f, d):
    with file_lock:
        try:
            with open(f, 'w') as file: json.dump(d, file, indent=2)
        except: pass

def record_equity_loop():
    """Record equity every 60 seconds and monitor positions"""
    while True:
        if exchange:
            try:
                bal = exchange.fetch_balance(params={'type': 'swap'})
                usdt = bal.get('USDT', {})
                real_bal = float(usdt.get('total', 0))
                pos = exchange.fetch_positions(None, params={'category': 'linear'})
                upnl = sum([float(p.get('unrealizedPnl') or 0) for p in pos])

                hist = load_json(HISTORY_FILE)
                hist.append({
                    "timestamp": datetime.now().isoformat(),
                    "real_balance": real_bal,
                    "live_equity": real_bal + upnl
                })
                if len(hist) > 4000: hist = hist[-4000:]
                save_json(HISTORY_FILE, hist)
                
                # Update trailing stops every cycle
                check_and_update_trailing_stops()
                
            except Exception as e:
                print(f"⚠️ Equity recording error: {e}")
        time.sleep(MONITOR_INTERVAL)  # 60 seconds by default

Thread(target=record_equity_loop, daemon=True).start()

# --- MODELLI ---
class OrderRequest(BaseModel):
    symbol: str
    side: str = "buy"
    leverage: float = 1.0
    size_pct: float = 0.0
    sl_pct: float = 0.0 

class CloseRequest(BaseModel):
    symbol: str

# --- TRAILING LOGIC (FIXED) ---
def check_and_update_trailing_stops():
    if not exchange: return

    try:
        positions = exchange.fetch_positions(None, params={'category': 'linear'})

        for p in positions:
            qty = float(p.get('contracts') or 0)
            if qty == 0: continue

            symbol = p['symbol'] 
            
            # Ottieni ID di mercato per chiamate RAW
            try:
                market_id = exchange.market(symbol)['id']
            except:
                market_id = symbol.replace('/', '').split(':')[0]

            side_raw = (p.get('side') or '').lower()
            is_long = side_raw in ['long', 'buy']
            
            entry_price = float(p['entryPrice'])
            mark_price = float(p['markPrice'])
            sl_current = float(p.get('stopLoss') or 0)

            # 1) ROI in %
            if is_long:
                roi_pct = (mark_price - entry_price) / entry_price
            else:
                roi_pct = (entry_price - mark_price) / entry_price

            # 2) Attivazione trailing
            if roi_pct >= TRAILING_ACTIVATION_PCT:
                new_sl_price = None

                if is_long:
                    target_sl = mark_price * (1 - TRAILING_DISTANCE_PCT)
                    if sl_current == 0 or target_sl > sl_current:
                        new_sl_price = target_sl
                else:
                    target_sl = mark_price * (1 + TRAILING_DISTANCE_PCT)
                    if sl_current == 0 or target_sl < sl_current:
                        new_sl_price = target_sl

                if new_sl_price:
                    price_str = exchange.price_to_precision(symbol, new_sl_price)

                    print(f"🏃 TRAILING STOP {symbol} ROI={roi_pct*100:.2f}% SL {sl_current} -> {price_str}")

                    # --- FIX: CHIAMATA DIRETTA V5 ---
                    try:
                        req = {
                            "category": "linear",
                            "symbol": market_id,
                            "stopLoss": price_str,
                            "positionIdx": 0
                        }
                        exchange.private_post_v5_position_trading_stop(req)
                        print("✅ SL Aggiornato con successo su Bybit")
                    except Exception as api_err:
                        print(f"❌ Errore API Bybit: {api_err}")

    except Exception as e:
        print(f"⚠️ Trailing logic error: {e}")

# --- API ENDPOINTS ---
@app.get("/get_wallet_balance")
def get_balance():
    if not exchange: return {"equity": 0, "available": 0}
    try:
        bal = exchange.fetch_balance(params={'type': 'swap'})
        u = bal.get('USDT', {})
        return {"equity": float(u.get('total', 0)), "available": float(u.get('free', 0))}
    except: return {"equity": 0, "available": 0}

@app.get("/get_open_positions")
def get_positions():
    if not exchange: return {"active": [], "details": []}
    try:
        raw = exchange.fetch_positions(None, params={'category': 'linear'})
        active = []
        details = []
        for p in raw:
            if float(p.get('contracts') or 0) > 0:
                sym = p['symbol'].split(':')[0].replace('/', '')
                details.append({
                    "symbol": sym,
                    "side": p.get('side'),
                    "size": float(p['contracts']),
                    "entry_price": float(p['entryPrice']),
                    "mark_price": float(p.get('markPrice', p['entryPrice'])),
                    "pnl": float(p.get('unrealizedPnl') or 0),
                    "leverage": p.get('leverage', 1)
                })
                active.append(sym)
        return {"active": active, "details": details}
    except: return {"active": [], "details": []}

@app.get("/get_history")
def get_hist(): return load_json(HISTORY_FILE)

@app.get("/get_closed_positions")
def get_closed():
    """Get closed positions from database"""
    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT symbol, side, entry_price, exit_price, size, leverage, 
                       pnl, pnl_percentage, close_time, close_reason, was_reversed
                FROM closed_positions
                ORDER BY close_time DESC
                LIMIT 50
            ''')
            
            rows = cursor.fetchall()
            conn.close()
            
            result = []
            for row in rows:
                result.append({
                    'symbol': row[0],
                    'side': row[1],
                    'entry_price': row[2],
                    'exit_price': row[3],
                    'size': row[4],
                    'leverage': row[5],
                    'pnl': row[6],
                    'pnl_percentage': row[7],
                    'close_time': row[8],
                    'close_reason': row[9],
                    'was_reversed': row[10]
                })
            
            return result
        except Exception as e:
            print(f"❌ Error fetching closed positions: {e}")
            return []

def add_management_log(pair, action):
    """Add log entry for management actions"""
    with management_logs_lock:
        management_logs.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "pair": pair,
            "action": action
        })
        # Keep only last 100 logs
        if len(management_logs) > 100:
            management_logs.pop(0)

@app.get("/management_logs")
def get_management_logs():
    """Get position management logs"""
    with management_logs_lock:
        return list(management_logs)

@app.post("/open_position")
def open_position(order: OrderRequest):
    if not exchange: return {"status": "error", "msg": "No Exchange"}

    try:
        raw_sym = order.symbol
        target_market = None
        for m in exchange.markets.values():
            if m.get('id') == raw_sym and m.get('linear', False):
                target_market = m
                break
        if not target_market: target_market = exchange.market(raw_sym)
        sym = target_market['symbol']
        
        # 1. Leva
        try: exchange.set_leverage(int(order.leverage), sym, params={'category': 'linear'})
        except: pass

        # 2. Soldi
        bal = float(exchange.fetch_balance(params={'type': 'swap'})['USDT']['free'])
        cost = max(bal * order.size_pct, 10.0)
        price = float(exchange.fetch_ticker(sym)['last'])

        # 3. Quantità
        info = target_market.get('info', {}) or {}
        lot_filter = info.get('lotSizeFilter', {}) or {}
        qty_step = float(lot_filter.get('qtyStep') or target_market['limits']['amount']['min'] or 0.001)
        min_qty = float(lot_filter.get('minOrderQty') or qty_step)

        qty_raw = (cost * order.leverage) / price
        d_qty = Decimal(str(qty_raw))
        d_step = Decimal(str(qty_step))
        steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
        final_qty_d = steps * d_step
        
        if final_qty_d < Decimal(str(min_qty)): final_qty_d = Decimal(str(min_qty))
        final_qty = float("{:f}".format(final_qty_d.normalize()))

        # 4. SL Iniziale
        sl_pct = order.sl_pct if order.sl_pct > 0 else DEFAULT_INITIAL_SL_PCT
        is_long = 'buy' in order.side.lower() or 'long' in order.side.lower()
        side = 'buy' if is_long else 'sell'
        
        sl_price = price * (1 - sl_pct) if is_long else price * (1 + sl_pct)
        sl_str = exchange.price_to_precision(sym, sl_price)

        print(f"🚀 ORDER {sym}: Qty={final_qty} | SL={sl_str}")

        res = exchange.create_order(
            sym, 'market', side, final_qty, 
            params={'category': 'linear', 'stopLoss': sl_str}
        )
        
        add_management_log(sym, f"OPENED {side.upper()} position - Size: {final_qty} - Leverage: {order.leverage}x")

        return {"status": "executed", "id": res['id']}

    except Exception as e:
        print(f"❌ Order Error: {e}")
        return {"status": "error", "msg": str(e)}

class ReverseRequest(BaseModel):
    symbol: str
    current_side: str  # Current losing position side
    loss_amount: float
    recovery_multiplier: float = 1.5
    leverage: float = 5.0

@app.post("/reverse_position")
def reverse_position(req: ReverseRequest):
    """Close losing position and open opposite position with increased size for recovery"""
    if not exchange: 
        return {"status": "error", "msg": "No Exchange"}
    
    try:
        raw_sym = req.symbol
        target_market = None
        for m in exchange.markets.values():
            if m.get('id') == raw_sym and m.get('linear', False):
                target_market = m
                break
        if not target_market: 
            target_market = exchange.market(raw_sym)
        sym = target_market['symbol']
        
        # 1. Close current losing position
        positions = exchange.fetch_positions([sym], params={'category': 'linear'})
        current_position = None
        
        for p in positions:
            if float(p.get('contracts') or 0) > 0:
                current_position = p
                break
        
        if not current_position:
            return {"status": "error", "msg": "No position found to reverse"}
        
        # Get position details for database
        entry_price = float(current_position['entryPrice'])
        current_price = float(current_position['markPrice'])
        size = float(current_position['contracts'])
        leverage = float(current_position.get('leverage', 1))
        pnl = float(current_position.get('unrealizedPnl') or 0)
        open_time_ts = current_position.get('timestamp', 0)
        
        # Calculate PnL percentage
        pnl_pct = (pnl / (entry_price * size / leverage)) * 100 if leverage > 0 else 0
        
        # Close the position
        close_side = 'sell' if req.current_side.lower() in ['buy', 'long'] else 'buy'
        close_order = exchange.create_order(
            sym, 'market', close_side, size,
            params={'category': 'linear', 'reduceOnly': True}
        )
        
        print(f"🔄 CLOSED losing {req.current_side} position on {sym} - PnL: ${pnl:.2f}")
        
        # Save to database
        close_time = datetime.now()
        # Note: open_time_ts from Bybit is in milliseconds, so we divide by 1000
        open_time_seconds = open_time_ts / 1000 if open_time_ts else 0
        duration_seconds = int((close_time.timestamp() - open_time_seconds)) if open_time_seconds else 0
        
        save_closed_position({
            'symbol': raw_sym,
            'side': req.current_side,
            'entry_price': entry_price,
            'exit_price': current_price,
            'size': size,
            'leverage': leverage,
            'pnl': pnl,
            'pnl_percentage': pnl_pct,
            'duration_seconds': duration_seconds,
            'open_time': datetime.fromtimestamp(open_time_seconds).isoformat() if open_time_seconds else close_time.isoformat(),
            'close_time': close_time.isoformat(),
            'close_reason': 'REVERSE_STRATEGY',
            'was_reversed': True,
            'strategy_used': 'Loss Recovery Reverse',
            'market_conditions': f"Loss: ${abs(pnl):.2f}"
        })
        
        add_management_log(raw_sym, f"CLOSED losing position - PnL: ${pnl:.2f} - Reason: REVERSE")
        
        # 2. Calculate new position size with recovery multiplier
        bal = float(exchange.fetch_balance(params={'type': 'swap'})['USDT']['free'])
        
        # Base cost + additional amount to recover loss
        loss_recovery_amount = abs(req.loss_amount) * req.recovery_multiplier
        base_cost = bal * 0.15  # 15% base
        total_cost = min(base_cost + loss_recovery_amount, bal * 0.30)  # Cap at 30%
        
        current_price = float(exchange.fetch_ticker(sym)['last'])
        
        # 3. Set leverage
        try: 
            exchange.set_leverage(int(req.leverage), sym, params={'category': 'linear'})
        except: 
            pass
        
        # 4. Calculate quantity
        info = target_market.get('info', {}) or {}
        lot_filter = info.get('lotSizeFilter', {}) or {}
        qty_step = float(lot_filter.get('qtyStep') or target_market['limits']['amount']['min'] or 0.001)
        min_qty = float(lot_filter.get('minOrderQty') or qty_step)
        
        qty_raw = (total_cost * req.leverage) / current_price
        d_qty = Decimal(str(qty_raw))
        d_step = Decimal(str(qty_step))
        steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
        final_qty_d = steps * d_step
        
        if final_qty_d < Decimal(str(min_qty)): 
            final_qty_d = Decimal(str(min_qty))
        final_qty = float("{:f}".format(final_qty_d.normalize()))
        
        # 5. Open REVERSE position (opposite side)
        new_side = 'buy' if req.current_side.lower() in ['sell', 'short'] else 'sell'
        
        # Set stop loss
        sl_price = current_price * (1 - DEFAULT_INITIAL_SL_PCT) if new_side == 'buy' else current_price * (1 + DEFAULT_INITIAL_SL_PCT)
        sl_str = exchange.price_to_precision(sym, sl_price)
        
        print(f"🔄 OPENING REVERSE {new_side.upper()} position - Qty: {final_qty} - Recovery Mult: {req.recovery_multiplier}x")
        
        reverse_order = exchange.create_order(
            sym, 'market', new_side, final_qty,
            params={'category': 'linear', 'stopLoss': sl_str}
        )
        
        add_management_log(raw_sym, f"OPENED REVERSE {new_side.upper()} - Size: {final_qty} - Recovery: {req.recovery_multiplier}x - Target: ${abs(pnl):.2f}")
        
        return {
            "status": "executed",
            "close_order_id": close_order['id'],
            "reverse_order_id": reverse_order['id'],
            "closed_pnl": pnl,
            "new_size": final_qty,
            "recovery_target": abs(pnl)
        }
        
    except Exception as e:
        print(f"❌ Reverse Position Error: {e}")
        return {"status": "error", "msg": str(e)}

@app.post("/close_position")
def close_position(req: CloseRequest):
    """Close position and save to database"""
    if not exchange:
        return {"status": "error", "msg": "No Exchange"}
    
    try:
        raw_sym = req.symbol
        target_market = None
        for m in exchange.markets.values():
            if m.get('id') == raw_sym and m.get('linear', False):
                target_market = m
                break
        if not target_market:
            target_market = exchange.market(raw_sym)
        sym = target_market['symbol']
        
        # Get position details before closing
        positions = exchange.fetch_positions([sym], params={'category': 'linear'})
        current_position = None
        
        for p in positions:
            if float(p.get('contracts') or 0) > 0:
                current_position = p
                break
        
        if not current_position:
            return {"status": "error", "msg": "No position found"}
        
        # Extract details
        side = current_position.get('side', '').lower()
        entry_price = float(current_position['entryPrice'])
        current_price = float(current_position['markPrice'])
        size = float(current_position['contracts'])
        leverage = float(current_position.get('leverage', 1))
        pnl = float(current_position.get('unrealizedPnl') or 0)
        open_time_ts = current_position.get('timestamp', 0)
        
        # Calculate PnL percentage
        pnl_pct = (pnl / (entry_price * size / leverage)) * 100 if leverage > 0 else 0
        
        # Close order
        close_side = 'sell' if side in ['buy', 'long'] else 'buy'
        result = exchange.create_order(
            sym, 'market', close_side, size,
            params={'category': 'linear', 'reduceOnly': True}
        )
        
        # Save to database
        close_time = datetime.now()
        # Note: open_time_ts from Bybit is in milliseconds, so we divide by 1000
        open_time_seconds = open_time_ts / 1000 if open_time_ts else 0
        duration_seconds = int((close_time.timestamp() - open_time_seconds)) if open_time_seconds else 0
        
        save_closed_position({
            'symbol': raw_sym,
            'side': side,
            'entry_price': entry_price,
            'exit_price': current_price,
            'size': size,
            'leverage': leverage,
            'pnl': pnl,
            'pnl_percentage': pnl_pct,
            'duration_seconds': duration_seconds,
            'open_time': datetime.fromtimestamp(open_time_seconds).isoformat() if open_time_seconds else close_time.isoformat(),
            'close_time': close_time.isoformat(),
            'close_reason': 'MANUAL_CLOSE',
            'was_reversed': False,
            'strategy_used': 'Standard',
            'market_conditions': 'N/A'
        })
        
        add_management_log(raw_sym, f"CLOSED position - PnL: ${pnl:.2f}")
        
        return {"status": "executed", "id": result['id'], "pnl": pnl}
        
    except Exception as e:
        print(f"❌ Close Position Error: {e}")
        return {"status": "error", "msg": str(e)}

@app.post("/manage_active_positions")
def manage():
    check_and_update_trailing_stops()
    return {"status": "ok"}
