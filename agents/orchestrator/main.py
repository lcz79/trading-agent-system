import asyncio, httpx, json
from datetime import datetime

URLS = {
    "tech": "http://01_technical_analyzer:8000",
    "pos": "http://07_position_manager:8000",
    "ai": "http://04_master_ai_agent:8000"
}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

async def manage_cycle():
    async with httpx.AsyncClient() as c:
        try: await c.post(f"{URLS['pos']}/manage_active_positions", timeout=5)
        except: pass

async def analysis_cycle():
    print(f"\n[{datetime.now().strftime('%H:%M')}] 🧠 AI SCAN START")
    async with httpx.AsyncClient(timeout=60) as c:
        
        # 1. DATA COLLECTION
        portfolio = {}
        active_symbols = []
        try:
            # Fetch parallelo
            r_bal, r_pos = await asyncio.gather(
                c.get(f"{URLS['pos']}/get_wallet_balance"),
                c.get(f"{URLS['pos']}/get_open_positions"),
                return_exceptions=True
            )
            if hasattr(r_bal, 'json'): portfolio = r_bal.json()
            if hasattr(r_pos, 'json'): 
                d = r_pos.json()
                active_symbols = d.get('active', []) if isinstance(d, dict) else []
            
            print(f"ℹ️  Wallet: {portfolio.get('equity', 0)}$ | Active: {active_symbols}")

        except Exception as e:
            print(f"⚠️ Data Error: {e}")
            return

        # 2. FILTER
        scan_list = [s for s in SYMBOLS if s not in active_symbols]
        if not scan_list:
            print("💰 Full Portfolio. Skip.")
            return

        # 3. TECH ANALYSIS
        assets_data = {}
        for s in scan_list:
            try:
                t = (await c.post(f"{URLS['tech']}/analyze_multi_tf", json={"symbol": s})).json()
                assets_data[s] = {"tech": t}
            except: pass
        
        if not assets_data: return

        # 4. AI DECISION
        print(f"🚀 Asking AI about {list(assets_data.keys())}...")
        try:
            resp = await c.post(f"{URLS['ai']}/decide_batch", json={
                "global_data": {"portfolio": portfolio, "already_open": active_symbols},
                "assets_data": assets_data
            }, timeout=120)
            
            dec_data = resp.json()
            analysis_text = dec_data.get('analysis', 'No text')
            decisions_list = dec_data.get('decisions', [])

            print(f"🤖 AI Says: {analysis_text}")
            print(f"📋 AI Orders List: {decisions_list}") # DEBUG CRUCIALE

            if not decisions_list:
                print("⚠️ AI non ha generato ordini JSON nonostante l'analisi.")

            # 5. EXECUTION
            for d in decisions_list:
                sym = d['symbol']
                action = d['action']
                
                if action == "CLOSE":
                    print(f"🛡️ Ignorato CLOSE su {sym} (Auto-Close Disabled)")
                    continue

                if action in ["OPEN_LONG", "OPEN_SHORT"]:
                    print(f"🔥 EXECUTING {action} on {sym}...")
                    res = await c.post(f"{URLS['pos']}/open_position", json={
                        "symbol": sym,
                        "side": action,
                        "leverage": d.get('leverage', 5),
                        "size_pct": d.get('size_pct', 0.15)
                    })
                    print(f"✅ Result: {res.json()}")

        except Exception as e: print(f"❌ AI/Exec Error: {e}")

async def main_loop():
    while True:
        await manage_cycle()
        await analysis_cycle()
        await asyncio.sleep(900)

if __name__ == "__main__":
    asyncio.run(main_loop())
