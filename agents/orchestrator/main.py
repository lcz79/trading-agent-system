import asyncio, httpx, json, os, uuid
from datetime import datetime
from confluence import calculate_confluence_both, calculate_limit_price
from hl_market_data import get_wyckoff_data

URLS = {
    "tech": "http://01_technical_analyzer:8000",
    "pos": "http://07_position_manager:8000",
    "ai": "http://04_master_ai_agent:8000",
    "learning": "http://10_learning_agent:8000",
    "fib": "http://03_fibonacci_agent:8000",
}
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "ADAUSDT", "SUIUSDT", "PEPEUSDT",
    "PAXGUSDT",
]
DISABLED_SYMBOLS = os.getenv("DISABLED_SYMBOLS", "").split(",")
DISABLED_SYMBOLS = [s.strip() for s in DISABLED_SYMBOLS if s.strip()]

# --- CONFIGURATION ---
MAX_POSITIONS = 10
MAX_SAME_DIRECTION = 6
CONFLUENCE_THRESHOLD = 65
REVERSE_THRESHOLD = float(os.getenv("REVERSE_THRESHOLD", "2.0"))
CRITICAL_LOSS_PCT_LEV = float(os.getenv("CRITICAL_LOSS_PCT_LEV", "12.0"))
CYCLE_INTERVAL = 60
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# LIMIT order settings
FORCE_LIMIT_ONLY = os.getenv("FORCE_LIMIT_ONLY", "true").lower() == "true"
SNIPER_BUFFER_PCT = float(os.getenv("SNIPER_BUFFER_PCT", "0.0008"))
LIMIT_ORDER_TTL_SEC = int(os.getenv("LIMIT_ORDER_TTL_SEC", "300"))
MAX_LIMIT_RESUBMISSIONS = int(os.getenv("MAX_LIMIT_RESUBMISSIONS", "2"))

# Risk management (ATR-based)
ATR_SL_MULTIPLIER = float(os.getenv("ATR_SL_MULTIPLIER", "1.5"))
ATR_TP_MULTIPLIER = float(os.getenv("ATR_TP_MULTIPLIER", "4.5"))
MIN_SIZE_PCT = float(os.getenv("MIN_SIZE_PCT", "0.06"))
MAX_SIZE_PCT = float(os.getenv("MAX_SIZE_PCT", "0.10"))
MIN_TP_PCT = float(os.getenv("MIN_TP_PCT", "0.35"))

# --- CRITICAL CLOSE CONFIRMATION STATE ---
pending_critical_closes = {}

# Deterministic leverage and size (NO LLM)
MIN_LEVERAGE = 2
MAX_LEVERAGE = 4

AI_DECISIONS_FILE = "/data/ai_decisions.json"

# --- EQUITY SNAPSHOTS & MARKET REGIME ---
EQUITY_SNAPSHOTS_FILE = "/data/equity_snapshots_v2.json"
MARKET_REGIME_FILE = "/data/market_regime.json"
_last_equity_snapshot = 0  # timestamp of last snapshot
EQUITY_SNAPSHOT_INTERVAL = 3600  # save every hour

def save_equity_snapshot(equity: float, margin_used: float, num_positions: int):
    """Save hourly equity snapshot for dashboard chart."""
    global _last_equity_snapshot
    import time as _time
    now = _time.time()
    if now - _last_equity_snapshot < EQUITY_SNAPSHOT_INTERVAL:
        return
    _last_equity_snapshot = now
    try:
        snapshots = []
        if os.path.exists(EQUITY_SNAPSHOTS_FILE):
            with open(EQUITY_SNAPSHOTS_FILE) as f:
                snapshots = json.load(f)
        if not isinstance(snapshots, list):
            snapshots = []
        snapshots.append({
            "timestamp": datetime.now().isoformat(),
            "equity": round(equity, 2),
            "margin_used": round(margin_used, 0),
            "positions": num_positions,
        })
        # Keep last 30 days (~720 hourly snapshots)
        snapshots = snapshots[-720:]
        with open(EQUITY_SNAPSHOTS_FILE, "w") as f:
            json.dump(snapshots, f)
    except Exception as e:
        print(f"Equity snapshot error: {e}")

