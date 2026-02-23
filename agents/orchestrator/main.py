import asyncio, httpx, json, os, uuid
from datetime import datetime
from confluence import calculate_confluence_both, calculate_limit_price
import re

def parse_leverage(val) -> float:
    """Parse leverage from various formats like 3, "3x", "3x (cross)", etc."""
    if isinstance(val, (int, float)):
        return max(1.0, float(val))
    s = str(val).strip()
    m = re.match(r"([d.]+)", s)
    if m:
        return max(1.0, float(m.group(1)))
    return 1.0

URLS = {
    "tech": "http://01_technical_analyzer:8000",
    "pos": "http://07_position_manager:8000",
    "ai": "http://04_master_ai_agent:8000",
    "learning": "http://10_learning_agent:8000",
    "fib": "http://03_fibonacci_agent:8000",
}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "AVAXUSDT", "SUIUSDT", "BNBUSDT"]
DISABLED_SYMBOLS = os.getenv("DISABLED_SYMBOLS", "").split(",")
DISABLED_SYMBOLS = [s.strip() for s in DISABLED_SYMBOLS if s.strip()]

# --- CONFIGURATION ---
MAX_POSITIONS = 3
MAX_SAME_DIRECTION = 2  # Phase 7: max positions in same direction
CONFLUENCE_THRESHOLD = 65  # Minimum score to open a position
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
ATR_SL_MULTIPLIER = float(os.getenv("ATR_SL_MULTIPLIER", "2.0"))
ATR_TP_MULTIPLIER = float(os.getenv("ATR_TP_MULTIPLIER", "3.0"))
MIN_SIZE_PCT = float(os.getenv("MIN_SIZE_PCT", "0.06"))
MAX_SIZE_PCT = float(os.getenv("MAX_SIZE_PCT", "0.10"))

# --- CRITICAL CLOSE CONFIRMATION STATE ---
pending_critical_closes = {}

# AI params range (for leverage validation from DeepSeek)
MIN_LEVERAGE = 2
MAX_LEVERAGE = 5

AI_DECISIONS_FILE = "/data/ai_decisions.json"

# --- CORRELATION GUARD (Phase 7) ---
# BTC and ETH are correlated: max 1 of each in same direction
CORRELATED_PAIRS = {"BTCUSDT": "ETHUSDT", "ETHUSDT": "BTCUSDT"}


def check_correlation_guard(symbol: str, direction: str, position_details: list) -> bool:
    """
    Phase 7: Correlation guard.
    Returns True if trade is ALLOWED, False if BLOCKED.

    Rules:
    - Max 2 positions in same direction total
    - BTC and ETH count as correlated: max 1 of each in same direction
    """
    same_dir_count = 0
    for pos in position_details:
        pos_side = pos.get('side', '').lower()
        if pos_side == direction:
            same_dir_count += 1

    if same_dir_count >= MAX_SAME_DIRECTION:
        print(f"        🚫 CORRELATION GUARD: {same_dir_count} positions already {direction}, blocking {symbol}")
        return False

    # Check BTC/ETH correlation
    correlated = CORRELATED_PAIRS.get(symbol)
    if correlated:
        for pos in position_details:
            if pos.get('symbol') == correlated and pos.get('side', '').lower() == direction:
                print(f"        🚫 CORRELATION GUARD: {correlated} already {direction}, blocking correlated {symbol}")
                return False

    return True


