import asyncio
import httpx
import schedule
import time
import os
from datetime import datetime, timezone

# --- CONFIGURAZIONE ---
SYMBOLS_TO_ANALYZE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", 
    "DOGEUSDT", "BNBUSDT", "LTCUSDT", "MATICUSDT", "DOTUSDT"
]

# URL degli Agenti (Corretti con i trattini '-' come nel docker-compose)
TECHNICAL_ANALYZER_AGENT_URL = os.getenv("TECHNICAL_ANALYZER_URL", "http://technical-analyzer-agent:8000")
FIBONACCI_AGENT_URL = os.getenv("FIBONACCI_AGENT_URL", "http://fibonacci-cyclical-agent:8000")
GANN_AGENT_URL = os.getenv("GANN_AGENT_URL", "http://gann-analyzer-agent:8000")
NEWS_SENTIMENT_AGENT_URL = os.getenv("NEWS_SENTIMENT_AGENT_URL", "http://news-sentiment-agent:8000")
MASTER_AI_AGENT_URL = os.getenv("MASTER_AI_AGENT_URL", "http://master-ai-agent:8000")
POSITION_MANAGER_AGENT_URL = os.getenv("POSITION_MANAGER_AGENT_URL", "http://position-manager-agent:8000")

# --- UTILS ---
async def make_request(client, url, method='get', json=None):
    try:
        if method == 'get':
            resp = await client.get(url, timeout=20.0)
        else:
            resp = await client.post(url, json=json, timeout=20.0)
        
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"⚠️ Errore {resp.status_code} da {url}: {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Eccezione chiamando {url}: {e}")
        return None

# --- LOGICA ---

async def get_all_data(client, symbol):
    print(f"   1. Raccolta Dati per {symbol}...")

    # Technical Analyzer (POST)
    tech_url = f"{TECHNICAL_ANALYZER_AGENT_URL}/analyze_multi_tf"
    tech_payload = {"symbol": symbol, "timeframes": ["15", "240"]}
    tech_task = make_request(client, tech_url, method='post', json=tech_payload)

    # Fibonacci Analyzer (POST)
    fib_url = f"{FIBONACCI_AGENT_URL}/analyze_fibonacci"
    fib_payload = {"crypto_symbol": symbol}
    fib_task = make_request(client, fib_url, method='post', json=fib_payload)

    # Gann Analyzer (POST)
    gann_url = f"{GANN_AGENT_URL}/analyze_gann"
    gann_payload = {"symbol": symbol}
    gann_task = make_request(client, gann_url, method='post', json=gann_payload)

    # CoinGecko Market Data (GET)
    market_data_url = f"{NEWS_SENTIMENT_AGENT_URL}/analyze_market_data/{symbol}"
    market_data_task = make_request(client, market_data_url)

    tasks = [tech_task, fib_task, gann_task, market_data_task]
    results = await asyncio.gather(*tasks)

    tech_data_raw = results[0] or {}
    tech_data_15m = (tech_data_raw.get("data") or {}).get("15", {})
    tech_data_4h = (tech_data_raw.get("data") or {}).get("240", {})

    fib_levels = results[1] or {}
    gann_levels = results[2] or {}
    market_data = results[3] or {}

    return tech_data_15m, tech_data_4h, fib_levels, gann_levels, market_data

async def consult_master_ai(client, symbol, tech_15m, tech_4h, fib, gann, market_data):
    print(f"   2. Consultazione Cervello AI per {symbol}...")
    ai_payload = {
        "symbol": symbol,
        "tech_data": {
            "data": {
                "15": tech_15m,
                "240": tech_4h
            }
        },
        "fib_data": fib,
        "gann_data": gann,
        "sentiment_data": market_data
    }
    ai_url = f"{MASTER_AI_AGENT_URL}/decide"

    decision = await make_request(client, ai_url, method='post', json=ai_payload)
    if decision:
        print(f"   -> 🤖 Risposta AI per {symbol}: {decision.get('decision', 'N/D')}")
        if decision.get('logic_log'):
            for line in decision['logic_log']:
                print(f"      {line}")
    else:
        print(f"   -> 🚫 Nessuna risposta valida dalla AI per {symbol}")
    return decision

async def manage_active_positions():
    """Ordina al Position Manager di controllare e aggiornare i Trailing Stop"""
    print("\n--- 🛡️ GESTIONE POSIZIONI APERTE (Trailing Stop) ---")
    try:
        async with httpx.AsyncClient() as client:
            # Chiamata POST vuota: il Position Manager scaricherà le posizioni reali da Bybit
            response = await client.post(f"{POSITION_MANAGER_AGENT_URL}/manage", json={"positions": []}, timeout=20.0)
            
            if response.status_code == 200:
                actions = response.json()
                if actions:
                    for action in actions:
                        print(f"✅ AZIONE SU {action['symbol']}: {action['message']}")
                else:
                    print("ℹ️ Nessuna modifica agli Stop Loss necessaria (Trailing non scattato).")
            else:
                print(f"⚠️ Errore Position Manager durante il trailing: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Impossibile contattare Position Manager per Trailing Stop: {e}")

async def scan_market():
    start_time = datetime.now(timezone.utc)
    print(f"\n--- 🕒 {start_time.strftime('%Y-%m-%d %H:%M:%S')} | INIZIO CICLO DI SCANSIONE MERCATO ---")

    # 1. PRIMA DI TUTTO: Gestiamo le posizioni esistenti (Trailing Stop)
    await manage_active_positions()

    # 2. Recupero posizioni aperte per evitare duplicati e analisi inutili
    open_positions = []
    try:
        async with httpx.AsyncClient() as client:
            pos_data = await make_request(client, f"{POSITION_MANAGER_AGENT_URL}/get_open_positions")
            if pos_data:
                open_positions = pos_data.get("open_positions", [])
            print(f"ℹ️ Posizioni attualmente aperte (SKIP ANALISI): {open_positions if open_positions else 'Nessuna'}")
    except Exception as e:
        print(f"⚠️ Impossibile recuperare lista posizioni aperte: {e}")

    # 3. Scansione Nuovi Ingressi
    async with httpx.AsyncClient() as client:
        for symbol in SYMBOLS_TO_ANALYZE:
            # SE ABBIAMO GIÀ UNA POSIZIONE APERTA, NON ANALIZZIAMO PER APRIRE DI NUOVO
            if symbol in open_positions:
                print(f"\n--- 🚫 {symbol} saltato: posizione già aperta ---")
                continue

            print(f"\n--- Analizzando {symbol} ---")
            tech_15m, tech_4h, fib, gann, market_data = await get_all_data(client, symbol)
            
            # Se manca qualcosa (es. errore o 404), passiamo oltre
            if not (tech_15m and tech_4h and fib and gann and market_data):
                print("   -> ⚠️ Consultazione AI saltata: dati di analisi incompleti.")
                continue

            # Se tutti i dati sono ok, consulta l'AI
            await consult_master_ai(client, symbol, tech_15m, tech_4h, fib, gann, market_data)
            
            # Pausa anti-rate-limit
            await asyncio.sleep(2)

    print("\n--- ✅ CICLO DI SCANSIONE COMPLETATO ---")

def job():
    asyncio.run(scan_market())

if __name__ == "__main__":
    print("🚀 Orchestrator avviato. Esecuzione immediata primo ciclo...")
    job()
    # Pianifica ogni 15 minuti
    schedule.every(15).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)
