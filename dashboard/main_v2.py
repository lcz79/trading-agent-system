import os, json, httpx
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Trading Dashboard v2")

POS_MGR = os.getenv("POSITION_MANAGER_URL", "http://07_position_manager:8000")
LEARNING = os.getenv("LEARNING_AGENT_URL", "http://10_learning_agent:8000")
DATA_DIR = "/data"
API_COSTS_FILE = f"{DATA_DIR}/api_costs.json"
TRADING_HISTORY_FILE = f"{DATA_DIR}/trading_history.json"
EQUITY_SNAPSHOTS_FILE = f"{DATA_DIR}/equity_snapshots_v2.json"
STRATEGY_RULES_FILE = f"{DATA_DIR}/strategy_rules.json"
EVOLUTION_LOG_FILE = f"{DATA_DIR}/evolution_log.json"
MARKET_REGIME_FILE = f"{DATA_DIR}/market_regime.json"
TRADING_STATE_FILE = f"{DATA_DIR}/trading_state.json"
AI_DECISIONS_FILE = f"{DATA_DIR}/ai_decisions.json"

DEEPSEEK_INPUT_COST_PER_M = 0.27
DEEPSEEK_OUTPUT_COST_PER_M = 1.10
SIMULATED_FEE_PCT = float(os.getenv("SIMULATED_FEE_PCT", "0.07"))

# Use RESET_STARTING_DATE from .env, fallback to DASHBOARD_START_DATE
START_DATE = os.getenv("RESET_STARTING_DATE",
    os.getenv("DASHBOARD_START_DATE", "2026-01-28"))
START_BALANCE = float(os.getenv("RESET_STARTING_BALANCE", "50.0"))


def _safe_get(url, timeout=5):
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(url)
            return r.json() if r.status_code == 200 else {}
    except:
        return {}


def _read_json(path, default=None):
    try:
        if not os.path.exists(path):
            return default if default is not None else {}
        with open(path) as f:
            return json.load(f)
    except:
        return default if default is not None else {}


def get_api_costs():
    r = {"today": 0, "week": 0, "month": 0, "total": 0,
         "calls_today": 0, "calls_week": 0, "calls_month": 0, "calls_total": 0}
    try:
        data = _read_json(API_COSTS_FILE)
        calls = data.get("calls", [])
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        start = datetime.fromisoformat(START_DATE)
        for call in calls:
            try:
                ts = datetime.fromisoformat(call["timestamp"].replace("Z", ""))
                if ts < start:
                    continue
                cost = (call.get("tokens_in", 0) * DEEPSEEK_INPUT_COST_PER_M / 1e6 +
                        call.get("tokens_out", 0) * DEEPSEEK_OUTPUT_COST_PER_M / 1e6)
                r["total"] += cost; r["calls_total"] += 1
                if ts >= month_start: r["month"] += cost; r["calls_month"] += 1
                if ts >= week_start: r["week"] += cost; r["calls_week"] += 1
                if ts >= today_start: r["today"] += cost; r["calls_today"] += 1
            except:
                continue
    except:
        pass
    return r


def get_trade_history():
    try:
        trades = _read_json(TRADING_HISTORY_FILE, [])
        start = datetime.fromisoformat(START_DATE)
        filtered = [t for t in trades
                    if datetime.fromisoformat(t.get("timestamp", "2000-01-01")) >= start]
        return filtered
    except:
        return []


def get_equity_snapshots():
    try:
        data = _read_json(EQUITY_SNAPSHOTS_FILE, [])
        if not isinstance(data, list):
            return []
        return data
    except:
        return []


def get_market_regime():
    return _read_json(MARKET_REGIME_FILE)


def get_recent_ai_decisions():
    try:
        data = _read_json(AI_DECISIONS_FILE, [])
        if isinstance(data, list):
            return data[-20:]
        return []
    except:
        return []


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    p = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(p.read_text()) if p.exists() else HTMLResponse("<h1>Not found</h1>")


