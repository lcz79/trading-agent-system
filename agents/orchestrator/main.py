import os
import asyncio
import httpx
import json
from datetime import datetime

URLS = {
    "tech": "http://01_technical_analyzer:8000",
    "pos": "http://07_position_manager:8000",
    "ai": "http://04_master_ai_agent:8000",
    "learning": "http://10_learning_agent:8000"
}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# Reverse strategy configuration
ENABLE_REVERSE = os.getenv('ENABLE_REVERSE_STRATEGY', 'true').lower() == 'true'
REVERSE_LOSS_THRESHOLD_PCT = float(os.getenv('REVERSE_LOSS_THRESHOLD_PCT', '2.0'))
REVERSE_RECOVERY_MULTIPLIER = float(os.getenv('REVERSE_RECOVERY_MULTIPLIER', '1.5'))

async def check_reverse_opportunities():
    """Check if any open positions need to be reversed due to losses"""
    if not ENABLE_REVERSE:
        return
    
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            # Get open positions with details
            r_pos = await c.get(f"{URLS['pos']}/get_open_positions")
            if r_pos.status_code != 200:
                return
            
            pos_data = r_pos.json()
            positions = pos_data.get('details', [])
            
            for pos in positions:
                symbol = pos.get('symbol')
                pnl = pos.get('pnl', 0)
                entry_price = pos.get('entry_price', 0)
                size = pos.get('size', 0)
                leverage = pos.get('leverage', 1)
                side = pos.get('side', '').lower()
                
                # Calculate loss percentage
                if entry_price > 0 and leverage > 0:
                    position_value = entry_price * size / leverage
                    loss_pct = abs(pnl / position_value * 100) if position_value > 0 else 0
                    
                    # Check if loss exceeds threshold
                    if pnl < 0 and loss_pct >= REVERSE_LOSS_THRESHOLD_PCT:
                        print(f"🚨 REVERSE TRIGGER: {symbol} - Loss: ${pnl:.2f} ({loss_pct:.2f}%)")
                        
                        # Execute reverse strategy
                        reverse_result = await c.post(f"{URLS['pos']}/reverse_position", json={
                            "symbol": symbol,
                            "current_side": side,
                            "loss_amount": abs(pnl),
                            "recovery_multiplier": REVERSE_RECOVERY_MULTIPLIER,
                            "leverage": min(leverage, 7.0)
                        })
                        
                        if reverse_result.status_code == 200:
                            result = reverse_result.json()
                            print(f"✅ REVERSE EXECUTED: {symbol} - New size: {result.get('new_size')} - Target recovery: ${result.get('recovery_target'):.2f}")
                        else:
                            print(f"❌ REVERSE FAILED: {symbol} - {reverse_result.text}")
        
        except Exception as e:
            print(f"⚠️ Reverse check error: {e}")

async def manage_cycle():
    """Manage active positions and check for reverse opportunities"""
    async with httpx.AsyncClient() as c:
        try: 
            await c.post(f"{URLS['pos']}/manage_active_positions", timeout=5)
        except: 
            pass
    
    # Check for reverse opportunities
    await check_reverse_opportunities()