def update_market_regime(tech_data_map: dict):
    """Update market regime based on BTC+ETH technical data."""
    try:
        btc = tech_data_map.get("BTCUSDT", {})
        eth = tech_data_map.get("ETHUSDT", {})
        if not btc and not eth:
            return

        btc_4h = btc.get("timeframes", {}).get("4h", {})
        eth_4h = eth.get("timeframes", {}).get("4h", {})

        # Simple regime detection
        btc_trend = btc_4h.get("ema_trend", "")
        btc_adx = float(btc_4h.get("adx", 0))
        eth_trend = eth_4h.get("ema_trend", "")

        bullish_signals = 0
        bearish_signals = 0

        if "bullish" in str(btc_trend).lower():
            bullish_signals += 2
        elif "bearish" in str(btc_trend).lower():
            bearish_signals += 2

        if "bullish" in str(eth_trend).lower():
            bullish_signals += 1
        elif "bearish" in str(eth_trend).lower():
            bearish_signals += 1

        if btc_adx > 25:
            if bullish_signals > bearish_signals:
                bullish_signals += 1
            else:
                bearish_signals += 1

        if bullish_signals >= 3:
            regime = "TRENDING_UP"
            confidence = min(90, 50 + bullish_signals * 10)
            prefer = "long"
        elif bearish_signals >= 3:
            regime = "TRENDING_DOWN"
            confidence = min(90, 50 + bearish_signals * 10)
            prefer = "short"
        elif bullish_signals > bearish_signals:
            regime = "RANGING_BULLISH"
            confidence = 50
            prefer = "long"
        elif bearish_signals > bullish_signals:
            regime = "RANGING_BEARISH"
            confidence = 50
            prefer = "short"
        else:
            regime = "RANGING"
            confidence = 40
            prefer = "none"

        regime_data = {
            "regime": regime,
            "confidence": confidence,
            "updated_at": datetime.now().isoformat(),
            "adjustments": {
                "threshold_modifier": 3.0 if "TRENDING" in regime else 0.0,
                "sl_multiplier": 1.2 if "TRENDING" in regime else 1.0,
                "tp_multiplier": 1.3 if "TRENDING" in regime else 1.0,
                "size_multiplier": 1.2 if confidence >= 70 else 1.0,
                "prefer_direction": prefer,
            },
        }
        with open(MARKET_REGIME_FILE, "w") as f:
            json.dump(regime_data, f, indent=2)
    except Exception as e:
        print(f"Market regime update error: {e}")

# --- CORRELATION GUARD ---
CORRELATED_PAIRS = {"BTCUSDT": "ETHUSDT", "ETHUSDT": "BTCUSDT"}

# --- CRASH GUARD ---
CRASH_GUARD_5M_LONG_BLOCK_PCT = float(os.getenv("CRASH_GUARD_5M_LONG_BLOCK_PCT", "0.6"))
CRASH_GUARD_5M_SHORT_BLOCK_PCT = float(os.getenv("CRASH_GUARD_5M_SHORT_BLOCK_PCT", "0.6"))

# --- COOLDOWN ---
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "900"))  # 15 min
_cooldown_tracker = {}  # {(symbol, direction): timestamp}

# --- PENDING ORDER TRACKER (prevents duplicate submissions) ---
_pending_orders = {}  # {symbol: timestamp_of_submission}
PENDING_ORDER_TTL = int(os.getenv("PENDING_ORDER_TTL", "600"))  # 10 min before allowing resubmission

# --- STRATEGY RULES (from learning agent reflection) ---
STRATEGY_RULES_FILE = "/data/strategy_rules.json"
_cached_strategy_rules = {}
_strategy_rules_mtime = 0

def load_strategy_rules() -> dict:
    """Load strategy rules from file. Caches and reloads on file change."""
    global _cached_strategy_rules, _strategy_rules_mtime
    import os as _os
    try:
        if not _os.path.exists(STRATEGY_RULES_FILE):
            return {}
        mtime = _os.path.getmtime(STRATEGY_RULES_FILE)
        if mtime != _strategy_rules_mtime:
            with open(STRATEGY_RULES_FILE) as f:
                import json as _json
                _cached_strategy_rules = _json.load(f)
                _strategy_rules_mtime = mtime
        # Stale check: if rules are older than 48h, ignore them
        from datetime import datetime as _dt, timedelta as _td
        updated = _cached_strategy_rules.get("updated_at", "")
        if updated:
            try:
                age = _dt.utcnow() - _dt.fromisoformat(updated)
                if age > _td(hours=48):
                    return {}
            except:
                pass
        return _cached_strategy_rules
    except:
        return {}

def is_blocked_by_rules(symbol: str, direction: str, hour: int, rules: dict) -> str:
    """Check if symbol/direction/hour is blocked. Returns reason or empty string."""
    r = rules.get("rules", {})
    # Normalize symbol for comparison (rules may use "BTC", orchestrator uses "BTCUSDT")
    sym_norm = symbol.replace("USDT", "").replace("USD", "").upper()
    # Symbol+direction blocks
    for block in r.get("symbol_direction_blocks", []):
        block_sym = block.get("symbol", "").replace("USDT", "").replace("USD", "").upper()
        if block_sym == sym_norm and block.get("direction") == direction:
            return f"STRATEGY_BLOCK: {symbol} {direction} blocked by reflection rules"
    # Hour restrictions
    if hour in r.get("hour_restrictions", []):
        return f"STRATEGY_BLOCK: hour {hour:02d}:00 blocked by reflection rules"
    return ""