@app.get("/api/snapshot")
def api_snapshot():
    wallet = _safe_get(f"{POS_MGR}/get_wallet_balance")
    positions = _safe_get(f"{POS_MGR}/get_open_positions")
    api_costs = get_api_costs()
    all_trades = get_trade_history()
    equity = get_equity_snapshots()
    strategy = _read_json(STRATEGY_RULES_FILE)
    evolution = _read_json(EVOLUTION_LOG_FILE, [])
    if isinstance(evolution, list):
        evolution = evolution[-10:]
    regime = get_market_regime()
    ai_decisions = get_recent_ai_decisions()

    details = positions.get("details", [])

    # Calculate proper ROI for open positions
    for p in details:
        entry = float(p.get("entry_price", 0))
        mark = float(p.get("mark_price", 0))
        side = (p.get("side", "") or "").lower()
        lev_raw = str(p.get("leverage", "1"))
        lev = float("".join(c for c in lev_raw.split("x")[0] if c.isdigit() or c == ".") or "1")
        if entry > 0:
            if side == "long":
                p["roi_pct"] = round((mark - entry) / entry * lev * 100, 2)
            else:
                p["roi_pct"] = round((entry - mark) / entry * lev * 100, 2)
        else:
            p["roi_pct"] = 0.0

    total_pnl = sum(float(p.get("pnl", 0)) for p in details)
    winning = sum(1 for p in details if float(p.get("pnl", 0)) > 0)
    losing = sum(1 for p in details if float(p.get("pnl", 0)) < 0)

    # Simulated fees on open positions
    sim_fees_open = sum(
        SIMULATED_FEE_PCT / 100 * abs(float(p.get("entry_price", 0)) * float(p.get("size", 0)))
        for p in details
    )

    # Closed trade stats with dollar PnL
    closed_pnl_pct = 0
    closed_pnl_dollars = 0
    closed_wins = 0
    closed_losses = 0
    closed_fees_est = 0
    recent_trades = all_trades[-100:]  # show last 100 in table
    for t in all_trades:
        pnl = float(t.get("pnl_pct", 0))
        pnl_d = float(t.get("pnl_dollars", 0))
        if pnl > 0:
            closed_wins += 1
        elif pnl < 0:
            closed_losses += 1
        closed_pnl_pct += pnl
        closed_pnl_dollars += pnl_d
        # Estimate fees per trade
        size_pct = float(t.get("size_pct", 0.08))
        entry = float(t.get("entry_price", 0))
        # notional est
        notional = START_BALANCE * size_pct * entry if entry < 1 else START_BALANCE * size_pct
        closed_fees_est += notional * SIMULATED_FEE_PCT / 100

    equity_val = float(wallet.get("equity", 0))
    available = float(wallet.get("available_for_new_trades",
                      wallet.get("available", 0)))
    margin_used = float(wallet.get("components", {}).get("margin_used", 0))

    return JSONResponse({
        "timestamp": datetime.utcnow().isoformat(),
        "start_date": START_DATE,
        "start_balance": START_BALANCE,
        "wallet": {
            "equity": round(equity_val, 2),
            "available": round(available, 2),
            "margin_used": round(margin_used, 2),
            "pnl_vs_start": round(equity_val - START_BALANCE, 2) if equity_val > 0 else 0,
            "pnl_pct_vs_start": round((equity_val - START_BALANCE) / START_BALANCE * 100, 2) if equity_val > 0 else 0,
        },
        "positions": {
            "count": len(details),
            "details": details,
            "total_unrealized_pnl": round(total_pnl, 4),
            "winning": winning,
            "losing": losing,
            "simulated_fees_open": round(sim_fees_open, 4),
        },
        "market_regime": regime,
        "strategy_rules": strategy,
        "evolution_log": evolution,
        "api_costs": api_costs,
        "fee_config": {
            "simulated_fee_pct": SIMULATED_FEE_PCT,
            "description": f"{SIMULATED_FEE_PCT/2}% open + {SIMULATED_FEE_PCT/2}% close",
        },
        "trade_history": recent_trades,
        "trade_stats": {
            "total": len(all_trades),
            "wins": closed_wins,
            "losses": closed_losses,
            "win_rate": round(closed_wins / max(1, len(all_trades)) * 100, 1),
            "total_pnl_pct": round(closed_pnl_pct, 2),
            "total_pnl_dollars": round(closed_pnl_dollars, 2),
            "total_fees_est": round(closed_fees_est, 2),
        },
        "equity_history": equity[-500:],
        "ai_decisions": ai_decisions,
    })


@app.get("/api/health")
def health():
    services = {}
    checks = [
        ("position_manager", POS_MGR, "/get_wallet_balance"),
        ("learning_agent", LEARNING, "/health"),
    ]
    for name, url, path in checks:
        try:
            with httpx.Client(timeout=3) as c:
                r = c.get(f"{url}{path}")
                services[name] = "online" if r.status_code == 200 else "error"
        except:
            services[name] = "offline"
    return {"services": services}