def validate_ai_params(leverage: float, size_pct: float, symbol: str = "") -> tuple:
    """Validate leverage and size_pct. Clamp to safe ranges."""
    warnings = []
    had_warnings = False

    if leverage < MIN_LEVERAGE:
        warnings.append(f"leverage {leverage:.1f} < {MIN_LEVERAGE}, clamped")
        leverage = MIN_LEVERAGE
    elif leverage > MAX_LEVERAGE:
        warnings.append(f"leverage {leverage:.1f} > {MAX_LEVERAGE}, clamped")
        leverage = MAX_LEVERAGE

    if size_pct < MIN_SIZE_PCT:
        warnings.append(f"size_pct {size_pct:.3f} < {MIN_SIZE_PCT}, clamped")
        size_pct = MIN_SIZE_PCT
    elif size_pct > MAX_SIZE_PCT:
        warnings.append(f"size_pct {size_pct:.3f} > {MAX_SIZE_PCT}, clamped")
        size_pct = MAX_SIZE_PCT

    if warnings:
        had_warnings = True
        print(f"        ⚠️ Param validation for {symbol}: {'; '.join(warnings)}")

    return leverage, size_pct, had_warnings


async def fetch_learning_params(c: httpx.AsyncClient) -> dict:
    """Fetch evolved params from learning agent. Best-effort: returns {} on failure."""
    try:
        r = await c.get(f"{URLS['learning']}/current_params", timeout=5.0)
        if r.status_code == 200:
            return r.json() or {}
    except Exception as e:
        print(f"        ⚠️ Learning params fetch failed: {e}")
    return {}


import time
import random


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
            print(f"        ⏳ Retry {n}/{attempts} POST {url}: {e} (sleep {sleep_s:.2f}s)")
            await asyncio.sleep(sleep_s)
    raise last_exc


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
        print(f"⚠️ Error saving monitoring decision: {e}")


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
        print(f"        ⚠️ Failed to write AI decision log: {e}")


AI_TRADE_LOG = "/data/ai_trade_log.json"