# ---------------------------------------------------------------------------
# Deterministic tables (replace LLM decisions)
# ---------------------------------------------------------------------------

def deterministic_leverage(confluence_score: float) -> int:
    """Leverage from hardcoded table. No LLM involved."""
    if confluence_score >= 85:
        return 4
    elif confluence_score >= 80:
        return 4
    elif confluence_score >= 75:
        return 3
    elif confluence_score >= 70:
        return 3
    else:
        return 2


def deterministic_size(confluence_score: float) -> float:
    """Position size from hardcoded table. No LLM involved."""
    if confluence_score >= 85:
        return 0.25
    elif confluence_score >= 75:
        return 0.20
    else:
        return 0.15


# ---------------------------------------------------------------------------
# Risk gate checks
# ---------------------------------------------------------------------------

def check_correlation_guard(symbol: str, direction: str, position_details: list) -> bool:
    """Returns True if trade is ALLOWED, False if BLOCKED."""
    same_dir_count = 0
    for pos in position_details:
        pos_side = pos.get('side', '').lower()
        if pos_side == direction:
            same_dir_count += 1

    if same_dir_count >= MAX_SAME_DIRECTION:
        print(f"        CORRELATION GUARD: {same_dir_count} positions already {direction}, blocking {symbol}")
        return False

    correlated = CORRELATED_PAIRS.get(symbol)
    if correlated:
        for pos in position_details:
            if pos.get('symbol') == correlated and pos.get('side', '').lower() == direction:
                print(f"        CORRELATION GUARD: {correlated} already {direction}, blocking correlated {symbol}")
                return False

    return True


def check_cooldown(symbol: str, direction: str) -> bool:
    """Returns True if cooldown has passed, False if still cooling down."""
    key = (symbol, direction)
    last_close = _cooldown_tracker.get(key)
    if last_close is None:
        return True
    elapsed = (datetime.now() - last_close).total_seconds()
    if elapsed < COOLDOWN_SECONDS:
        print(f"        COOLDOWN: {symbol} {direction} closed {elapsed:.0f}s ago (need {COOLDOWN_SECONDS}s)")
        return False
    return True


def record_cooldown(symbol: str, direction: str):
    """Record a trade close for cooldown tracking."""
    _cooldown_tracker[(symbol, direction)] = datetime.now()


def has_pending_order(symbol: str) -> bool:
    """Check if there's a recent pending order for this symbol."""
    ts = _pending_orders.get(symbol)
    if ts is None:
        return False
    elapsed = (datetime.now() - ts).total_seconds()
    if elapsed > PENDING_ORDER_TTL:
        # Expired - remove and allow
        del _pending_orders[symbol]
        return False
    return True


def record_pending_order(symbol: str):
    """Record that an order was just submitted for this symbol."""
    _pending_orders[symbol] = datetime.now()


def clear_pending_order(symbol: str):
    """Clear pending order (e.g. when position is confirmed open or order failed)."""
    _pending_orders.pop(symbol, None)


def check_crash_guard(tech: dict, direction: str) -> bool:
    """Returns True if safe, False if crash/pump detected."""
    return_5m = tech.get('summary', {}).get('return_5m', 0)
    if direction == "long" and return_5m <= -CRASH_GUARD_5M_LONG_BLOCK_PCT:
        print(f"        CRASH GUARD: Blocked LONG (return_5m={return_5m:.2f}%)")
        return False
    if direction == "short" and return_5m >= CRASH_GUARD_5M_SHORT_BLOCK_PCT:
        print(f"        CRASH GUARD: Blocked SHORT (return_5m={return_5m:.2f}%)")
        return False
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import time
import random
import re


def parse_leverage(val) -> float:
    """Parse leverage from various formats: 3, '3', '3x', '3x (cross)', etc."""
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    m = re.match(r'(\d+\.?\d*)', s)
    if m:
        return float(m.group(1))
    return 1.0


async def async_post_with_retry(client, url, json_payload, timeout=30.0, attempts=3, base_sleep=1.0):
    last_exc = None
    for n in range(1, attempts + 1):
        try:
            return await client.post(url, json=json_payload, timeout=timeout)
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            retryable = any(x in msg for x in [
                "temporary failure in name resolution", "name resolution",
                "failed to establish a new connection", "connecterror",
                "connection refused", "timed out", "timeout"
            ])
            if (not retryable) or (n == attempts):
                raise
            sleep_s = (base_sleep * (2 ** (n - 1))) + random.uniform(0, 0.25)
            print(f"        Retry {n}/{attempts} POST {url}: {e} (sleep {sleep_s:.2f}s)")
            await asyncio.sleep(sleep_s)
    raise last_exc