async def analysis_cycle():
    print(f"\n[{datetime.now().strftime('%H:%M')}] 🧠 AI SCAN START")
    async with httpx.AsyncClient(timeout=60) as c:
        
        # 1. DATA COLLECTION
        portfolio = {}
        active_symbols = []
        positions_details = []
        learning_insights = {}
        
        try:
            # Fetch parallel data
            r_bal, r_pos = await asyncio.gather(
                c.get(f"{URLS['pos']}/get_wallet_balance"),
                c.get(f"{URLS['pos']}/get_open_positions"),
                return_exceptions=True
            )
            
            if hasattr(r_bal, 'json'): 
                portfolio = r_bal.json()
            
            if hasattr(r_pos, 'json'): 
                pos_data = r_pos.json()
                active_symbols = pos_data.get('active', []) if isinstance(pos_data, dict) else []
                positions_details = pos_data.get('details', [])
            
            print(f"ℹ️  Wallet: {portfolio.get('equity', 0)}$ | Active: {active_symbols}")
            
            # Get learning insights for scan symbols
            try:
                r_learning = await c.post(f"{URLS['learning']}/analyze_symbols", json={
                    "symbols": SYMBOLS,
                    "days": 30
                })
                if r_learning.status_code == 200:
                    learning_insights = r_learning.json()
                    print(f"📚 Learning Agent: {learning_insights.get('overall_recommendation', 'N/A')}")
            except Exception as e:
                print(f"⚠️ Learning Agent unavailable: {e}")

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
            except: 
                pass
        
        if not assets_data: 
            return

        # 4. AI DECISION (with learning insights)
        print(f"🚀 Asking DeepSeek AI about {list(assets_data.keys())}...")
        try:
            resp = await c.post(f"{URLS['ai']}/decide_batch", json={
                "global_data": {
                    "portfolio": portfolio, 
                    "already_open": active_symbols,
                    "positions_details": positions_details,
                    "learning_insights": learning_insights
                },
                "assets_data": assets_data
            }, timeout=120)
            
            dec_data = resp.json()
            analysis_text = dec_data.get('analysis', 'No text')
            market_conditions = dec_data.get('market_conditions', 'Unknown')
            risk_assessment = dec_data.get('risk_assessment', 'Not provided')
            decisions_list = dec_data.get('decisions', [])

            print(f"🤖 DeepSeek AI Analysis: {analysis_text}")
            print(f"📊 Market Conditions: {market_conditions}")
            print(f"⚠️  Risk Assessment: {risk_assessment}")
            print(f"📋 AI Orders List: {decisions_list}")

            if not decisions_list:
                print("⚠️ AI did not generate any orders despite the analysis.")

            # 5. EXECUTION
            for d in decisions_list:
                sym = d['symbol']
                action = d['action']
                is_reverse = d.get('is_reverse', False)
                recovery_mult = d.get('recovery_multiplier', 1.0)
                
                if action == "CLOSE":
                    print(f"🛡️ Ignored CLOSE on {sym} (Auto-Close Disabled)")
                    continue
                
                # Handle REVERSE actions
                if action in ["REVERSE_LONG", "REVERSE_SHORT"]:
                    print(f"🔄 AI RECOMMENDS REVERSE on {sym} - Checking position...")
                    # This is now handled by check_reverse_opportunities
                    continue

                if action in ["OPEN_LONG", "OPEN_SHORT"]:
                    print(f"🔥 EXECUTING {action} on {sym}...")
                    
                    # Adjust size if recovery multiplier is set
                    size_pct = d.get('size_pct', 0.15)
                    if recovery_mult > 1.0:
                        size_pct = min(size_pct * recovery_mult, 0.30)
                        print(f"   📈 Size increased for recovery: {size_pct:.2%}")
                    
                    res = await c.post(f"{URLS['pos']}/open_position", json={
                        "symbol": sym,
                        "side": action,
                        "leverage": d.get('leverage', 5),
                        "size_pct": size_pct
                    })
                    print(f"✅ Result: {res.json()}")

        except Exception as e: 
            print(f"❌ AI/Exec Error: {e}")

async def main_loop():
    """Main orchestrator loop"""
    analysis_counter = 0
    
    while True:
        # Always manage positions and check for reverses (every 60 seconds)
        await manage_cycle()
        
        # Run full analysis cycle every 15 minutes (900 seconds / 60 = 15 iterations)
        analysis_counter += 1
        if analysis_counter >= 15:
            await analysis_cycle()
            analysis_counter = 0
        
        await asyncio.sleep(60)  # 60 second cycle

if __name__ == "__main__":
    print("🚀 Trading Orchestrator Starting...")
    print(f"   - Position monitoring: every 60 seconds")
    print(f"   - Full analysis: every 15 minutes")
    print(f"   - Reverse strategy: {'ENABLED' if ENABLE_REVERSE else 'DISABLED'}")
    print(f"   - Reverse threshold: {REVERSE_LOSS_THRESHOLD_PCT}%")
    print(f"   - Recovery multiplier: {REVERSE_RECOVERY_MULTIPLIER}x")
    asyncio.run(main_loop())