def write_dashboard_cycle_log(portfolio: dict, position_details: list, decisions: list, symbols_analyzed: int, processing_ms: int = 0) -> None:
    """Write a cycle summary to ai_trade_log.json in the format dashboard_v2 expects."""
    try:
        longs = sum(1 for p in position_details if str(p.get("side", "")).lower() in ("long", "buy"))
        shorts = sum(1 for p in position_details if str(p.get("side", "")).lower() in ("short", "sell"))
        positions = []
        for p in position_details:
            pnl = float(p.get("pnl", 0))
            entry = float(p.get("entry_price", 0))
            size = float(p.get("size", 0))
            notional = entry * size if entry and size else 1
            roi_pct = (pnl / notional * 100) if notional > 0 else 0
            positions.append({
                "symbol": p.get("symbol", "?"),
                "side": str(p.get("side", "?")).lower(),
                "roi_pct": round(roi_pct, 2)
            })
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "portfolio": {
                "equity": round(float(portfolio.get("equity", 0)), 2),
                "available": round(float(portfolio.get("available_for_new_trades", portfolio.get("available", 0))), 2),
                "longs": longs,
                "shorts": shorts,
                "positions": positions
            },
            "decisions": decisions,
            "symbols_analyzed": symbols_analyzed,
            "processing_ms": processing_ms
        }
        try:
            with open(AI_TRADE_LOG, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except (FileNotFoundError, Exception):
            data = []
        data.append(entry)
        data = data[-200:]
        with open(AI_TRADE_LOG, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"        Warning: Failed to write dashboard trade log: {e}")


def check_critical_close_confirmation(symbol: str, action_type: str) -> bool:
    global pending_critical_closes

    if action_type == "CLOSE":
        if symbol in pending_critical_closes:
            print(f"        ✅ CRITICAL CLOSE confirmed for {symbol} (2nd cycle)")
            del pending_critical_closes[symbol]
            return True
        else:
            print(f"        ⏸️ CRITICAL CLOSE pending for {symbol} (1st cycle, need confirmation)")
            pending_critical_closes[symbol] = datetime.now().isoformat()
            return False
    else:
        if symbol in pending_critical_closes:
            print(f"        🔄 CRITICAL CLOSE reset for {symbol}")
            del pending_critical_closes[symbol]
        return False


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
                    print(f"        ⚠️ manage_active_positions error (attempt {attempt}/3): {e}")
                    break
                wait_time = 2 ** (attempt - 1)
                print(f"        ⏳ manage_active_positions retry {attempt}/3 after {wait_time}s: {e}")
                await asyncio.sleep(wait_time)


async def request_leverage_from_ai(c: httpx.AsyncClient, symbol: str, direction: str,
                                    confluence_score: float, portfolio: dict,
                                    num_positions: int, learning_params: dict) -> dict:
    """
    Phase 4: Ask DeepSeek ONLY for leverage selection + optional veto.
    Returns {"leverage": 3, "veto": false, "reason": "..."}
    """
    try:
        payload = {
            "symbol": symbol,
            "direction": direction,
            "confluence_score": confluence_score,
            "equity": portfolio.get("equity", 0),
            "available_for_new_trades": portfolio.get("available_for_new_trades", 0),
            "positions_open": num_positions,
            "max_positions": MAX_POSITIONS,
            "learning_params": learning_params,
        }
        resp = await async_post_with_retry(
            c, f"{URLS['ai']}/select_leverage",
            json_payload=payload, timeout=30.0
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"        ⚠️ Leverage AI call failed: {e}, using default")

    # Fallback: deterministic leverage based on confluence score
    if confluence_score >= 80:
        lev = 4
    elif confluence_score >= 70:
        lev = 3
    else:
        lev = 2
    return {"leverage": lev, "veto": False, "reason": "fallback_deterministic"}


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
            print(f"⚠️ Data Error: {e}")
            return

        num_positions = len(active_symbols)
        print(f"\n[{datetime.now().strftime('%H:%M')}] 📊 Positions: {num_positions}/{MAX_POSITIONS}")

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
            print(f"        🔥 CRITICAL: {len(positions_losing)} positions below threshold ({CRITICAL_LOSS_PCT_LEV:.1f}%)")
            for pos_loss in positions_losing:
                print(f"        ⚠️ {pos_loss['symbol']} {pos_loss['side']}: {pos_loss['loss_pct']:.2f}%")

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
                    print(f"        ✅ MGMT: {len(actions)} actions, {meta.get('processing_time_ms', 0)}ms")
                    append_ai_decision_event({"type": "CRITICAL_MANAGEMENT", "status": "MGMT_RESPONSE"})

                    if not DRY_RUN:
                        for act in actions:
                            action_type = act.get('action')
                            symbol = act.get('symbol')

                            if action_type in ("CLOSE", "REVERSE"):
                                if action_type == "REVERSE":
                                    print(f"        ⏸️ REVERSE -> CLOSE for {symbol}")
                                should_execute = check_critical_close_confirmation(symbol, "CLOSE")
                                if should_execute:
                                    print(f"        🔒 Closing {symbol}...")
                                    try:
                                        close_resp = await c.post(f"{URLS['pos']}/close_position", json={"symbol": symbol}, timeout=20.0)
                                        print(f"        ✅ Close: {close_resp.json()}")
                                    except Exception as e:
                                        print(f"        ❌ Close error: {e}")
                            elif action_type == "HOLD":
                                check_critical_close_confirmation(symbol, "HOLD")
                                print(f"        ⏸️ Holding {symbol}")

                    append_ai_decision_event({"type": "CRITICAL_MANAGEMENT", "status": "COMPLETED"})
                    print(f"        🛑 Critical management done, skipping new positions")
                    return
                else:
                    print(f"        ❌ MGMT failed: {mgmt_resp.status_code}")
            except Exception as e:
                print(f"        ❌ Critical management error: {e}")

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
            print(f"        ✅ All slots full - {positions_str}")
            save_monitoring_decision(len(position_details), MAX_POSITIONS, position_details, f"Full: {positions_str}")
            return

        # CASE 2: Free slots - DETERMINISTIC ENTRY LOGIC (Phase 2)
        print(f"        🔍 Free slot - running deterministic confluence analysis")

        scan_list = [s for s in SYMBOLS if s not in active_symbols]
        if not scan_list:
            print("        ⚠️ No assets available for scan")
            return

        # Check margin
        available_for_new = portfolio.get('available_for_new_trades', portfolio.get('available', 0))
        if available_for_new < 10.0:
            print(f"        🚫 Insufficient margin: {available_for_new:.2f} USDT")
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
                print(f"        ⚠️ Data fetch failed for {s}: {e}")

        if not tech_data_map:
            print("        ⚠️ No technical data available")
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

            print(f"        📊 {sym}: LONG={long_score['total']:.1f} SHORT={short_score['total']:.1f}")
            print(f"           L: trend={long_score['trend_alignment']:.0f} mom={long_score['momentum']:.0f} mr={long_score['mean_reversion']:.0f} vol={long_score['volume']:.0f} lvl={long_score['key_levels']:.0f}")
            print(f"           S: trend={short_score['trend_alignment']:.0f} mom={short_score['momentum']:.0f} mr={short_score['mean_reversion']:.0f} vol={short_score['volume']:.0f} lvl={short_score['key_levels']:.0f}")

            # Pick the best direction for this symbol
            if long_score['total'] >= CONFLUENCE_THRESHOLD and long_score['total'] > short_score['total']:
                if long_score['total'] > best_score:
                    if check_correlation_guard(sym, "long", position_details):
                        best_candidate = {
                            "symbol": sym, "direction": "long", "action": "OPEN_LONG",
                            "confluence": long_score, "tech": tech, "fib": fib
                        }
                        best_score = long_score['total']

            if short_score['total'] >= CONFLUENCE_THRESHOLD and short_score['total'] > long_score['total']:
                if short_score['total'] > best_score:
                    if check_correlation_guard(sym, "short", position_details):
                        best_candidate = {
                            "symbol": sym, "direction": "short", "action": "OPEN_SHORT",
                            "confluence": short_score, "tech": tech, "fib": fib
                        }
                        best_score = short_score['total']

        if not best_candidate:
            print(f"        ℹ️ No symbol meets confluence threshold ({CONFLUENCE_THRESHOLD})")
            append_ai_decision_event({
                "type": "DETERMINISTIC_SCAN", "action": "HOLD",
                "rationale": f"No symbol reached confluence >= {CONFLUENCE_THRESHOLD}"
            })
            write_dashboard_cycle_log(portfolio, position_details, [], len(scan_list))
            return

        # We have a candidate - send to DeepSeek for full analysis (Phase 2+4)
        sym = best_candidate["symbol"]
        direction = best_candidate["direction"]
        confluence = best_candidate["confluence"]
        tech = best_candidate["tech"]
        fib = best_candidate["fib"]

        print(f"        🎯 BEST: {sym} {direction.upper()} score={confluence['total']:.1f}")
        print(f"        🤖 Sending to DeepSeek for full analysis...")

        # Build payload for /decide_batch
        enhanced_global_data = {
            "portfolio": portfolio,
            "already_open": active_symbols,
            "max_positions": MAX_POSITIONS,
            "positions_open_count": num_positions,
        }
        if position_details:
            total_pnl = sum(p.get('pnl', 0) for p in position_details)
            equity = portfolio.get('equity', 1)
            if equity > 0:
                enhanced_global_data['drawdown_pct'] = (total_pnl / equity) * 100

        ai_payload = {
            "learning_params": learning_params,
            "global_data": enhanced_global_data,
            "assets_data": {sym: {"tech": tech}},
        }

        try:
            ai_resp = await async_post_with_retry(
                c, f"{URLS['ai']}/decide_batch",
                json_payload=ai_payload, timeout=60.0
            )
            if ai_resp.status_code != 200:
                print(f"        ⚠️ DeepSeek returned {ai_resp.status_code}")
                return
            ai_data = ai_resp.json()
        except Exception as e:
            print(f"        ⚠️ DeepSeek call failed: {e}")
            return

        decisions = ai_data.get("decisions", [])
        if not decisions:
            print("        ⚠️ DeepSeek returned no decisions")
            return

        decision = decisions[0]
        action = decision.get("action", "HOLD")
        blocked_by = decision.get("blocked_by", [])

        if action == "HOLD" or blocked_by:
            reason = decision.get("rationale", "no rationale")
            blocks = ", ".join(blocked_by) if blocked_by else "AI decision"
            print(f"        🚫 DeepSeek: HOLD ({blocks})")
            print(f"           Rationale: {reason}")
            append_ai_decision_event({
                "type": "AI_FULL_DECISION", "symbol": sym, "action": "HOLD",
                "rationale": reason, "confluence_score": confluence['total'],
                "blocked_by": blocked_by, "confidence": decision.get("confidence", 0)
            })
            write_dashboard_cycle_log(portfolio, position_details, [], len(scan_list))
            return

        # DeepSeek decided to open - extract params
        leverage = float(decision.get("leverage", 3))
        size_pct = float(decision.get("size_pct", 0.08))
        sl_pct_ai = decision.get("sl_pct")
        tp_pct_ai = decision.get("tp_pct")
        confidence = decision.get("confidence", 0)
        rationale = decision.get("rationale", "")

        # Validate and clamp
        leverage, size_pct, _ = validate_ai_params(leverage, size_pct, sym)

        # SL/TP: use AI values if provided, otherwise ATR-based fallback
        tf_15m = tech.get("timeframes", {}).get("15m", {})
        atr = float(tf_15m.get("atr", 0))
        price = float(tf_15m.get("price", 0))

        if sl_pct_ai and float(sl_pct_ai) > 0:
            sl_pct = float(sl_pct_ai)
        elif atr > 0 and price > 0:
            sl_pct = (ATR_SL_MULTIPLIER * atr) / price
        else:
            sl_pct = 0.02

        if tp_pct_ai and float(tp_pct_ai) > 0:
            tp_pct = float(tp_pct_ai)
        elif atr > 0 and price > 0:
            tp_pct = (ATR_TP_MULTIPLIER * atr) / price
        else:
            tp_pct = 0.03

        # Calculate limit entry price
        entry_price = calculate_limit_price(price, direction, tech, fib, SNIPER_BUFFER_PCT)

        intent_id = str(uuid.uuid4())

        print(f"        🔥 EXECUTING {action} on {sym} [intent:{intent_id[:8]}]")
        print(f"           Leverage={leverage}x Size={size_pct*100:.0f}% SL={sl_pct*100:.2f}% TP={tp_pct*100:.2f}%")
        print(f"           Confluence={confluence['total']:.1f} Limit={entry_price:.2f} (market={price:.2f})")
        print(f"           AI confidence={confidence}% rationale={rationale[:100]}")

        append_ai_decision_event({
            "type": "AI_FULL_DECISION", "symbol": sym, "action": action,
            "leverage": leverage, "size_pct": size_pct,
            "confluence_score": confluence['total'], "confluence_breakdown": confluence,
            "entry_price": entry_price, "sl_pct": sl_pct, "tp_pct": tp_pct,
            "confidence": confidence, "rationale": rationale
        })

        # Write to dashboard trade log
        dash_decision = {
            "symbol": sym, "action": action,
            "leverage": leverage, "size_pct": size_pct,
            "sl_pct": sl_pct, "tp_pct": tp_pct,
            "confidence": confidence,
            "entry_type": "LIMIT",
            "entry_price": entry_price,
            "reason_code": f"confluence={confluence['total']:.0f}"
        }
        write_dashboard_cycle_log(portfolio, position_details, [dash_decision], len(scan_list))


        if DRY_RUN:
            print(f"        🔍 DRY_RUN: not executing")
            return

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
            print(f"        ✅ Result: {res.json()}")
        except Exception as e:
            print(f"        ❌ Execution error: {e}")


async def main_loop():
    while True:
        await manage_cycle()
        await analysis_cycle()
        await asyncio.sleep(CYCLE_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main_loop())