def append_ai_decision_event(event: dict) -> None:
    event = dict(event or {})
    event.setdefault("timestamp", datetime.utcnow().isoformat())
    try:
        try:
            with open(AI_DECISIONS_FILE, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except (FileNotFoundError, Exception):
            data = []
        data.append(event)
        data = data[-500:]
        with open(AI_DECISIONS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"        Failed to write AI decision log: {e}")


async def fetch_learning_params(c: httpx.AsyncClient) -> dict:
    try:
        r = await c.get(f"{URLS['learning']}/current_params", timeout=5.0)
        if r.status_code == 200:
            return r.json() or {}
    except Exception as e:
        print(f"        Learning params fetch failed: {e}")
    return {}


def check_critical_close_confirmation(symbol: str, action_type: str) -> bool:
    global pending_critical_closes

    if action_type == "CLOSE":
        if symbol in pending_critical_closes:
            print(f"        CRITICAL CLOSE confirmed for {symbol} (2nd cycle)")
            del pending_critical_closes[symbol]
            return True
        else:
            print(f"        CRITICAL CLOSE pending for {symbol} (1st cycle, need confirmation)")
            pending_critical_closes[symbol] = datetime.now().isoformat()
            return False
    else:
        if symbol in pending_critical_closes:
            print(f"        CRITICAL CLOSE reset for {symbol}")
            del pending_critical_closes[symbol]
        return False


def save_monitoring_decision(positions_count: int, max_positions: int, positions_details: list, reason: str):
    try:
        decisions = []
        if os.path.exists(AI_DECISIONS_FILE):
            with open(AI_DECISIONS_FILE, 'r') as f:
                decisions = json.load(f)

        positions_summary = []
        for p in positions_details:
            pnl_pct = (p.get('pnl', 0) / (p.get('entry_price', 1) * p.get('size', 1))) * 100 if p.get('entry_price') else 0
            positions_summary.append({
                'symbol': p.get('symbol'), 'side': p.get('side'),
                'pnl': p.get('pnl'), 'pnl_pct': round(pnl_pct, 2)
            })

        decisions.append({
            'timestamp': datetime.now().isoformat(),
            'symbol': 'PORTFOLIO', 'action': 'HOLD', 'leverage': 0, 'size_pct': 0,
            'rationale': reason,
            'analysis_summary': f"Monitoring: {positions_count}/{max_positions} positions",
            'positions': positions_summary
        })
        decisions = decisions[-100:]

        os.makedirs(os.path.dirname(AI_DECISIONS_FILE), exist_ok=True)
        with open(AI_DECISIONS_FILE, 'w') as f:
            json.dump(decisions, f, indent=2)
    except Exception as e:
        print(f"Error saving monitoring decision: {e}")


def build_ohlcv_summary(tech: dict) -> dict:
    """Build compact OHLCV summary for Wyckoff LLM from technical data."""
    tfs = tech.get("timeframes", {})
    summary = {}
    for tf_name in ["15m", "1h", "4h", "1d"]:
        tf = tfs.get(tf_name, {})
        if not tf:
            continue
        summary[tf_name] = {
            "trend": tf.get("trend", "unknown"),
            "rsi": round(float(tf.get("rsi", 50)), 1),
            "macd": tf.get("macd", "neutral"),
            "macd_momentum": tf.get("macd_momentum", "flat"),
            "ema_20": tf.get("ema_20"),
            "ema_50": tf.get("ema_50"),
            "atr": tf.get("atr"),
            "price": tf.get("price"),
        }
        vol_key = f"volume_spike_{tf_name}"
        if tf.get(vol_key):
            summary[tf_name]["volume_spike"] = round(float(tf[vol_key]), 2)
    return summary


# ---------------------------------------------------------------------------
# Wyckoff analysis request
# ---------------------------------------------------------------------------

async def request_wyckoff_analysis(c: httpx.AsyncClient, symbol: str,
                                    tech: dict, fib: dict,
                                    wyckoff_data: dict) -> dict:
    """Call /analyze_wyckoff on Master AI Agent."""
    try:
        payload = {
            "symbol": symbol,
            "ohlcv_summary": build_ohlcv_summary(tech),
            "order_book": wyckoff_data.get("order_book"),
            "funding_rate": wyckoff_data.get("funding_rate"),
            "open_interest": wyckoff_data.get("open_interest"),
            "fibonacci": fib,
        }

        resp = await async_post_with_retry(
            c, f"{URLS['ai']}/analyze_wyckoff",
            json_payload=payload, timeout=30.0
        )

        if resp.status_code == 200:
            return resp.json()

    except Exception as e:
        print(f"        Wyckoff analysis failed: {e}")

    return {
        "market_phase": "UNCERTAIN",
        "phase_confidence": 0,
        "trade_proposal": {"direction": "NONE", "reasoning": "Analysis unavailable"},
        "journal_learning": "",
    }


# ---------------------------------------------------------------------------
# Direction agreement logic
# ---------------------------------------------------------------------------

def determine_confluence_direction(long_score: dict, short_score: dict) -> str:
    """Determine confluence direction. Returns 'long', 'short', or 'NONE'."""
    l_total = long_score.get("total", 0)
    s_total = short_score.get("total", 0)

    if l_total >= CONFLUENCE_THRESHOLD and l_total > s_total:
        return "long"
    if s_total >= CONFLUENCE_THRESHOLD and s_total > l_total:
        return "short"
    return "NONE"


# ---------------------------------------------------------------------------
# Manage cycle (position monitoring)
# ---------------------------------------------------------------------------

async def manage_cycle():
    async with httpx.AsyncClient() as c:
        for attempt in range(1, 4):
            try:
                await c.post(f"{URLS['pos']}/manage_active_positions", timeout=60)
                break
            except Exception as e:
                error_msg = str(e).lower()
                is_retryable = any(x in error_msg for x in ["timeout", "connection", "temporary"])
                if attempt == 3 or not is_retryable:
                    print(f"        manage_active_positions error (attempt {attempt}/3): {e}")
                    break
                wait_time = 2 ** (attempt - 1)
                print(f"        manage_active_positions retry {attempt}/3 after {wait_time}s: {e}")
                await asyncio.sleep(wait_time)


# ---------------------------------------------------------------------------
# Analysis cycle v2 (Wyckoff + Risk Gates)
# ---------------------------------------------------------------------------

async def analysis_cycle():
    async with httpx.AsyncClient(timeout=60) as c:
        learning_params = await fetch_learning_params(c)

        # 1. DATA COLLECTION
        portfolio = {}
        position_details = []
        active_symbols = []
        try:
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
            print(f"Data Error: {e}")
            return

        num_positions = len(active_symbols)

        # Save hourly equity snapshot for dashboard
        eq = float(portfolio.get("equity", portfolio.get("accountValue", 0)))
        mu = float(portfolio.get("margin_used", portfolio.get("components", {}).get("margin_used", 0)))
        if eq > 0:
            save_equity_snapshot(eq, mu, num_positions)

        # Clear pending orders for symbols that are now confirmed open
        for s in active_symbols:
            clear_pending_order(s)

        # Load strategy rules from learning agent
        sr = load_strategy_rules()
        sr_rules = sr.get("rules", {})
        sr_version = sr.get("version", 0)
        sr_blocks = sr_rules.get("symbol_direction_blocks", [])
        sr_hours = sr_rules.get("hour_restrictions", [])
        sr_conf_adj = sr_rules.get("confluence_threshold_adj", 0)
        sr_long_adj = sr_rules.get("long_penalty_adj", 0)
        sr_sl_adj = sr_rules.get("atr_sl_multiplier_adj", 0.0)
        sr_tp_adj = sr_rules.get("atr_tp_multiplier_adj", 0.0)

        effective_threshold = CONFLUENCE_THRESHOLD + sr_conf_adj

        print(f"\n[{datetime.now().strftime('%H:%M')}] Positions: {num_positions}/{MAX_POSITIONS}")
        if sr_version:
            print(f"        Strategy rules: v{sr_version}, {len(sr_blocks)} blocks, {len(sr_hours)} hour restrictions, conf_adj={sr_conf_adj:+d}, long_adj={sr_long_adj:+d}, sl_adj={sr_sl_adj:+.2f}, tp_adj={sr_tp_adj:+.2f}")


        # 2. CRITICAL LOSS CHECK
        positions_losing = []
        for pos in position_details:
            entry = pos.get('entry_price', 0)
            mark = pos.get('mark_price', 0)
            side = pos.get('side', '').lower()
            symbol = pos.get('symbol', '')
            leverage = parse_leverage(pos.get('leverage', 1))

            if entry > 0 and mark > 0:
                if side in ['long', 'buy']:
                    loss_pct = ((mark - entry) / entry) * leverage * 100
                else:
                    loss_pct = -((mark - entry) / entry) * leverage * 100

                if loss_pct < -CRITICAL_LOSS_PCT_LEV:
                    positions_losing.append({
                        'symbol': symbol, 'loss_pct': loss_pct, 'side': side,
                        'entry_price': entry, 'mark_price': mark, 'leverage': leverage,
                        'size': pos.get('size', 0), 'pnl': pos.get('pnl', 0)
                    })

        # CRITICAL MANAGEMENT
        if positions_losing:
            print(f"        CRITICAL: {len(positions_losing)} positions below threshold ({CRITICAL_LOSS_PCT_LEV:.1f}%)")
            for pos_loss in positions_losing:
                print(f"        {pos_loss['symbol']} {pos_loss['side']}: {pos_loss['loss_pct']:.2f}%")

            try:
                critical_positions = [{
                    "symbol": pl['symbol'], "side": pl['side'],
                    "entry_price": pl['entry_price'], "mark_price": pl['mark_price'],
                    "leverage": pl['leverage'], "size": pl.get('size', 0),
                    "pnl": pl.get('pnl', 0), "is_disabled": pl['symbol'] in DISABLED_SYMBOLS
                } for pl in positions_losing]

                mgmt_resp = await async_post_with_retry(c, f"{URLS['ai']}/manage_critical_positions", json_payload={
                    "positions": critical_positions,
                    "portfolio_snapshot": portfolio,
                    "learning_params": learning_params,
                }, timeout=60.0)

                if mgmt_resp.status_code == 200:
                    mgmt_data = mgmt_resp.json()
                    actions = mgmt_data.get('actions', [])
                    meta = mgmt_data.get('meta', {})
                    print(f"        MGMT: {len(actions)} actions, {meta.get('processing_time_ms', 0)}ms")
                    append_ai_decision_event({"type": "CRITICAL_MANAGEMENT", "status": "MGMT_RESPONSE"})

                    if not DRY_RUN:
                        for act in actions:
                            action_type = act.get('action')
                            symbol = act.get('symbol')

                            if action_type in ("CLOSE", "REVERSE"):
                                if action_type == "REVERSE":
                                    print(f"        REVERSE -> CLOSE for {symbol}")
                                should_execute = check_critical_close_confirmation(symbol, "CLOSE")
                                if should_execute:
                                    print(f"        Closing {symbol}...")
                                    try:
                                        close_resp = await c.post(f"{URLS['pos']}/close_position", json={"symbol": symbol}, timeout=20.0)
                                        print(f"        Close: {close_resp.json()}")
                                    except Exception as e:
                                        print(f"        Close error: {e}")
                            elif action_type == "HOLD":
                                check_critical_close_confirmation(symbol, "HOLD")
                                print(f"        Holding {symbol}")

                    append_ai_decision_event({"type": "CRITICAL_MANAGEMENT", "status": "COMPLETED"})
                    print(f"        Critical management done, skipping new positions")
                    return
                else:
                    print(f"        MGMT failed: {mgmt_resp.status_code}")
            except Exception as e:
                print(f"        Critical management error: {e}")

        # CASE 1: All slots full
        if num_positions >= MAX_POSITIONS:
            all_positions_status = []
            for pos in position_details:
                entry = pos.get('entry_price', 0)
                mark = pos.get('mark_price', 0)
                side = pos.get('side', '').lower()
                symbol = pos.get('symbol', '').replace('USDT', '')
                leverage = parse_leverage(pos.get('leverage', 1))
                if entry > 0 and mark > 0:
                    if side in ['long', 'buy']:
                        pnl_pct = ((mark - entry) / entry) * leverage * 100
                    else:
                        pnl_pct = -((mark - entry) / entry) * leverage * 100
                    all_positions_status.append(f"{symbol}: {pnl_pct:+.2f}%")

            positions_str = " | ".join(all_positions_status)
            print(f"        All slots full - {positions_str}")
            save_monitoring_decision(len(position_details), MAX_POSITIONS, position_details, f"Full: {positions_str}")
            return

        # CASE 2: Free slots - WYCKOFF + CONFLUENCE ANALYSIS
        print(f"        Free slot - running Wyckoff + Confluence analysis")

        # Filter out symbols with open positions AND symbols with recent pending orders
        scan_list = []
        for s in SYMBOLS:
            if s in active_symbols:
                continue
            if has_pending_order(s):
                print(f"        {s}: skipped (pending order, waiting for fill)")
                continue
            scan_list.append(s)

        if not scan_list:
            print("        No assets available for scan")
            return

        # Check margin
        available_for_new = portfolio.get('available_for_new_trades', portfolio.get('available', 0))
        if available_for_new < 10.0:
            print(f"        BLOCKED: Insufficient margin: {available_for_new:.2f} USDT")
            return

        # Fetch technical + fibonacci data for all candidates
        tech_data_map = {}
        fib_data_map = {}

        for s in scan_list:
            try:
                tech_resp, fib_resp = await asyncio.gather(
                    c.post(f"{URLS['tech']}/analyze_multi_tf_full", json={"symbol": s}),
                    c.post(f"{URLS['fib']}/analyze_fib", json={"symbol": s}),
                    return_exceptions=True
                )
                if hasattr(tech_resp, 'json'):
                    tech_data_map[s] = tech_resp.json()
                if hasattr(fib_resp, 'json'):
                    fib_data_map[s] = fib_resp.json()
            except Exception as e:
                print(f"        Data fetch failed for {s}: {e}")

        if not tech_data_map:
            print("        No technical data available")
            return

        # Calculate confluence scores for all candidates
        best_candidate = None
        best_score = 0

        for sym in scan_list:
            tech = tech_data_map.get(sym, {})
            fib = fib_data_map.get(sym, {})

            if not tech.get("timeframes"):
                continue

            long_score, short_score = calculate_confluence_both(tech, fib)

            print(f"        {sym}: LONG={long_score['total']:.1f} SHORT={short_score['total']:.1f}")
            print(f"           L: trend={long_score['trend_alignment']:.0f} mom={long_score['momentum']:.0f} mr={long_score['mean_reversion']:.0f} vol={long_score['volume']:.0f} lvl={long_score['key_levels']:.0f}")
            print(f"           S: trend={short_score['trend_alignment']:.0f} mom={short_score['momentum']:.0f} mr={short_score['mean_reversion']:.0f} vol={short_score['volume']:.0f} lvl={short_score['key_levels']:.0f}")

            # Pick the best direction for this symbol
            confluence_dir = determine_confluence_direction(long_score, short_score)
            if confluence_dir == "NONE":
                continue

            score = long_score if confluence_dir == "long" else short_score

            # --- STRATEGY RULE CHECKS ---
            block_reason = is_blocked_by_rules(sym, confluence_dir, datetime.now().hour, sr)
            if block_reason:
                print(f"        {sym}: {block_reason}")
                continue

            # Apply long penalty from strategy rules
            effective_score = score['total']
            if confluence_dir == "long" and sr_long_adj > 0:
                effective_score -= sr_long_adj
                if effective_score < effective_threshold:
                    print(f"        {sym}: LONG penalty applied ({sr_long_adj:+d}), effective={effective_score:.1f} < {effective_threshold}")
                    continue

            # Check against effective threshold (base + strategy adj)
            if effective_score < effective_threshold:
                continue

            if effective_score > best_score:
                if check_correlation_guard(sym, confluence_dir, position_details):
                    best_candidate = {
                        "symbol": sym,
                        "direction": confluence_dir,
                        "action": f"OPEN_{confluence_dir.upper()}",
                        "confluence": score,
                        "long_score": long_score,
                        "short_score": short_score,
                        "tech": tech,
                        "fib": fib
                    }
                    best_score = effective_score

        # Update market regime from tech data
        update_market_regime(tech_data_map)

        if not best_candidate:
            print(f"        No symbol meets confluence threshold ({effective_threshold})")
            append_ai_decision_event({
                "type": "DETERMINISTIC_SCAN", "action": "HOLD",
                "rationale": f"No symbol reached effective threshold >= {effective_threshold}"
            })
            return

        sym = best_candidate["symbol"]
        direction = best_candidate["direction"]
        action = best_candidate["action"]
        confluence = best_candidate["confluence"]
        tech = best_candidate["tech"]
        fib = best_candidate["fib"]

        print(f"        BEST: {sym} {direction.upper()} score={confluence['total']:.1f}")

        # --- RISK GATE 1: Cooldown ---
        if not check_cooldown(sym, direction):
            append_ai_decision_event({
                "type": "RISK_GATE_BLOCK", "symbol": sym, "action": "HOLD",
                "gate": "COOLDOWN", "confluence_score": confluence['total']
            })
            return

        # --- RISK GATE 2: Crash Guard ---
        if not check_crash_guard(tech, direction):
            append_ai_decision_event({
                "type": "RISK_GATE_BLOCK", "symbol": sym, "action": "HOLD",
                "gate": "CRASH_GUARD", "confluence_score": confluence['total']
            })
            return

        # --- WYCKOFF ANALYSIS (LLM) ---
        print(f"        Requesting Wyckoff analysis for {sym}...")
        wyckoff_data = get_wyckoff_data(sym)
        wyckoff_result = await request_wyckoff_analysis(c, sym, tech, fib, wyckoff_data)

        llm_direction = wyckoff_result.get("trade_proposal", {}).get("direction", "NONE").lower()
        llm_phase = wyckoff_result.get("market_phase", "UNCERTAIN")
        phase_confidence = wyckoff_result.get("phase_confidence", 0)
        llm_reasoning = wyckoff_result.get("trade_proposal", {}).get("reasoning", "")
        journal_learning = wyckoff_result.get("journal_learning", "")

        print(f"        Wyckoff: phase={llm_phase} conf={phase_confidence} dir={llm_direction}")
        print(f"        Reasoning: {llm_reasoning[:120]}")
        if journal_learning:
            print(f"        Journal: {journal_learning[:120]}")

        # --- RISK GATE 3: Direction Agreement ---
        if llm_direction == direction:
            # AGREEMENT - proceed
            print(f"        AGREEMENT: Confluence={direction} == Wyckoff={llm_direction}")

        elif llm_direction == "none" or llm_direction == "NONE":
            # LLM uncertain - proceed ONLY if confluence >= 75
            if confluence['total'] < 75:
                print(f"        BLOCKED: LLM uncertain, confluence {confluence['total']:.1f} < 75")
                append_ai_decision_event({
                    "type": "DIRECTION_DISAGREEMENT", "symbol": sym, "action": "HOLD",
                    "confluence_direction": direction, "wyckoff_direction": "NONE",
                    "confluence_score": confluence['total'], "market_phase": llm_phase,
                    "rationale": f"LLM uncertain (phase={llm_phase}), confluence < 75"
                })
                return
            else:
                print(f"        LLM uncertain but confluence {confluence['total']:.1f} >= 75, proceeding")

        else:
            # LLM says OPPOSITE direction - VETO (always block)
            print(f"        BLOCKED: Confluence={direction} vs Wyckoff={llm_direction}")
            append_ai_decision_event({
                "type": "DIRECTION_DISAGREEMENT", "symbol": sym, "action": "HOLD",
                "confluence_direction": direction, "wyckoff_direction": llm_direction,
                "confluence_score": confluence['total'], "market_phase": llm_phase,
                "rationale": f"Direction conflict: confluence={direction}, Wyckoff={llm_direction}"
            })
            return

        # --- DETERMINISTIC PARAMETERS (NO LLM) ---
        leverage = deterministic_leverage(confluence['total'])
        size_pct = deterministic_size(confluence['total'])

        # Clamp
        leverage = max(MIN_LEVERAGE, min(MAX_LEVERAGE, leverage))
        size_pct = max(MIN_SIZE_PCT, min(MAX_SIZE_PCT, size_pct))

        # ATR-based SL/TP
        tf_15m = tech.get("timeframes", {}).get("15m", {})
        atr = float(tf_15m.get("atr", 0))
        price = float(tf_15m.get("price", 0))

        if atr > 0 and price > 0:
            sl_pct = ((ATR_SL_MULTIPLIER + sr_sl_adj) * atr) / price
            tp_pct = ((ATR_TP_MULTIPLIER + sr_tp_adj) * atr) / price
        else:
            sl_pct = 0.02
            tp_pct = 0.03

        # --- FEE PROFITABILITY FILTER ---
        if tp_pct * 100 < MIN_TP_PCT:
            print(f"        FEE_FILTER: {sym} {direction.upper()} TP={tp_pct*100:.2f}% < min {MIN_TP_PCT}% (not profitable after fees)")
            append_ai_decision_event({
                "type": "FEE_FILTER_BLOCK", "symbol": sym, "action": "HOLD",
                "tp_pct": tp_pct * 100, "min_tp_pct": MIN_TP_PCT,
                "rationale": f"TP {tp_pct*100:.2f}% too small, would lose money to fees"
            })
            return

        # Calculate limit entry price
        entry_price = calculate_limit_price(price, direction, tech, fib, SNIPER_BUFFER_PCT)

        intent_id = str(uuid.uuid4())

        print(f"        EXECUTING {action} on {sym} [intent:{intent_id[:8]}]")
        print(f"           Leverage={leverage}x Size={size_pct*100:.0f}% SL={sl_pct*100:.2f}% TP={tp_pct*100:.2f}%")
        print(f"           Confluence={confluence['total']:.1f} Limit={entry_price:.2f} (market={price:.2f})")
        print(f"           Wyckoff: phase={llm_phase} conf={phase_confidence} dir={llm_direction}")

        # Log decision
        append_ai_decision_event({
            "type": "WYCKOFF_ENTRY", "symbol": sym, "action": action,
            "leverage": leverage, "size_pct": size_pct,
            "confluence_score": confluence['total'], "confluence_breakdown": confluence,
            "entry_price": entry_price, "sl_pct": sl_pct, "tp_pct": tp_pct,
            "wyckoff_phase": llm_phase, "wyckoff_confidence": phase_confidence,
            "wyckoff_direction": llm_direction, "wyckoff_reasoning": llm_reasoning[:200],
            "journal_learning": journal_learning[:200],
            "rationale": f"Confluence {confluence['total']:.0f} + Wyckoff {llm_phase} agree on {direction}. "
                         f"Deterministic: lev={leverage}x size={size_pct*100:.0f}% LIMIT @ {entry_price:.2f}"
        })

        if DRY_RUN:
            print(f"        DRY_RUN: not executing")
            return

        # Build payload
        payload = {
            "symbol": sym,
            "side": action,
            "leverage": leverage,
            "size_pct": size_pct,
            "intent_id": intent_id,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
        }

        try:
            res = await c.post(f"{URLS['pos']}/open_position", json=payload)
            result = res.json()
            print(f"        Result: {result}")

            # Track pending order to prevent duplicate submissions
            record_pending_order(sym)

        except Exception as e:
            print(f"        Execution error: {e}")


async def main_loop():
    while True:
        await manage_cycle()
        await analysis_cycle()
        await asyncio.sleep(CYCLE_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main_loop())
