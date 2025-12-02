import asyncio, httpx, time
from datetime import datetime

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

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

async def manage_cycle():
    """Controlla Stop Loss/Take Profit matematici (ATR)"""
    async with httpx.AsyncClient() as c:
        try: await c.post(f"{URLS['pos']}/manage_active_positions", timeout=5)
        except: pass

async def analysis_cycle():
    print(f"\n[{datetime.now().strftime('%H:%M')}] 🧠 AI SCAN START")
    async with httpx.AsyncClient(timeout=60) as c:
        # 1. Dati Portafoglio
        try:
            glob = await asyncio.gather(
                c.get(f"{URLS['pos']}/get_wallet_balance"),
                c.get(f"{URLS['pos']}/get_open_positions"),
                return_exceptions=True
            )
            portfolio = glob[0].json() if hasattr(glob[0], 'json') else {}
            raw_pos = glob[1].json() if hasattr(glob[1], 'json') else {}
            
            # Parsing sicuro
            active_symbols = raw_pos.get('active', [])
            if isinstance(raw_pos, list): active_symbols = []
            
            print(f"ℹ️  Wallet: {portfolio.get('equity', 0)}$ | Active: {active_symbols}")
            
            # MONEY SAVER: Se siamo pieni su tutti i simboli, inutile chiamare l'AI
            if all(s in active_symbols for s in SYMBOLS):
                print("💰 Tutte le posizioni occupate. Skip AI Analysis.")
                return

        except Exception as e: 
            print(f"Error fetch global: {e}")
            return

        # 2. Analisi Tecnica Asset (Solo per quelli liberi)
        assets = {}
        for s in SYMBOLS:
            if s in active_symbols: continue # Non analizziamo se siamo già dentro
            
            try:
                tech = (await c.post(f"{URLS['tech']}/analyze_multi_tf", json={"symbol": s})).json()
                assets[s] = {"tech": tech}
            except: pass

        if not assets:
            print("✅ Nessun asset libero da analizzare.")
            return

        # 3. Chiamata AI
        payload = {
            "global_data": {"portfolio": portfolio, "already_open": active_symbols}, 
            "assets_data": assets
        }
        
        print(f"🚀 Asking Master AI about {list(assets.keys())}...")
        try:
            resp = await c.post(f"{URLS['ai']}/decide_batch", json=payload, timeout=120)
            dec = resp.json()
            print(f"🤖 Analysis: {dec.get('analysis')}")
            
            for d in dec.get('decisions', []):
                sym = d['symbol']
                action = d['action']
                
                # --- MODIFICA FONDAMENTALE ---
                if action == "CLOSE":
                    # L'AI vorrebbe chiudere, ma noi GLIELO VIETIAMO.
                    # Lasciamo correre i profitti (Let Winners Run).
                    print(f"🛡️ AI voleva chiudere {sym} (Take Profit anticipato), ma AUTO-CLOSE è DISABILITATO. HOLDING.")
                    continue 
                # -----------------------------
                
                elif action in ["OPEN_LONG", "OPEN_SHORT"]:
                    if sym in active_symbols: continue
                    
                    print(f"🔥 EXECUTING OPEN: {sym} {action}")
                    await c.post(f"{URLS['pos']}/open_position", json={
                        "symbol": sym,
                        "side": action,
                        "leverage": d.get('leverage', 5),
                        "size_pct": d.get('size_pct', 0.1)
                    })

        except Exception as e: print(f"AI Err: {e}")

async def main_loop():
    while True:
        await manage_cycle() # Gestione Stop Loss
        await analysis_cycle() # Nuove entrate
        await asyncio.sleep(900) # 15 min

if __name__ == "__main__":
    asyncio.run(main_loop())
