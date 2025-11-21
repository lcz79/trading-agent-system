import time
import schedule
import requests
import os
from pybit.unified_trading import HTTP

# --- CONFIG ---
SYMBOL = "BTCUSDT"
QTY_USDT = 50  # Budget base per trade
LEVERAGE = 5

# --- URL DEGLI AGENTI (per Docker Compose) ---
URL_BRAIN = "http://master-ai-agent:8000/decide"
URL_TECH = "http://technical-analyzer-agent:8000/analyze_multi_tf"
URL_FIB = "http://fibonacci-cyclical-agent:8000/analyze_fibonacci"
URL_GANN = "http://gann-analyzer-agent:8000/analyze_gann"
URL_NEWS = "http://coingecko-agent:8000/analyze_sentiment" # Assumendo che l'agente news si chiami così
URL_MGMT = "http://position-manager-agent:8000/manage"

session = HTTP(testnet=False, api_key=os.getenv("BYBIT_API_KEY"), api_secret=os.getenv("BYBIT_API_SECRET"))

def get_data(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=20) # Aumentato timeout per AI
        r.raise_for_status() # Lancia un errore se lo status non è 2xx
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"[ORCHESTRATOR] Errore di rete su {url}: {e}")
        return {}
    except Exception as e:
        print(f"[ORCHESTRATOR] Errore generico su {url}: {e}")
        return {}

def execute_trade(setup):
    if not setup:
        print("❌ Errore: tentativo di eseguire un trade con setup nullo.")
        return
    try:
        action = setup['action']
        side = "Buy" if action == "OPEN_LONG" else "Sell"
        entry = setup['entry_price']
        sl = setup['stop_loss']
        tp = setup['take_profit']
        
        # Calcolo Qty basato sulla size suggerita dall'AI
        budget = QTY_USDT * setup.get('size_pct', 0.5) # Fallback a 50%
        qty = (budget * LEVERAGE) / entry
        qty = round(qty, 3) # Arrotonda alla precisione di BTC

        print(f"🚀 ESECUZIONE ORDINE: {side} {qty} {SYMBOL} @ {entry} | SL: {sl} | TP: {tp}")
        
        # Imposta leva (potrebbe fallire se già impostata, ignoriamo l'errore)
        try:
            session.set_leverage(category="linear", symbol=SYMBOL, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))
        except Exception:
            pass # L'importante è che l'ordine vada a buon fine

        # Invia ordine
        session.place_order(
            category="linear", symbol=SYMBOL, side=side, orderType="Limit",
            qty=str(qty), price=str(entry), timeInForce="GTC",
            stopLoss=str(sl), takeProfit=str(tp),
            slTriggerBy="LastPrice", tpTriggerBy="LastPrice"
        )
        print("✅ Ordine inviato con successo a Bybit.")
    except KeyError as e:
        print(f"❌ Errore: campo mancante nel trade_setup: {e}")
    except Exception as e:
        print(f"❌ Errore esecuzione ordine: {e}")

def job():
    print(f"\n--- 🕒 {time.strftime('%Y-%m-%d %H:%M:%S')} | INIZIO CICLO DI ANALISI ---")
    
    # 1. Raccolta Dati in Parallelo (più efficiente, ma per ora sequenziale)
    print("📡 Fase 1: Raccolta Dati...")
    tech = get_data(URL_TECH, {"symbol": SYMBOL})
    fib = get_data(URL_FIB, {"crypto_symbol": SYMBOL})
    gann = get_data(URL_GANN, {"symbol": SYMBOL})
    news = get_data(URL_NEWS, {"crypto_symbol": SYMBOL.replace("USDT","")})
    
    if not tech or not fib: 
        print("⚠️ DATI FONDAMENTALI (TECH/FIB) MANCANTI. CICLO INTERROTTO.")
        return

    # 2. Consultazione Cervello AI
    print("🧠 Fase 2: Consultazione Cervello AI...")
    payload = {
        "symbol": SYMBOL, "tech_data": tech, "fib_data": fib,
        "gann_data": gann, "sentiment_data": news
    }
    brain_resp = get_data(URL_BRAIN, payload)
    
    if not brain_resp:
        print("⚠️ IL CERVELLO AI NON HA RISPOSTO. CICLO INTERROTTO.")
        return
        
    decision = brain_resp.get("decision", "WAIT")
    print(f"🤖 Risposta AI: {decision}")
    
    # Logica decisionale dell'AI
    if brain_resp.get("logic_log"):
        for log_entry in brain_resp["logic_log"]:
            print(f"   - {log_entry}")
    
    if decision in ["OPEN_LONG", "OPEN_SHORT"]:
        execute_trade(brain_resp.get('trade_setup'))
        
    # 3. Gestione Posizioni Aperte (Trailing Stop)
    print("🛡️ Fase 3: Gestione Posizioni (Trailing Stop)...")
    mgmt_resp = get_data(URL_MGMT, {"positions": []}) # L'agente management ora si scarica le posizioni da solo
    
    if mgmt_resp:
        print(f"   -> {len(mgmt_resp)} azioni di management ricevute.")
        for act in mgmt_resp:
            print(f"   -> 🔧 Adeguamento SL per {act['symbol']} a {act['new_stop_loss']}")
            try:
                session.set_trading_stop(
                    category="linear", symbol=act['symbol'], 
                    stopLoss=str(act['new_stop_loss']), slTriggerBy="LastPrice"
                )
            except Exception as e: 
                print(f"      -> ❌ Errore aggiornamento SL: {e}")
    else:
        print("   -> Nessuna azione di management richiesta.")
    
    print("--- ✅ CICLO COMPLETATO ---")

# Avvio del ciclo
print("🚀 Orchestrator avviato. Prima esecuzione in corso...")
job() # Esegui subito il primo ciclo

schedule.every(15).minutes.do(job)
print(f"🗓️ Prossima esecuzione schedulata tra 15 minuti. In attesa...")

while True:
    schedule.run_pending()
    time.sleep(1)
