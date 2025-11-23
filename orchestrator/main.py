import os
import asyncio
import httpx
import schedule
import time
from datetime import datetime, UTC

# --- Configurazione dagli Variabili d'Ambiente ---
TECHNICAL_ANALYZER_AGENT_URL = os.getenv("TECHNICAL_ANALYZER_AGENT_URL")
FIBONACCI_AGENT_URL = os.getenv("FIBONACCI_AGENT_URL")
GANN_AGENT_URL = os.getenv("GANN_AGENT_URL")
MASTER_AI_AGENT_URL = os.getenv("MASTER_AI_AGENT_URL")
POSITION_MANAGER_AGENT_URL = os.getenv("POSITION_MANAGER_AGENT_URL")
NEWS_SENTIMENT_AGENT_URL = os.getenv("NEWS_SENTIMENT_AGENT_URL")

# Lista delle crypto da analizzare (tutte)
SYMBOLS_TO_ANALYZE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT"
]

async def make_request(client, url, method='get', json=None, timeout=60):
    try:
        if method.lower() == 'post':
            response = await client.post(url, json=json, timeout=timeout)
        else:
            response = await client.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"   -> [ORCHESTRATOR] Fallimento richiesta ({method.upper()}) a {url}: {str(e)}")
        return None

async def get_all_data(client, symbol):
    print(f"1. Raccolta Dati per {symbol}...")

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
    print(f"2. Consultazione Cervello AI per {symbol}...")
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

async def scan_market():
    start_time = datetime.now(UTC)
    print(f"\n--- 🕒 {start_time.strftime('%Y-%m-%d %H:%M:%S')} | INIZIO CICLO DI SCANSIONE MERCATO ---")

    # Recupero posizioni aperte (se vuoi gestire questo aspetto)
    open_positions = []
    try:
        async with httpx.AsyncClient() as client:
            pos_data = await make_request(client, f"{POSITION_MANAGER_AGENT_URL}/get_open_positions")
            if pos_data:
                open_positions = pos_data.get("open_positions", [])
            print(f"ℹ️ Posizioni attualmente aperte: {open_positions if open_positions else 'Nessuna'}")
    except Exception as e:
        print(f"⚠️ Impossibile recuperare posizioni aperte: {e}")

    async with httpx.AsyncClient() as client:
        for symbol in SYMBOLS_TO_ANALYZE:
            if symbol in open_positions:
                print(f"\n--- 🚫 {symbol} saltato: posizione già aperta ---")
                continue
            print(f"\n--- Analizzando {symbol} ---")
            tech_15m, tech_4h, fib, gann, market_data = await get_all_data(client, symbol)
            print("   -> Dati analisi tecnica 15m:", "OK" if tech_15m else "FALLITI")
            print("   -> Dati analisi tecnica 4h:", "OK" if tech_4h else "FALLITI")
            print("   -> Dati Fibonacci:", "OK" if fib else "FALLITI")
            print("   -> Dati Gann:", "OK" if gann else "FALLITI")
            print("   -> Dati CoinGecko:", "OK" if market_data else "FALLITI")

            # Se tutti i dati sono ok, consulta l'AI
            if tech_15m and tech_4h and fib and gann and market_data:
                await consult_master_ai(client, symbol, tech_15m, tech_4h, fib, gann, market_data)
            else:
                print("   -> ⚠️ Consultazione AI saltata: dati di analisi incompleti.")

            await asyncio.sleep(5)

    print("\n--- ✅ CICLO DI SCANSIONE COMPLETATO ---")

def job():
    asyncio.run(scan_market())

if __name__ == "__main__":
    print("🚀 Orchestrator avviato. Esecuzione primo ciclo...")
    job()
    schedule.every(15).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)
