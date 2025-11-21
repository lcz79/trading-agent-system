import time
import schedule
import requests
import os
from pybit.unified_trading import HTTP
from typing import Dict, Any

# --- CONFIGURAZIONE ---
SYMBOL = "BTCUSDT"
TIMEFRAME = "15"
QTY_USDT_PER_TRADE = 100
LEVERAGE = 5

# --- URL DEGLI AGENTI (per Docker Compose) ---
URL_BRAIN = "http://master-ai-agent:8000/decide"
URL_TECH = "http://technical-analyzer-agent:8000/analyze_multi_tf"
URL_FIB = "http://fibonacci-cyclical-agent:8000/analyze_fibonacci"
URL_GANN = "http://gann-analyzer-agent:8000/analyze_gann"
URL_NEWS = "http://coingecko-agent:8000/analyze"
URL_MGMT = "http://position-manager-agent:8000/manage"

session = HTTP(
    testnet=False,
    api_key=os.getenv("BYBIT_API_KEY"),
    api_secret=os.getenv("BYBIT_API_SECRET"),
)

def get_data_safe(url: str, payload: dict) -> Dict[str, Any]:
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[ORCHESTRATOR] Errore chiamata {url}: {e}")
        return {}

def execute_order_on_bybit(decision: dict):
    setup = decision.get("trade_setup")
    if not setup: return

    action = setup["action"]
    entry = setup["entry_price"]
    sl = setup["stop_loss"]
    tp = setup["take_profit"]
    size_pct = setup.get("size_pct", 1.0) # Fallback a 100%

    budget_usdt = QTY_USDT_PER_TRADE * size_pct
    qty = (budget_usdt * LEVERAGE) / entry
    qty = round(qty, 3) 

    side = "Buy" if action == "OPEN_LONG" else "Sell"
    
    print(f"🚀 ESECUZIONE ORDINE: {side} {qty} {SYMBOL} @ {entry}. SL: {sl}, TP: {tp}")

    try:
        try:
            session.set_leverage(category="linear", symbol=SYMBOL, buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE))
        except Exception:
            pass

        order = session.place_order(
            category="linear", symbol=SYMBOL, side=side, orderType="Limit",
            qty=str(qty), price=str(entry), timeInForce="GTC",
            stopLoss=str(sl), takeProfit=str(tp),
            slTriggerBy="LastPrice", tpTriggerBy="LastPrice"
        )
        print(f"✅ ORDINE INVIATO! ID: {order.get('result', {}).get('orderId')}")
    except Exception as e:
        print(f"❌ ERRORE BYBIT: {e}")

def job_15_min():
    print(f"\n--- ⏰ INIZIO CICLO ANALISI: {time.strftime('%H:%M:%S')} ---")
    
    print("📡 Raccolta dati in corso...")
    tech_data = get_data_safe(URL_TECH, {"symbol": SYMBOL, "timeframes": ["15", "60", "240"]})
    fib_data = get_data_safe(URL_FIB, {"crypto_symbol": SYMBOL, "interval": "240"})
    gann_data = get_data_safe(URL_GANN, {"symbol": SYMBOL, "interval": "D"})
    news_data = get_data_safe(URL_NEWS, {"crypto_symbol": SYMBOL.replace("USDT", "")})

    if not tech_data or not fib_data:
        print("⚠️ Dati tecnici o Fib non disponibili. Salto il ciclo.")
        return

    print("🧠 Consultazione Master Brain...")
    payload_brain = {
        "symbol": SYMBOL, "tech_data": tech_data, "fib_data": fib_data,
        "gann_data": gann_data, "sentiment_data": news_data
    }
    decision_response = get_data_safe(URL_BRAIN, payload_brain)
    
    if not decision_response:
        print("⚠️ Il Master Brain non ha risposto. Salto il ciclo.")
        return

    decision = decision_response.get("decision", "WAIT")
    log = decision_response.get("logic_log", [])
    
    print(f"🤖 RISPOSTA AI: {decision}")
    if log:
        print("📝 Ragionamento:")
        for l in log: print(f"  - {l}")

    if decision in ["OPEN_LONG", "OPEN_SHORT"]:
        execute_order_on_bybit(decision_response)
    else:
        print("zzz Nessuna operazione da aprire.")

    print("🛡️ Controllo posizioni aperte (Trailing Stop)...")
    mgmt_response = get_data_safe(URL_MGMT, {"positions": []})
    
    if mgmt_response:
        print(f"🔧 Azioni di gestione: {len(mgmt_response)}")
        for action in mgmt_response:
            print(f"   -> Aggiornamento SL su {action['symbol']} a {action['new_stop_loss']}")
            try:
                session.set_trading_stop(
                    category="linear", symbol=action['symbol'],
                    stopLoss=str(action['new_stop_loss']), slTriggerBy="LastPrice"
                )
            except Exception as e:
                print(f"Errore update SL: {e}")

    print("--- CICLO COMPLETATO (Attesa 15 min) ---\n")

if __name__ == "__main__":
    job_15_min()
    schedule.every(15).minutes.do(job_15_min)
    print("🚀 Orchestrator avviato. Premere Ctrl+C per fermare.")
    while True:
        schedule.run_pending()
        time.sleep(1)
