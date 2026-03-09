import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LearningAgent")

app = FastAPI()

# Configuration
REFLECTION_INTERVAL_HOURS = int(os.getenv("REFLECTION_INTERVAL_HOURS", "72"))
MIN_TRADES_FOR_REFLECTION = int(os.getenv("MIN_TRADES_FOR_REFLECTION", "10"))

DATA_DIR = "/data"
TRADING_HISTORY_FILE = f"{DATA_DIR}/trading_history.json"
STRATEGY_RULES_FILE = f"{DATA_DIR}/strategy_rules.json"
EVOLUTION_LOG_FILE = f"{DATA_DIR}/evolution_log.json"
API_COSTS_FILE = f"{DATA_DIR}/api_costs.json"
EVENTS_LOG_FILE = os.getenv("EVENTS_LOG_FILE", f"{DATA_DIR}/events_log.json")

# DeepSeek client
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com") if DEEPSEEK_API_KEY else None

# Default rules (no modifications)
DEFAULT_RULES = {
    "symbol_direction_blocks": [],
    "hour_restrictions": [],
    "confluence_threshold_adj": 0,
    "long_penalty_adj": 0,
    "atr_sl_multiplier_adj": 0.0,
    "atr_tp_multiplier_adj": 0.0,
}

# Clamping limits
CLAMP = {
    "symbol_direction_blocks_max": 5,
    "hour_restrictions_max": 4,
    "confluence_threshold_adj": (-3, 5),
    "long_penalty_adj": (-2, 5),
    "atr_sl_multiplier_adj": (-0.5, 0.5),
    "atr_tp_multiplier_adj": (-1.0, 1.0),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {path}: {e}")
    return default if default is not None else {}


def save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {path}: {e}")
        return False


def log_api_call(tokens_in: int, tokens_out: int):
    try:
        data = load_json(API_COSTS_FILE, {"calls": []})
        data.setdefault("calls", []).append({
            "timestamp": datetime.utcnow().isoformat(),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        })
        save_json(API_COSTS_FILE, data)
    except Exception as e:
        logger.error(f"Error logging API call: {e}")


def log_evolution(status: str, details: Dict[str, Any]):
    try:
        entries = load_json(EVOLUTION_LOG_FILE, [])
        if not isinstance(entries, list):
            entries = []
        entries.append({
            "timestamp": datetime.utcnow().isoformat(),
            "status": status,
            "details": details,
        })
        entries = entries[-50:]
        save_json(EVOLUTION_LOG_FILE, entries)
    except Exception as e:
        logger.error(f"Error logging evolution: {e}")


# ---------------------------------------------------------------------------
# Stats calculation (local, no LLM)
# ---------------------------------------------------------------------------

def calculate_detailed_stats(trades: List[Dict]) -> Dict[str, Any]:
    """Calculate per-symbol/direction, per-hour, and overall stats."""
    sym_dir = {}  # "BTCUSDT_short" -> {count, wins, pnl}
    per_hour = {}  # 0-23 -> {count, wins, pnl}
    side_stats = {"long": {"c": 0, "w": 0, "p": 0.0}, "short": {"c": 0, "w": 0, "p": 0.0}}

    for t in trades:
        sym = t.get("symbol", "?")
        side = t.get("side", "?").lower()
        pnl = float(t.get("pnl_pct", 0))
        ts_str = t.get("timestamp", "")

        # Per symbol+direction
        key = f"{sym}_{side}"
        if key not in sym_dir:
            sym_dir[key] = {"symbol": sym, "direction": side, "count": 0, "wins": 0, "pnl": 0.0}
        sym_dir[key]["count"] += 1
        sym_dir[key]["pnl"] += pnl
        if pnl > 0:
            sym_dir[key]["wins"] += 1

        # Per hour
        try:
            hour = datetime.fromisoformat(ts_str).hour
        except:
            continue
        if hour not in per_hour:
            per_hour[hour] = {"hour": hour, "count": 0, "wins": 0, "pnl": 0.0}
        per_hour[hour]["count"] += 1
        per_hour[hour]["pnl"] += pnl
        if pnl > 0:
            per_hour[hour]["wins"] += 1

        # Per side
        if side in side_stats:
            side_stats[side]["c"] += 1
            side_stats[side]["p"] += pnl
            if pnl > 0:
                side_stats[side]["w"] += 1

    # Add win rates
    for v in sym_dir.values():
        v["win_rate"] = round(v["wins"] / max(1, v["count"]) * 100, 1)
        v["avg_pnl"] = round(v["pnl"] / max(1, v["count"]), 3)
    for v in per_hour.values():
        v["win_rate"] = round(v["wins"] / max(1, v["count"]) * 100, 1)
        v["avg_pnl"] = round(v["pnl"] / max(1, v["count"]), 3)

    total_count = len(trades)
    total_wins = sum(1 for t in trades if float(t.get("pnl_pct", 0)) > 0)
    total_pnl = sum(float(t.get("pnl_pct", 0)) for t in trades)

    return {
        "total": {"count": total_count, "wins": total_wins, "pnl": round(total_pnl, 2),
                  "win_rate": round(total_wins / max(1, total_count) * 100, 1)},
        "per_symbol_direction": sorted(sym_dir.values(), key=lambda x: x["pnl"]),
        "per_hour": sorted(per_hour.values(), key=lambda x: x["hour"]),
        "per_side": {k: {"count": v["c"], "wins": v["w"], "pnl": round(v["p"], 2),
                         "win_rate": round(v["w"] / max(1, v["c"]) * 100, 1)}
                     for k, v in side_stats.items()},
    }


# ---------------------------------------------------------------------------
# DeepSeek reflection prompt
# ---------------------------------------------------------------------------

def build_reflection_prompt(stats: Dict, current_rules: Dict) -> str:
    total = stats["total"]
    sym_dir_lines = []
    for s in stats["per_symbol_direction"]:
        sym_dir_lines.append(
            f"  {s['symbol']} {s['direction'].upper()}: {s['count']} trades, "
            f"WR={s['win_rate']}%, PnL={s['pnl']:+.2f}%, avg={s['avg_pnl']:+.3f}%"
        )
    hour_lines = []
    for h in stats["per_hour"]:
        hour_lines.append(
            f"  {h['hour']:02d}:00 - {h['count']} trades, WR={h['win_rate']}%, PnL={h['pnl']:+.2f}%"
        )
    side_lines = []
    for side, v in stats["per_side"].items():
        side_lines.append(f"  {side.upper()}: {v['count']} trades, WR={v['win_rate']}%, PnL={v['pnl']:+.2f}%")

    current_rules_str = json.dumps(current_rules, indent=2)

    return f"""You are the strategy reflection engine for a crypto trading bot.

TASK: Analyze the trading statistics below and output concrete rule adjustments.

== OVERALL ==
{total['count']} trades | WR: {total['win_rate']}% | Total PnL: {total['pnl']:+.2f}%

== PER SYMBOL + DIRECTION ==
{chr(10).join(sym_dir_lines)}

== PER HOUR (UTC) ==
{chr(10).join(hour_lines)}

== LONG vs SHORT ==
{chr(10).join(side_lines)}

== CURRENT RULES ==
{current_rules_str}

== RULES FOR YOUR DECISIONS ==

1. symbol_direction_blocks (max 5): Block a symbol+direction ONLY if:
   - WR < 42% AND total PnL is negative AND at least 20 trades
   - Keep existing blocks unless data shows they should be removed

2. hour_restrictions (max 4): Block an hour ONLY if:
   - WR < 40% AND PnL is significantly negative (< -1%)
   - Keep existing restrictions unless data contradicts them

3. confluence_threshold_adj (-3 to +5): Adjust the confluence entry threshold.
   - Positive = more selective (fewer but better trades)
   - Increase if overall WR < 45%
   - Decrease if WR > 55% and you want more trades

4. long_penalty_adj (-2 to +5): Extra penalty on long entries.
   - Increase if LONG WR is significantly worse than SHORT WR
   - Decrease if LONG is performing well

5. atr_sl_multiplier_adj (-0.5 to +0.5): Adjust stop loss width.
   - Positive = wider SL (fewer stops but bigger losses)
   - Negative = tighter SL

6. atr_tp_multiplier_adj (-1.0 to +1.0): Adjust take profit width.
   - Positive = wider TP (bigger wins but fewer hits)
   - Negative = tighter TP (more frequent but smaller wins)

BE CONSERVATIVE. Only change what the data clearly supports. Small increments.
If unsure, keep the current value.

IMPORTANT: Use the EXACT symbol names from the data above (e.g. "BTC", "ETH", "SOL"), NOT with "USDT" suffix.

Respond ONLY with valid JSON:
{{
  "rules": {{
    "symbol_direction_blocks": [{{"symbol": "XXX", "direction": "long/short"}}],
    "hour_restrictions": [0-23],
    "confluence_threshold_adj": <int>,
    "long_penalty_adj": <int>,
    "atr_sl_multiplier_adj": <float>,
    "atr_tp_multiplier_adj": <float>
  }},
  "analysis": "<2-4 sentences explaining your decisions>"
}}"""


# ---------------------------------------------------------------------------
# DeepSeek call + parse
# ---------------------------------------------------------------------------

async def call_deepseek(prompt: str) -> str:
    if not client:
        logger.warning("DeepSeek client not configured")
        return "{}"
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an expert trading strategy analyst. Respond ONLY with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        if hasattr(response, "usage") and response.usage:
            log_api_call(response.usage.prompt_tokens, response.usage.completion_tokens)
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return "{}"


def parse_and_validate_rules(response_str: str, current_rules: Dict) -> Optional[Dict]:
    """Parse DeepSeek response and clamp all values to safe ranges."""
    try:
        data = json.loads(response_str)
        rules = data.get("rules", {})
        analysis = data.get("analysis", "")
    except (json.JSONDecodeError, TypeError):
        logger.error("Failed to parse DeepSeek response")
        return None

    validated = {}

    # symbol_direction_blocks
    blocks = rules.get("symbol_direction_blocks", current_rules.get("symbol_direction_blocks", []))
    valid_blocks = []
    for b in blocks:
        if isinstance(b, dict) and "symbol" in b and "direction" in b:
            valid_blocks.append({"symbol": b["symbol"], "direction": b["direction"]})
    validated["symbol_direction_blocks"] = valid_blocks[:CLAMP["symbol_direction_blocks_max"]]

    # hour_restrictions
    hours = rules.get("hour_restrictions", current_rules.get("hour_restrictions", []))
    valid_hours = [h for h in hours if isinstance(h, int) and 0 <= h <= 23]
    validated["hour_restrictions"] = valid_hours[:CLAMP["hour_restrictions_max"]]

    # Numeric adjustments with clamping
    for key in ["confluence_threshold_adj", "long_penalty_adj", "atr_sl_multiplier_adj", "atr_tp_multiplier_adj"]:
        val = rules.get(key, current_rules.get(key, 0))
        lo, hi = CLAMP[key]
        if isinstance(val, (int, float)):
            validated[key] = max(lo, min(hi, val))
        else:
            validated[key] = current_rules.get(key, 0)

    return {"rules": validated, "analysis": analysis}


# ---------------------------------------------------------------------------
# Backtest validation (simulate rules on 30 days of history)
# ---------------------------------------------------------------------------

BACKTEST_DAYS = int(os.getenv("BACKTEST_DAYS", "30"))
# Base confluence threshold from orchestrator (must match)
BASE_CONFLUENCE_THRESHOLD = int(os.getenv("FAST_OPEN_CONFLUENCE_THRESHOLD", "65"))


def backtest_rules(rules: Dict, all_trades: List[Dict]) -> Dict[str, Any]:
    """
    Simulate proposed rules against the last BACKTEST_DAYS of trade history.
    Returns stats comparing 'with rules' vs 'without rules'.

    A trade is "blocked" by the rules if:
    - Its symbol+direction is in symbol_direction_blocks
    - Its hour is in hour_restrictions
    - Its confluence score (if available) + adjustments < effective threshold
    """
    cutoff = datetime.utcnow() - timedelta(days=BACKTEST_DAYS)
    history = [
        t for t in all_trades
        if datetime.fromisoformat(t.get("timestamp", "2000-01-01")) >= cutoff
    ]

    if len(history) < 10:
        logger.info(f"Backtest: not enough history ({len(history)} trades in {BACKTEST_DAYS}d)")
        return {"skip": True, "reason": "insufficient_history", "count": len(history)}

    # Normalize symbol names: rules use "BTCUSDT", history may use "BTC"
    def norm_sym(s):
        return s.replace("USDT", "").replace("USD", "").upper()
    blocks = {(norm_sym(b["symbol"]), b["direction"]) for b in rules.get("symbol_direction_blocks", [])}
    hour_restrictions = set(rules.get("hour_restrictions", []))
    conf_adj = rules.get("confluence_threshold_adj", 0)
    long_penalty = rules.get("long_penalty_adj", 0)

    # Without rules: all trades count
    total_pnl_no_rules = sum(float(t.get("pnl_pct", 0)) for t in history)
    total_count_no_rules = len(history)
    wins_no_rules = sum(1 for t in history if float(t.get("pnl_pct", 0)) > 0)

    # With rules: filter out blocked trades
    surviving = []
    blocked = []
    for t in history:
        sym = t.get("symbol", "")
        sym_norm = norm_sym(sym)
        side = t.get("side", "").lower()
        pnl = float(t.get("pnl_pct", 0))
        try:
            hour = datetime.fromisoformat(t.get("timestamp", "")).hour
        except:
            hour = -1

        # Check symbol_direction block
        if (sym_norm, side) in blocks:
            blocked.append(t)
            continue

        # Check hour restriction
        if hour in hour_restrictions:
            blocked.append(t)
            continue

        # Check confluence threshold adjustment
        # Use score if available in trade record, otherwise skip this check
        score = t.get("confluence_score")
        if score is not None:
            effective_threshold = BASE_CONFLUENCE_THRESHOLD + conf_adj
            effective_score = float(score)
            if side == "long" and long_penalty > 0:
                effective_score -= long_penalty
            if effective_score < effective_threshold:
                blocked.append(t)
                continue

        surviving.append(t)

    total_pnl_with_rules = sum(float(t.get("pnl_pct", 0)) for t in surviving)
    total_count_with_rules = len(surviving)
    wins_with_rules = sum(1 for t in surviving if float(t.get("pnl_pct", 0)) > 0)

    blocked_pnl = sum(float(t.get("pnl_pct", 0)) for t in blocked)
    blocked_count = len(blocked)

    wr_no_rules = wins_no_rules / max(1, total_count_no_rules) * 100
    wr_with_rules = wins_with_rules / max(1, total_count_with_rules) * 100

    improvement = total_pnl_with_rules - total_pnl_no_rules

    result = {
        "skip": False,
        "backtest_days": BACKTEST_DAYS,
        "total_trades": total_count_no_rules,
        "without_rules": {
            "trades": total_count_no_rules,
            "wins": wins_no_rules,
            "win_rate": round(wr_no_rules, 1),
            "pnl": round(total_pnl_no_rules, 2),
        },
        "with_rules": {
            "trades": total_count_with_rules,
            "wins": wins_with_rules,
            "win_rate": round(wr_with_rules, 1),
            "pnl": round(total_pnl_with_rules, 2),
        },
        "blocked": {
            "count": blocked_count,
            "pnl": round(blocked_pnl, 2),
        },
        "improvement_pnl": round(improvement, 2),
        "pass": improvement >= 0,  # Rules must not worsen PnL
    }

    return result


# ---------------------------------------------------------------------------
# Main reflection cycle
# ---------------------------------------------------------------------------

async def daily_reflection_cycle():
    logger.info("--- DAILY REFLECTION START ---")

    try:
        # 1. Load current rules
        current_data = load_json(STRATEGY_RULES_FILE, {})
        current_rules = current_data.get("rules", DEFAULT_RULES.copy())
        last_ts = current_data.get("last_reflection_timestamp", "")
        current_version = current_data.get("version", 0)

        # 2. Load trades since last reflection
        all_trades = load_json(TRADING_HISTORY_FILE, [])
        if not isinstance(all_trades, list):
            all_trades = []

        if last_ts:
            try:
                cutoff = datetime.fromisoformat(last_ts)
                trades = [t for t in all_trades
                          if datetime.fromisoformat(t.get("timestamp", "2000-01-01")) > cutoff]
            except:
                trades = all_trades[-100:]
        else:
            # First run: take last 100 trades
            trades = all_trades[-100:]

        logger.info(f"Trades since last reflection: {len(trades)}")

        # 3. Check minimum
        if len(trades) < MIN_TRADES_FOR_REFLECTION:
            logger.info(f"Not enough trades ({len(trades)} < {MIN_TRADES_FOR_REFLECTION}), skipping")
            log_evolution("skipped", {
                "reason": "insufficient_trades",
                "count": len(trades),
                "min_required": MIN_TRADES_FOR_REFLECTION,
            })
            return

        # 4. Calculate stats (local, no LLM)
        stats = calculate_detailed_stats(trades)
        logger.info(f"Stats: {stats['total']}")
        for s in stats["per_symbol_direction"]:
            logger.info(f"  {s['symbol']} {s['direction']}: {s['count']}t WR={s['win_rate']}% PnL={s['pnl']:+.2f}%")

        # 5. Build prompt and call DeepSeek
        prompt = build_reflection_prompt(stats, current_rules)
        logger.info("Calling DeepSeek for reflection...")
        response = await call_deepseek(prompt)

        # 6. Parse and validate
        result = parse_and_validate_rules(response, current_rules)
        if result is None:
            logger.error("Failed to parse DeepSeek response, keeping current rules")
            log_evolution("error", {"reason": "parse_failure", "response": response[:500]})
            return

        new_rules = result["rules"]
        analysis = result["analysis"]
        new_version = current_version + 1
        now = datetime.utcnow().isoformat()

        # 7. BACKTEST: validate proposed rules on 30 days of history
        logger.info("Running backtest validation...")
        bt = backtest_rules(new_rules, all_trades)

        if bt.get("skip"):
            logger.info(f"Backtest skipped: {bt.get('reason')} ({bt.get('count', 0)} trades)")
            # Not enough history to validate — apply rules anyway (conservative)
        elif not bt["pass"]:
            logger.warning(f"BACKTEST FAILED — rules would WORSEN PnL by {bt['improvement_pnl']:+.2f}%")
            logger.warning(f"  Without rules: {bt['without_rules']['trades']}t, PnL={bt['without_rules']['pnl']:+.2f}%")
            logger.warning(f"  With rules:    {bt['with_rules']['trades']}t, PnL={bt['with_rules']['pnl']:+.2f}%")
            logger.warning(f"  Blocked: {bt['blocked']['count']}t, PnL={bt['blocked']['pnl']:+.2f}%")
            logger.warning("Keeping current rules.")
            log_evolution("backtest_rejected", {
                "proposed_version": new_version,
                "trades_analyzed": len(trades),
                "proposed_rules": new_rules,
                "backtest": bt,
                "analysis": analysis,
            })
            # Update last_reflection_timestamp so we don't re-analyze the same trades
            current_data["last_reflection_timestamp"] = now
            save_json(STRATEGY_RULES_FILE, current_data)
            return
        else:
            logger.info(f"BACKTEST PASSED — improvement: {bt['improvement_pnl']:+.2f}%")
            logger.info(f"  Without rules: {bt['without_rules']['trades']}t, PnL={bt['without_rules']['pnl']:+.2f}%")
            logger.info(f"  With rules:    {bt['with_rules']['trades']}t, PnL={bt['with_rules']['pnl']:+.2f}%")
            logger.info(f"  Blocked: {bt['blocked']['count']}t, PnL={bt['blocked']['pnl']:+.2f}%")

        # 8. Save strategy_rules.json
        strategy_data = {
            "version": new_version,
            "updated_at": now,
            "last_reflection_timestamp": now,
            "trades_analyzed": len(trades),
            "rules": new_rules,
            "analysis": analysis,
            "backtest": bt if not bt.get("skip") else None,
        }
        save_json(STRATEGY_RULES_FILE, strategy_data)

        logger.info(f"Saved strategy_rules.json v{new_version}")
        logger.info(f"  Blocks: {len(new_rules['symbol_direction_blocks'])}")
        logger.info(f"  Hour restrictions: {new_rules['hour_restrictions']}")
        logger.info(f"  Conf adj: {new_rules['confluence_threshold_adj']}")
        logger.info(f"  Long penalty: {new_rules['long_penalty_adj']}")
        logger.info(f"  SL adj: {new_rules['atr_sl_multiplier_adj']}")
        logger.info(f"  TP adj: {new_rules['atr_tp_multiplier_adj']}")
        logger.info(f"  Analysis: {analysis[:200]}")

        # 9. Log
        log_evolution("success", {
            "version": new_version,
            "trades_analyzed": len(trades),
            "rules": new_rules,
            "backtest": bt if not bt.get("skip") else None,
        })

    except Exception as e:
        logger.error(f"Reflection cycle error: {e}", exc_info=True)
        log_evolution("error", {"error": str(e)})


async def reflection_loop():
    interval = REFLECTION_INTERVAL_HOURS * 3600
    logger.info(f"Reflection loop: every {REFLECTION_INTERVAL_HOURS}h")
    while True:
        try:
            await asyncio.sleep(interval)
            await daily_reflection_cycle()
        except Exception as e:
            logger.error(f"Reflection loop error: {e}")
            await asyncio.sleep(3600)


# ---------------------------------------------------------------------------
# API Endpoints (kept for backward compatibility)
# ---------------------------------------------------------------------------

class TradeRecord(BaseModel):
    timestamp: str
    intent_id: Optional[str] = None
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    leverage: float
    size_pct: float
    duration_minutes: Optional[int] = None
    market_conditions: Dict[str, Any] = {}


class EventRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    timestamp: Optional[str] = None
    event_type: str
    symbol: str
    side: Optional[str] = None
    reason: Optional[str] = None
    data: Dict[str, Any] = {}


@app.post("/record_trade")
async def record_trade(trade: TradeRecord):
    try:
        trades = load_json(TRADING_HISTORY_FILE, [])
        if not isinstance(trades, list):
            trades = []
        trades.append(trade.model_dump())
        save_json(TRADING_HISTORY_FILE, trades)
        logger.info(f"Recorded trade: {trade.symbol} {trade.side} PnL: {trade.pnl_pct}%")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error recording trade: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/record_event")
async def record_event(event: EventRecord):
    try:
        if not event.timestamp:
            event.timestamp = datetime.utcnow().isoformat()
        raw = event.model_dump()
        known = {"timestamp", "event_type", "symbol", "side", "reason", "data"}
        extra = {k: v for k, v in raw.items() if k not in known}
        if extra:
            raw["data"] = {**(raw.get("data") or {}), **extra}
            for k in extra:
                raw.pop(k, None)
        events = load_json(EVENTS_LOG_FILE, [])
        if not isinstance(events, list):
            events = []
        events.append(raw)
        events = events[-2000:]
        save_json(EVENTS_LOG_FILE, events)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/strategy_rules")
async def get_strategy_rules():
    return load_json(STRATEGY_RULES_FILE, {"version": 0, "rules": DEFAULT_RULES})


@app.post("/trigger_reflection")
async def trigger_reflection():
    try:
        await daily_reflection_cycle()
        # Return current state after reflection
        data = load_json(STRATEGY_RULES_FILE, {})
        return {
            "status": "success",
            "message": "Reflection completed",
            "version": data.get("version"),
            "backtest": data.get("backtest"),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/current_params")
async def get_current_params():
    """Backward compatibility — returns strategy rules as params."""
    data = load_json(STRATEGY_RULES_FILE, {})
    return {"status": "active", "version": data.get("version", 0), "rules": data.get("rules", DEFAULT_RULES)}


@app.get("/evolution_log")
async def get_evolution_log():
    entries = load_json(EVOLUTION_LOG_FILE, [])
    if not isinstance(entries, list):
        entries = []
    return {"status": "success", "entries": entries[-10:]}


@app.get("/events_log")
async def get_events_log(limit: int = 100):
    events = load_json(EVENTS_LOG_FILE, [])
    if not isinstance(events, list):
        events = []
    return {"events": events[-min(limit, 2000):]}


@app.get("/health")
def health():
    return {
        "status": "active",
        "reflection_interval_hours": REFLECTION_INTERVAL_HOURS,
        "min_trades_for_reflection": MIN_TRADES_FOR_REFLECTION,
    }


@app.on_event("startup")
async def startup():
    os.makedirs(DATA_DIR, exist_ok=True)
    logger.info("Learning Agent started (reflection mode)")
    logger.info(f"  Reflection interval: {REFLECTION_INTERVAL_HOURS}h")
    logger.info(f"  Min trades: {MIN_TRADES_FOR_REFLECTION}")
    asyncio.create_task(reflection_loop())
