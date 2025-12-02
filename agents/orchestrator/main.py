import asyncio, httpx, time
from datetime import datetime

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# URL CORRETTI
URLS = {
    "tech": "http://01_technical_analyzer:8000",
    "fc": "http://08_forecaster_agent:8000",
    "fib": "http://03_fibonacci_agent:8000",
    "gann": "http://05_gann_analyzer_agent:8000",
    "sent": "http://06_news_sentiment_agent:8000",
    "pos": "http://07_position_manager:8000",
    "ai": "http://04_master_ai_agent:8000"
}

async def manage_cycle():
    async with httpx.AsyncClient() as c:
        try:
            r = await c.post(f"{URLS['pos']}/manage_active_positions", timeout=10)
            if r.status_code == 200:
                logs = r.json().get('actions', [])
                if logs: print(f"🛡️ PROTECTION: {logs}")
        except Exception:
            pass

async def analysis_cycle():
    print(f"\n[{datetime.now().strftime('%H:%M')}] 🧠 AI SCAN START")
    async with httpx.AsyncClient(timeout=60) as c:
        # 1. Global Data + POSIZIONI APERTE
        try:
            glob = await asyncio.gather(
                c.get(f"{URLS['pos']}/get_wallet_balance"),
                c.get(f"{URLS['sent']}/global_sentiment"),
                c.get(f"{URLS['pos']}/get_open_positions"),
                return_exceptions=True
            )
            
            # Gestione Errori Singoli
            portfolio = glob[0].json() if not isinstance(glob[0], Exception) else {}
            if isinstance(portfolio, list): portfolio = {} # Fix sicurezza

            fg = glob[1].json() if not isinstance(glob[1], Exception) else {}
            
            # --- FIX CRASH LISTA vs DIZIONARIO ---
            raw_pos = glob[2].json() if not isinstance(glob[2], Exception) else []
            active_symbols = []
            
            if isinstance(raw_pos, list):
                # Se è una lista pura, estraiamo i simboli
                active_symbols = [p.get('symbol') for p in raw_pos if isinstance(p, dict) and 'symbol' in p]
            elif isinstance(raw_pos, dict):
                # Se è un dizionario, cerchiamo la chiave 'active'
                active_symbols = raw_pos.get("active", [])

            print(f"ℹ️  Portfolio: {portfolio.get('equity', '0')}$ | Active: {active_symbols}")

        except Exception as e:
            print(f"❌ Error fetching global data: {e}")
            return

        # 2. Assets Data
        assets = {}
        for s in SYMBOLS:
            try:
                tech_r = await c.post(f"{URLS['tech']}/analyze_multi_tf", json={"symbol": s})
                if tech_r.status_code != 200:
                    print(f"⚠️ Tech Analyzer Failed for {s}")
                    continue
                    
                tech = tech_r.json()
                price = tech.get('price', 0)
                
                r = await asyncio.gather(
                    c.post(f"{URLS['fc']}/forecast", json={"symbol": s}),
                    c.post(f"{URLS['fib']}/analyze_fibonacci", json={"crypto_symbol": s}),
                    c.post(f"{URLS['gann']}/analyze_gann", json={"price": price}),
                    return_exceptions=True
                )
                assets[s] = {
                    "tech": tech,
                    "fc": r[0].json() if not isinstance(r[0], Exception) else {},
                    "fib": r[1].json() if not isinstance(r[1], Exception) else {},
                    "gann": r[2].json() if not isinstance(r[2], Exception) else {}
                }
            except Exception as e: print(f"Err Analyzing {s}: {e}")

        # 3. AI Decision
        payload = {
            "global_data": {"fg": fg, "portfolio": portfolio, "already_open": active_symbols}, 
            "assets_data": assets
        }
        
        try:
            resp = await c.post(f"{URLS['ai']}/decide_batch", json=payload, timeout=120)
            dec = resp.json()
            print(f"🤖 Analysis: {dec.get('analysis')}")
            
            for d in dec.get('decisions', []):
                sym = d['symbol']
                action = d['action']
                
                if sym in active_symbols:
                    print(f"⚠️ SKIP {sym}: Position already open.")
                    continue
                
                if action in ["OPEN_LONG", "OPEN_SHORT"]:
                    print(f"🔥 EXECUTING: {sym} {action} (Lev {d['leverage']}x)")
                    
                    ord_resp = await c.post(f"{URLS['pos']}/open_position", json={
                        "symbol": sym,
                        "side": "Buy" if "LONG" in action else "Sell",
                        "leverage": d['leverage'],
                        "size_pct": d['size_pct']
                    })
                    print(f"👉 BYBIT RESPONSE: {ord_resp.json()}")

        except Exception as e: print(f"AI Err: {e}")

async def main_loop():
    last_scan = 0
    SCAN_INTERVAL = 900 
    print("🚀 ORCHESTRATOR STARTED - System Ready.")
    time.sleep(5)
    
    while True:
        now = time.time()
        await manage_cycle()
        if now - last_scan > SCAN_INTERVAL:
            await analysis_cycle()
            last_scan = now
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main_loop())
