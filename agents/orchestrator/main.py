import asyncio, httpx, json
from datetime import datetime

URLS = {
    "tech": "http://01_technical_analyzer:8000",
    "pos": "http://07_position_manager:8000",
    "ai": "http://04_master_ai_agent:8000"
}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# --- CONFIGURAZIONE OTTIMIZZAZIONE ---
MAX_POSITIONS = 3  # Numero massimo posizioni contemporanee
REVERSE_THRESHOLD = 2.0  # Percentuale perdita per trigger reverse analysis

async def manage_cycle():
    async with httpx.AsyncClient() as c:
        try: await c.post(f"{URLS['pos']}/manage_active_positions", timeout=5)
        except: pass

async def analysis_cycle():
    async with httpx.AsyncClient(timeout=60) as c:
        
        # 1. DATA COLLECTION
        portfolio = {}
        position_details = []
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
                position_details = d.get('details', []) if isinstance(d, dict) else []

        except Exception as e:
            print(f"⚠️ Data Error: {e}")
            return

        num_positions = len(active_symbols)
        print(f"\n[{datetime.now().strftime('%H:%M')}] 📊 Position check: {num_positions}/{MAX_POSITIONS} posizioni aperte")
        
        # 2. LOGICA OTTIMIZZAZIONE
        positions_losing = []
        
        # Controlla posizioni in perdita oltre la soglia
        for pos in position_details:
            entry = pos.get('entry_price', 0)
            mark = pos.get('mark_price', 0)
            side = pos.get('side', '').lower()
            symbol = pos.get('symbol', '')
            
            if entry > 0 and mark > 0:
                # Calcola perdita %
                if side in ['long', 'buy']:
                    loss_pct = ((mark - entry) / entry) * 100
                else:  # short - loss when mark > entry
                    loss_pct = -((mark - entry) / entry) * 100  # Inverted for shorts
                
                if loss_pct < -REVERSE_THRESHOLD:
                    positions_losing.append({
                        'symbol': symbol,
                        'loss_pct': loss_pct,
                        'side': side
                    })

        # CASO 1: Tutte le posizioni occupate (3/3)
        if num_positions >= MAX_POSITIONS:
            if positions_losing:
                # Ci sono posizioni in perdita oltre la soglia
                for pos_loss in positions_losing:
                    print(f"        ⚠️ {pos_loss['symbol']} perde {pos_loss['loss_pct']:.2f}%")
                
                # TODO: Implementare logica reverse per chiudere/invertire posizioni in perdita
                # Per ora monitoriamo solo, il trailing stop gestirà l'uscita
                print(f"        ⚠️ {len(positions_losing)} posizione(i) in perdita critica rilevata(e)")
            else:
                # Nessuna posizione in perdita critica
                print("        ✅ Nessun allarme perdita - Skip analisi DeepSeek")
            return

        # CASO 2: Almeno uno slot libero (< 3 posizioni)
        print(f"        🔍 Slot libero - Chiamo DeepSeek per nuove opportunità")
        
        # 3. FILTER - Solo asset senza posizione aperta
        scan_list = [s for s in SYMBOLS if s not in active_symbols]
        if not scan_list:
            print("        ⚠️ Nessun asset disponibile per scan")
            return

        # 4. TECH ANALYSIS
        assets_data = {}
        for s in scan_list:
            try:
                t = (await c.post(f"{URLS['tech']}/analyze_multi_tf", json={"symbol": s})).json()
                assets_data[s] = {"tech": t}
            except: pass
        
        if not assets_data: 
            print("        ⚠️ Nessun dato tecnico disponibile")
            return

        # 5. AI DECISION
        print(f"        🤖 DeepSeek: Analizzando {list(assets_data.keys())}...")
        try:
            resp = await c.post(f"{URLS['ai']}/decide_batch", json={
                "global_data": {"portfolio": portfolio, "already_open": active_symbols},
                "assets_data": assets_data
            }, timeout=120)
            
            dec_data = resp.json()
            analysis_text = dec_data.get('analysis', 'No text')
            decisions_list = dec_data.get('decisions', [])

            print(f"        📝 AI Says: {analysis_text}")

            if not decisions_list:
                print("        ℹ️ AI non ha generato ordini")
                return

            # 6. EXECUTION
            for d in decisions_list:
                sym = d['symbol']
                action = d['action']
                
                if action == "CLOSE":
                    print(f"        🛡️ Ignorato CLOSE su {sym} (Auto-Close Disabled)")
                    continue

                if action in ["OPEN_LONG", "OPEN_SHORT"]:
                    print(f"        🔥 EXECUTING {action} on {sym}...")
                    res = await c.post(f"{URLS['pos']}/open_position", json={
                        "symbol": sym,
                        "side": action,
                        "leverage": d.get('leverage', 5),
                        "size_pct": d.get('size_pct', 0.15)
                    })
                    print(f"        ✅ Result: {res.json()}")

        except Exception as e: 
            print(f"        ❌ AI/Exec Error: {e}")

async def main_loop():
    while True:
        await manage_cycle()
        await analysis_cycle()
        await asyncio.sleep(60)  # Ciclo ogni 60 secondi invece di 900

if __name__ == "__main__":
    asyncio.run(main_loop())
