import time
import schedule
import requests
import os
import math
from pybit.unified_trading import HTTP

# --- CONFIG ---
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
]
QTY_USDT = 50
LEVERAGE = 5

# --- URL DEGLI AGENTI ---
URL_BRAIN = "http://master-ai-agent:8000/decide"
URL_TECH = "http://technical-analyzer-agent:8000/analyze_multi_tf"
URL_FIB = "http://fibonacci-cyclical-agent:8000/analyze_fibonacci"
URL_GANN = "http://gann-analyzer-agent:8000/analyze_gann"
URL_MGMT = "http://position-manager-agent:8000/manage"

session = HTTP(testnet=False, api_key=os.getenv("BYBIT_API_KEY"), api_secret=os.getenv("BYBIT_API_SECRET"))
instrument_rules_cache = {}

def get_instrument_rules(symbol):
    if symbol in instrument_rules_cache:
        return instrument_rules_cache[symbol]
    try:
        response = session.get_instruments_info(category="linear", symbol=symbol)
        if response['retCode'] == 0 and response['result']['list']:
            rules = response['result']['list'][0]['lotSizeFilter']
            instrument_rules_cache[symbol] = rules
            return rules
    except Exception as e:
        print(f"   -> ⚠️ Impossibile ottenere le regole per {symbol}: {e}")
    return None

def get_data(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=40)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"   -> [ORCHESTRATOR] Avviso: l'agente su {url} non ha risposto. {e}")
        return {}
    return {}

def execute_trade(setup, symbol):
    # ... (Questa funzione rimane quasi identica, la copia per intero per sicurezza)
    if not setup:
        print(f"   -> ❌ Errore: setup nullo per {symbol}.")
        return
    try:
        action = setup.get('decision')
        trade_details = setup.get('trade_setup') or {}
        if not isinstance(trade_details, dict): trade_details = {}

        side = "Buy" if action == "OPEN_LONG" else "Sell"
        entry = trade_details.get('entry_price')
        sl = trade_details.get('stop_loss')
        tp = trade_details.get('take_profit')
        
        if not all([action, side, entry, sl, tp]):
            print(f"   -> ❌ Errore: setup di trade incompleto per {symbol}: {setup}")
            return

        rules = get_instrument_rules(symbol)
        if not rules:
            print(f"   -> ❌ Errore: impossibile procedere senza le regole di trading per {symbol}.")
            return

        qty_step = float(rules.get('qtyStep', '0.001'))
        budget = QTY_USDT * trade_details.get('size_pct', 0.5)
        raw_qty = (budget * LEVERAGE) / entry
        
        precision = int(-math.log10(qty_step)) if qty_step < 1 else 0
        qty = math.floor(raw_qty / qty_step) * qty_step
        final_qty_str = f"{qty:.{precision}f}"

        print(f"   -> 🚀 ESECUZIONE ORDINE: {side} {final_qty_str} {symbol} @ {entry} | SL: {sl} | TP: {tp}")
        
        # --- MODIFICA CHIAVE: Gestione Errore Leva ---
        try:
            session.set_leverage(category="linear", symbol=symbol, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))
        except Exception as e:
            # Se l'errore è 'leverage not modified', lo ignoriamo e andiamo avanti.
            if "110043" in str(e):
                print(f"      - Info: leva per {symbol} già impostata a {LEVERAGE}x. Si procede.")
            else:
                # Se è un altro errore, lo segnaliamo ma proviamo comunque a piazzare l'ordine.
                print(f"      - Avviso durante impostazione leva: {e}")

        session.place_order(
            category="linear", symbol=symbol, side=side, orderType="Limit",
            qty=final_qty_str, price=str(entry), timeInForce="GTC",
            stopLoss=str(sl), takeProfit=str(tp),
            slTriggerBy="LastPrice", tpTriggerBy="LastPrice"
        )
        print(f"   -> ✅ Ordine per {symbol} inviato con successo a Bybit.")
    except Exception as e:
        print(f"   -> ❌ Errore esecuzione ordine per {symbol}: {e}")

# --- FUNZIONE JOB MIGLIORATA V4 ---
def job():
    print(f"\n--- 🕒 {time.strftime('%Y-%m-%d %H:%M:%S')} | INIZIO CICLO DI SCANSIONE MERCATO ---")
    
    # --- MODIFICA CHIAVE: Controllo Posizioni Aperte ---
    open_positions = []
    try:
        positions_response = session.get_positions(category="linear", settleCoin="USDT")
        if positions_response['retCode'] == 0 and 'list' in positions_response['result']:
            # Creiamo una lista semplice con solo i simboli delle posizioni aperte (con size > 0)
            open_positions = [p['symbol'] for p in positions_response['result']['list'] if float(p.get('size', 0)) > 0]
            if open_positions:
                print(f"ℹ️ Posizioni attualmente aperte: {', '.join(open_positions)}")
    except Exception as e:
        print(f"   -> ⚠️ Impossibile recuperare le posizioni aperte: {e}")

    for symbol in SYMBOLS:
        # --- MODIFICA CHIAVE: Salta l'analisi se c'è già una posizione ---
        if symbol in open_positions:
            print(f"\n--- 🚫 Analisi per {symbol} saltata: posizione già aperta. ---")
            continue

        print(f"\n--- Analizzando {symbol} ---")
        print(f"1. Raccolta Dati per {symbol}...")
        tech = get_data(URL_TECH, {"symbol": symbol})
        fib = get_data(URL_FIB, {"crypto_symbol": symbol})
        gann = get_data(URL_GANN, {"symbol": symbol})
        sentiment = {}
        print(f"2. Consultazione Cervello AI per {symbol}...")
        payload = {"symbol": symbol, "tech_data": tech, "fib_data": fib, "gann_data": gann, "sentiment_data": sentiment}
        brain_resp = get_data(URL_BRAIN, payload)
        if not brain_resp:
            print(f"   -> ⚠️ Il Cervello AI non ha risposto. Salto.")
            continue
        decision = brain_resp.get("decision", "WAIT")
        print(f"   -> 🤖 Risposta AI per {symbol}: {decision}")
        if brain_resp.get("logic_log"):
            for log_entry in brain_resp["logic_log"]: print(f"      - {log_entry}")
        if decision in ["OPEN_LONG", "OPEN_SHORT"]:
            execute_trade(brain_resp, symbol)
    
    print("\n--- Analisi Completata ---")
    print("🛡️ Fase Finale: Gestione Posizioni Attive...")
    # (La logica per il trailing stop qui andrebbe migliorata, ma per ora la lasciamo così)
    mgmt_resp = get_data(URL_MGMT, {"positions": []})
    if mgmt_resp and len(mgmt_resp) > 0:
        print(f"   -> {len(mgmt_resp)} azioni di management ricevute.")
    else: print("   -> Nessuna azione di management richiesta.")
    print(f"--- ✅ CICLO DI SCANSIONE COMPLETATO ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---")

print("🚀 Orchestrator V4 (Position-Aware) avviato. Esecuzione primo ciclo...")
job()
schedule.every(15).minutes.do(job)
print(f"🗓️ Prossima esecuzione schedulata tra 15 minuti. In attesa...")
while True:
    schedule.run_pending()
    time.sleep(1)
