"""
Trading Dashboard v7.3 - FIXED DATA MAPPING
"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="Mitragliere Dashboard", version="7.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# URL interni della rete Docker
POS_URL = os.getenv("POSITION_MANAGER_URL", "http://position-manager-agent:8000")
AI_URL = os.getenv("MASTER_AI_URL", "http://master-ai-agent:8000")

# --- BACKEND PROXY ---
async def safe_get(client, url, default):
    try:
        r = await client.get(url, timeout=2.0)
        if r.status_code == 200: return r.json()
    except: pass
    return default

@app.get("/api/wallet")
async def gw():
    async with httpx.AsyncClient() as c:
        # Chiamiamo il backend (che restituisce 'balance')
        data = await safe_get(c, f"{POS_URL}/get_wallet_balance", {"balance": 0})
        # ADATTATORE: Trasformiamo 'balance' in 'equity' per il JS
        val = data.get("balance", 0)
        return {"equity": val, "availableToWithdraw": val}

@app.get("/api/stats")
async def gs():
    async with httpx.AsyncClient() as c: 
        data = await safe_get(c, f"{POS_URL}/stats", {})
        return {
            "total_pnl": data.get("daily_pnl", 0),
            "win_rate": data.get("win_rate", 0)
        }

@app.get("/api/positions")
async def gp():
    async with httpx.AsyncClient() as c: 
        # Il backend restituisce una lista, il JS vuole {"active": [...]}
        raw_list = await safe_get(c, f"{POS_URL}/get_open_positions", [])
        return {"active": raw_list}

@app.get("/api/ai")
async def gai():
    async with httpx.AsyncClient() as c: return await safe_get(c, f"{AI_URL}/latest_reasoning", {})

@app.get("/api/mgmt")
async def gmgmt():
    async with httpx.AsyncClient() as c: 
        # Il backend restituisce lista, JS vuole {"logs": [...]}
        raw_logs = await safe_get(c, f"{POS_URL}/management_logs", [])
        return {"logs": raw_logs}

@app.get("/api/history")
async def ghist():
    async with httpx.AsyncClient() as c: return await safe_get(c, f"{POS_URL}/equity_history", {"history":[]})

@app.post("/api/close_position")
async def cp(request: Request):
    try:
        data = await request.json()
        async with httpx.AsyncClient() as c:
            return (await c.post(f"{POS_URL}/close_position", json=data)).json()
    except Exception as e: return {"error": str(e)}

DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>MITRAGLIERE // V7.3</title>
    <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=JetBrains+Mono:wght@400;700&family=Orbitron:wght@900&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --neon-green: #00ff9d; --neon-red: #ff2a6d; --neon-blue: #00f3ff; --card-bg: rgba(12, 18, 24, 0.95); }
        body { background-color: #050505; color: #e0e0e0; font-family: 'Rajdhani', sans-serif; margin: 0; padding: 20px; min-height: 100vh; }
        
        /* LAYOUT */
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid #333; padding-bottom: 15px; }
        .logo { font-family: 'Orbitron'; font-size: 2rem; color: var(--neon-green); text-shadow: 0 0 15px rgba(0,255,157,0.3); }
        .status { font-family: 'JetBrains Mono'; font-size: 0.8rem; color: #888; border: 1px solid #333; padding: 5px 10px; border-radius: 4px; }
        
        .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
        .col-2 { grid-column: span 2; } .col-4 { grid-column: span 4; }
        
        .card { background: var(--card-bg); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; }
        .label { font-size: 0.75rem; color: #888; text-transform: uppercase; font-weight: 700; margin-bottom: 5px; }
        .val { font-family: 'JetBrains Mono'; font-size: 2.2rem; font-weight: 700; color: white; }
        .green { color: var(--neon-green); } .red { color: var(--neon-red); } .blue { color: var(--neon-blue); }
        
        /* ELEMENTS */
        .terminal { font-family: 'JetBrains Mono'; font-size: 0.75rem; height: 200px; overflow-y: auto; background: rgba(0,0,0,0.3); padding: 10px; border: 1px solid #222; }
        .log-entry { margin-bottom: 5px; border-bottom: 1px solid #222; padding-bottom: 5px; }
        .btn-kill { border: 1px solid var(--neon-red); color: var(--neon-red); background: transparent; padding: 5px; cursor: pointer; font-weight: bold; }
        
        @media(max-width: 900px) { .grid { grid-template-columns: 1fr; } .col-2, .col-4 { grid-column: span 1; } }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">MITRAGLIERE <span style="font-size:1rem; opacity:0.5; color:white;">// V7.3</span></div>
        <div class="status" id="sys-status">INIT...</div>
    </div>

    <div class="grid">
        <div class="card"><div class="label">NET EQUITY</div><div class="val" id="equity">----</div></div>
        <div class="card"><div class="label">AVAILABLE</div><div class="val blue" id="avail">----</div></div>
        <div class="card"><div class="label">SESSION PNL</div><div class="val" id="pnl">----</div></div>
        <div class="card"><div class="label">WIN RATE</div><div class="val green" id="wr">----</div></div>

        <div class="card col-4">
            <div class="label">ACTIVE ENGAGEMENTS</div>
            <div id="pos-box" style="display:flex; gap:10px; flex-wrap:wrap; margin-top:10px;">Scanning...</div>
        </div>

        <div class="card col-2"><div class="label">AI LOGS</div><div class="terminal" id="ai-box">...</div></div>
        <div class="card col-2"><div class="label">MANAGEMENT</div><div class="terminal" id="mgmt-box">...</div></div>
        <div class="card col-4"><div class="label">CHART</div><div style="height:250px"><canvas id="chart"></canvas></div></div>
    </div>

    <script>
        let chart = null;
        const sysStatus = document.getElementById('sys-status');
        
        try {
            if (typeof Chart !== 'undefined') {
                const ctx = document.getElementById('chart').getContext('2d');
                chart = new Chart(ctx, {
                    type: 'line',
                    data: { labels: [], datasets: [{ label: 'Equity', data: [], borderColor: '#00ff9d', tension: 0.2 }] },
                    options: { responsive: true, maintainAspectRatio: false, plugins:{legend:{display:false}}, scales:{x:{display:false}, y:{grid:{color:'#222'}}} }
                });
            }
        } catch (e) {}

        async function update() {
            // A. WALLET
            try {
                const r = await fetch('/api/wallet');
                const w = await r.json();
                document.getElementById('equity').innerText = '$' + (w.equity||0).toFixed(2);
                document.getElementById('avail').innerText = '$' + (w.availableToWithdraw||0).toFixed(2);
                sysStatus.innerText = "SYSTEM ONLINE"; sysStatus.style.color = "#00ff9d";
            } catch(e) {
                sysStatus.innerText = "CONN ERROR"; sysStatus.style.color = "#ff2a6d";
            }

            // B. STATS
            try {
                const s = await fetch('/api/stats').then(r=>r.json());
                const pnl = s.total_pnl || 0;
                const pnlEl = document.getElementById('pnl');
                pnlEl.innerText = (pnl>=0?'+':'') + '$' + pnl.toFixed(2);
                pnlEl.className = `val ${pnl>=0?'green':'red'}`;
                document.getElementById('wr').innerText = (s.win_rate||0) + '%';
            } catch(e) {}

            // C. POSITIONS
            try {
                const p = await fetch('/api/positions').then(r=>r.json());
                const pos = p.active || [];
                const pb = document.getElementById('pos-box');
                if(pos.length === 0) pb.innerHTML = '<span style="color:#555">NO POSITIONS</span>';
                else {
                    pb.innerHTML = pos.map(x => `
                        <div style="border:1px solid ${x.pnl>=0?'#00ff9d':'#ff2a6d'}; padding:10px; border-radius:5px;">
                            <b>${x.symbol}</b> ${x.side} <br>
                            <span style="font-size:1.2rem; color:${x.pnl>=0?'#00ff9d':'#ff2a6d'}">${x.pnl.toFixed(2)}$</span>
                        </div>
                    `).join('');
                }
            } catch(e) {}

            // D. LOGS
            try {
                const ai = await fetch('/api/ai').then(r=>r.json());
                if(ai.decisions) {
                    let h=''; for(const [k,v] of Object.entries(ai.decisions)) h+=`<div class="log-entry"><b style="color:#00f3ff">${k}</b>: ${v.decision}<br><small>${v.reasoning}</small></div>`;
                    document.getElementById('ai-box').innerHTML = h;
                }
                
                const mgmt = await fetch('/api/mgmt').then(r=>r.json());
                if(mgmt.logs && mgmt.logs.length>0) {
                     document.getElementById('mgmt-box').innerHTML = mgmt.logs.map(l=>`<div class="log-entry"><small>${l.time}</small> <b style="color:#00ff9d">${l.pair}</b>: ${l.action}</div>`).join('');
                }
            } catch(e) {}
        }

        setInterval(update, 3000);
        update();
    </script>
</body>
</html>'''

@app.get("/", response_class=HTMLResponse)
async def dashboard(): return DASHBOARD_HTML

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
