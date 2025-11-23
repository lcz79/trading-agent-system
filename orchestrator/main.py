import asyncio
import httpx
import schedule
import time
import os
import json
from datetime import datetime, timezone

# --- PERCORSI DATI ---
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")
ACTIONS_FILE = os.path.join(DATA_DIR, "actions.json")
EQUITY_FILE = os.path.join(DATA_DIR, "equity.json")

# --- CONFIGURAZIONE DEFAULT ---
DEFAULT_CONFIG = {
    "risk_per_trade": 1.0,
    "strategy": "intraday",
    "initial_budget": 1000.0,
    "active": True
}

# NOTA: Ho rimosso MATICUSDT per evitare errori API
SYMBOLS_TO_ANALYZE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", 
    "DOGEUSDT", "BNBUSDT", "LTCUSDT", "DOTUSDT"
]

# URL AGENTI
TECHNICAL_ANALYZER_AGENT_URL = os.getenv("TECHNICAL_ANALYZER_URL", "http://technical-analyzer-agent:8000")
FIBONACCI_AGENT_URL = os.getenv("FIBONACCI_AGENT_URL", "http://fibonacci-cyclical-agent:8000")
GANN_AGENT_URL = os.getenv("GANN_AGENT_URL", "http://gann-analyzer-agent:8000")
NEWS_SENTIMENT_AGENT_URL = os.getenv("NEWS_SENTIMENT_AGENT_URL", "http://news-sentiment-agent:8000")
MASTER_AI_AGENT_URL = os.getenv("MASTER_AI_AGENT_URL", "http://master-ai-agent:8000")
POSITION_MANAGER_AGENT_URL = os.getenv("POSITION_MANAGER_AGENT_URL", "http://position-manager-agent:8000")

# --- UTILS ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return json.load(f)
        except: return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_json_append(filepath, entry, max_items=200):
    data = []
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f: data = json.load(f)
        except: pass
    
    data.append(entry)
    if len(data) > max_items: data = data[-max_items:]
    
    with open(filepath, 'w') as f: json.dump(data, f, indent=4)

async def make_request(client, url, method='get', json_data=None):
    try:
        if method == 'get': resp = await client.get(url, timeout=20.0)
        else: resp = await client.post(url, json=json_data, timeout=20.0)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        print(f"❌ Error {url}: {e}")
        return None

# --- LOGICA ---

async def track_equity(client):
    """Recupera il saldo reale e lo salva per il grafico"""
    resp = await make_request(client, f"{POSITION_MANAGER_AGENT_URL}/get_wallet_balance")
    if resp:
        equity = resp.get("equity", 0.0)
        if equity > 0:
            entry = {
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                "equity": equity
            }
            save_json_append(EQUITY_FILE, entry, max_items=500)
            print(f"💰 Equity Tracciata: ${equity}")

async def manage_active_positions():
    print("\n--- 🛡️ GESTIONE POSIZIONI APERTE (Trailing Stop) ---")
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{POSITION_MANAGER_AGENT_URL}/manage", json={"positions": []}, timeout=20.0)
        if response and response.status_code == 200:
            actions = response.json()
            for action in actions:
                print(f"✅ AZIONE: {action['message']}")
                save_json_append(ACTIONS_FILE, {
                    "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    "symbol": action['symbol'],
                    "action": "TRAILING_STOP",
                    "details": action['message']
                })

async def scan_market():
    config = load_config()
    
    # Tracciamento Equity Reale
    async with httpx.AsyncClient() as client:
        await track_equity(client)

    if not config.get("active", True):
        print("💤 BOT IN PAUSA (da Dashboard)")
        return

    start_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n--- 🕒 {start_time} | SCAN (Strategy: {config.get('strategy')}, Risk: {config.get('risk_per_trade')}%) ---")

    await manage_active_positions()

    # Get Open Positions
    open_positions = []
    async with httpx.AsyncClient() as client:
        pos_data = await make_request(client, f"{POSITION_MANAGER_AGENT_URL}/get_open_positions")
        if pos_data: open_positions = pos_data.get("open_positions", [])
        print(f"ℹ️ Posizioni aperte (SKIP): {open_positions}")

    async with httpx.AsyncClient() as client:
        for symbol in SYMBOLS_TO_ANALYZE:
            if symbol in open_positions: continue

            print(f"Analizzando {symbol}...")
            # Chiamate parallele
            tech_url = f"{TECHNICAL_ANALYZER_AGENT_URL}/analyze_multi_tf"
            fib_url = f"{FIBONACCI_AGENT_URL}/analyze_fibonacci"
            gann_url = f"{GANN_AGENT_URL}/analyze_gann"
            news_url = f"{NEWS_SENTIMENT_AGENT_URL}/analyze_market_data/{symbol}"

            tasks = [
                make_request(client, tech_url, 'post', {"symbol": symbol, "timeframes": ["15", "240"]}),
                make_request(client, fib_url, 'post', {"crypto_symbol": symbol}),
                make_request(client, gann_url, 'post', {"symbol": symbol}),
                make_request(client, news_url)
            ]
            results = await asyncio.gather(*tasks)
            tech, fib, gann, news = results

            # Se mancano dati critici (Tech o Fib), saltiamo. 
            # Se manca News o Gann, proseguiamo lo stesso (Resilienza).
            if not tech or not fib:
                print(f"⚠️ Dati tecnici critici mancanti per {symbol}, skip.")
                continue

            ai_payload = {
                "symbol": symbol,
                "user_config": config, # PASSAGGIO CONFIGURAZIONE UTENTE
                "tech_data": {"data": {"15": tech.get("data", {}).get("15"), "240": tech.get("data", {}).get("240")}},
                "fib_data": fib,
                "gann_data": gann or {},
                "sentiment_data": news or {"summary": "N/A"}
            }

            decision_resp = await make_request(client, f"{MASTER_AI_AGENT_URL}/decide", 'post', ai_payload)
            
            if decision_resp:
                decision = decision_resp.get('decision', 'WAIT')
                reason = " | ".join(decision_resp.get('logic_log', []))
                print(f"   -> 🤖 {symbol}: {decision}")
                
                save_json_append(LOGS_FILE, {
                    "timestamp": start_time,
                    "symbol": symbol,
                    "decision": decision,
                    "reason": reason,
                    "strategy_used": config.get('strategy')
                })
            
            await asyncio.sleep(1)

def job():
    asyncio.run(scan_market())

if __name__ == "__main__":
    print("🚀 Orchestrator V2 Control Room Ready.")
    job()
    schedule.every(15).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)
