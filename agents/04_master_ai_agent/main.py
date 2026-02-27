import os
import json
import logging
import httpx
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from openai import OpenAI
from threading import Lock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MasterAI")

app = FastAPI()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# Agent URLs for reverse analysis
AGENT_URLS = {
    "technical": "http://01_technical_analyzer:8000",
    "fibonacci": "http://03_fibonacci_agent:8000",
    "gann": "http://05_gann_analyzer_agent:8000",
    "news": "http://06_news_sentiment_agent:8000",
    "forecaster": "http://08_forecaster_agent:8000"
}

LEARNING_AGENT_URL = "http://10_learning_agent:8000"

EVOLVED_PARAMS_FILE = "/data/evolved_params.json"
API_COSTS_FILE = "/data/api_costs.json"
AI_DECISIONS_FILE = "/data/ai_decisions.json"
RECENT_CLOSES_FILE = "/data/recent_closes.json"
TRADING_HISTORY_FILE = "/data/trading_history.json"

COOLDOWN_MINUTES = 15

file_lock = Lock()


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def load_json_file(filepath: str, default: Any = None):
    if default is None:
        default = []
    with file_lock:
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return json.load(f)
            return default
        except Exception as e:
            logger.error(f"Errore caricamento {filepath}: {e}")
            return default


def save_json_file(filepath: str, data: Any):
    ensure_parent_dir(filepath)
    with file_lock:
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Errore salvataggio {filepath}: {e}")
            return False


def save_close_event(symbol: str, side: str, reason: str):
    closes = load_json_file(RECENT_CLOSES_FILE, [])
    now = datetime.now()
    closes.append({
        "timestamp": now.isoformat(),
        "symbol": symbol,
        "side": side,
        "reason": reason
    })
    cutoff_ts = (now - timedelta(hours=24)).isoformat()
    closes = [c for c in closes if c.get("timestamp", "") > cutoff_ts]
    save_json_file(RECENT_CLOSES_FILE, closes)
    logger.info(f"Cooldown salvato: {symbol} {side} - {reason}")


def normalize_position_side(side_raw: str) -> Optional[str]:
    s = (side_raw or "").lower().strip()
    if s in ("long", "buy"):
        return "long"
    if s in ("short", "sell"):
        return "short"
    return None


def log_api_call(tokens_in: int, tokens_out: int):
    try:
        if os.path.exists(API_COSTS_FILE):
            with open(API_COSTS_FILE, 'r') as f:
                data = json.load(f)
        else:
            data = {'calls': []}

        data['calls'].append({
            'timestamp': datetime.now().isoformat(),
            'tokens_in': tokens_in,
            'tokens_out': tokens_out
        })

        os.makedirs(os.path.dirname(API_COSTS_FILE), exist_ok=True)
        with open(API_COSTS_FILE, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"API call logged: {tokens_in} in, {tokens_out} out")
    except Exception as e:
        logger.error(f"Error logging API call: {e}")


def save_ai_decision(decision_data):
    try:
        decisions = []
        if os.path.exists(AI_DECISIONS_FILE):
            with open(AI_DECISIONS_FILE, 'r') as f:
                decisions = json.load(f)

        decisions.append({
            'timestamp': datetime.now().isoformat(),
            **decision_data
        })

        decisions = decisions[-100:]

        os.makedirs(os.path.dirname(AI_DECISIONS_FILE), exist_ok=True)
        with open(AI_DECISIONS_FILE, 'w') as f:
            json.dump(decisions, f, indent=2)

        logger.info(f"AI decision saved: {decision_data.get('source', 'wyckoff')}")
    except Exception as e:
        logger.error(f"Error saving AI decision: {e}")


# ---------------------------------------------------------------------------
# Trading Journal for LLM feedback (Phase 4)
# ---------------------------------------------------------------------------

def get_journal_for_llm(symbol: str = None, limit: int = 20) -> list:
    """Prepare trading journal for LLM context. Compact format."""
    history = load_json_file(TRADING_HISTORY_FILE, [])

    if symbol:
        coin = symbol.replace("USDT", "")
        relevant = [t for t in history if t.get("symbol") == coin]
    else:
        relevant = history

    return [
        {
            "symbol": t.get("symbol", "?"),
            "side": t.get("side", "?"),
            "pnl_pct": round(t.get("pnl_pct", 0), 2),
            "leverage": t.get("leverage", 1),
            "date": t.get("timestamp", "")[:10],
            "closed_by": t.get("market_conditions", {}).get("closed_by", "unknown")
        }
        for t in relevant[-limit:]
    ]


# ---------------------------------------------------------------------------
# Wyckoff System Prompt (Phase 2 - replaces old scalper prompt)
# ---------------------------------------------------------------------------

WYCKOFF_SYSTEM_PROMPT = """Sei un ANALISTA DI MERCATO specializzato nel framework Wyckoff.
Il tuo compito e' ANALIZZARE dati di mercato e IDENTIFICARE pattern.
NON sei un trader. NON decidi leva, sizing, SL o TP.

## FRAMEWORK WYCKOFF

Analizza i dati per identificare la fase corrente:
1. ACCUMULATION - Smart money sta comprando (volume in aumento su supporto,
   spring, test of supply, SOS - Sign of Strength)
2. MARKUP - Trend rialzista confermato (breakout con volume, pullback su basso volume)
3. DISTRIBUTION - Smart money sta vendendo (volume in aumento su resistenza,
   UTAD - Upthrust After Distribution, SOW - Sign of Weakness)
4. MARKDOWN - Trend ribassista confermato (breakdown con volume, rally su basso volume)

## DATI CHE RICEVI
- OHLCV multi-timeframe (15m, 1h, 4h, 1d)
- Order Book L2 (bid/ask depth, imbalance)
- Funding Rate (sentiment leverage del mercato)
- Open Interest (posizionamento aggregato)
- Indicatori tecnici (EMA, RSI, MACD, ATR, Volume)
- Fibonacci levels
- Trading Journal (ultimi N trade con risultati)

## OUTPUT JSON OBBLIGATORIO
{
  "market_phase": "ACCUMULATION|MARKUP|DISTRIBUTION|MARKDOWN|UNCERTAIN",
  "phase_confidence": 0-100,
  "trade_proposal": {
    "direction": "LONG|SHORT|NONE",
    "reasoning": "Spiegazione Wyckoff: quale pattern vedi, perche' questa fase",
    "key_observations": [
      "Volume divergence: prezzo scende ma volume cala -> possibile accumulation",
      "Order book: bid depth 2x ask depth -> supporto istituzionale",
      "Funding negativo -0.01% -> mercato overleveraged short"
    ],
    "risk_warnings": [
      "RSI gia' in zona ipercomprato",
      "Resistenza EMA50 a 3% di distanza"
    ]
  },
  "journal_learning": "Cosa hai imparato dal journal: pattern simili passati e risultati"
}

REGOLE:
- Se i segnali sono contrastanti, direction = "NONE" e phase = "UNCERTAIN"
- Mai forzare un trade. Meglio "NONE" che un trade sbagliato.
- Consulta SEMPRE il trading journal per evitare errori ripetuti
- Il tuo output e' un'ANALISI, non una decisione. Il codice decidera'."""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class WyckoffRequest(BaseModel):
    symbol: str
    ohlcv_summary: Dict[str, Any]
    order_book: Optional[Dict[str, Any]] = None
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None
    fibonacci: Optional[Dict[str, Any]] = None
    trading_journal: Optional[List[Dict[str, Any]]] = None


class ReverseAnalysisRequest(BaseModel):
    symbol: str
    current_position: Dict[str, Any]


class PositionData(BaseModel):
    symbol: str
    side: str
    entry_price: float
    mark_price: float
    leverage: float
    size: Optional[float] = None
    pnl: Optional[float] = None
    is_disabled: Optional[bool] = False


class ManageCriticalPositionsRequest(BaseModel):
    positions: List[PositionData]
    portfolio_snapshot: Optional[Dict[str, Any]] = None
    learning_params: Optional[dict] = None


# ---------------------------------------------------------------------------
# /analyze_wyckoff - NEW main endpoint (replaces /decide_batch + /select_leverage)
# ---------------------------------------------------------------------------

@app.post("/analyze_wyckoff")
async def analyze_wyckoff(request: WyckoffRequest):
    """
    Wyckoff pattern analysis. LLM analyzes market data and proposes a direction.
    Code (orchestrator) decides whether to act on it.

    Returns:
        {
          "market_phase": "ACCUMULATION|MARKUP|DISTRIBUTION|MARKDOWN|UNCERTAIN",
          "phase_confidence": 0-100,
          "trade_proposal": {
            "direction": "LONG|SHORT|NONE",
            "reasoning": "...",
            "key_observations": [...],
            "risk_warnings": [...]
          },
          "journal_learning": "..."
        }
    """
    try:
        # Build compact data for LLM
        prompt_data = {
            "symbol": request.symbol,
            "ohlcv_summary": request.ohlcv_summary,
        }

        if request.order_book:
            prompt_data["order_book"] = {
                "bid_depth": request.order_book.get("bid_depth", 0),
                "ask_depth": request.order_book.get("ask_depth", 0),
                "imbalance": request.order_book.get("imbalance", 0.5),
            }

        if request.funding_rate is not None:
            prompt_data["funding_rate"] = request.funding_rate

        if request.open_interest is not None:
            prompt_data["open_interest"] = request.open_interest

        if request.fibonacci:
            prompt_data["fibonacci"] = request.fibonacci

        # Trading journal - use provided or fetch
        journal = request.trading_journal
        if journal is None:
            journal = get_journal_for_llm(request.symbol, limit=20)
        prompt_data["trading_journal"] = journal

        user_content = f"ANALIZZA: {json.dumps(prompt_data, indent=2)}"

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": WYCKOFF_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        if hasattr(response, 'usage') and response.usage:
            log_api_call(response.usage.prompt_tokens, response.usage.completion_tokens)

        content = response.choices[0].message.content
        logger.info(f"Wyckoff analysis for {request.symbol}: {content[:300]}")

        result = json.loads(content)

        # Normalize and validate
        phase = result.get("market_phase", "UNCERTAIN").upper()
        if phase not in ("ACCUMULATION", "MARKUP", "DISTRIBUTION", "MARKDOWN", "UNCERTAIN"):
            phase = "UNCERTAIN"

        phase_confidence = max(0, min(100, int(result.get("phase_confidence", 0))))

        trade_proposal = result.get("trade_proposal", {})
        direction = trade_proposal.get("direction", "NONE").upper()
        if direction not in ("LONG", "SHORT", "NONE"):
            direction = "NONE"

        validated_result = {
            "market_phase": phase,
            "phase_confidence": phase_confidence,
            "trade_proposal": {
                "direction": direction,
                "reasoning": trade_proposal.get("reasoning", ""),
                "key_observations": trade_proposal.get("key_observations", []),
                "risk_warnings": trade_proposal.get("risk_warnings", []),
            },
            "journal_learning": result.get("journal_learning", ""),
        }

        # Save for dashboard
        save_ai_decision({
            "source": "wyckoff_analysis",
            "symbol": request.symbol,
            "market_phase": phase,
            "phase_confidence": phase_confidence,
            "direction": direction,
            "reasoning": trade_proposal.get("reasoning", "")[:200],
        })

        return validated_result

    except Exception as e:
        logger.error(f"Wyckoff analysis error for {request.symbol}: {e}")
        return {
            "market_phase": "UNCERTAIN",
            "phase_confidence": 0,
            "trade_proposal": {
                "direction": "NONE",
                "reasoning": f"Analysis error: {str(e)}",
                "key_observations": [],
                "risk_warnings": ["Analysis failed, defaulting to NONE"],
            },
            "journal_learning": "",
        }


# ---------------------------------------------------------------------------
# /analyze_reverse - KEPT (for losing position management)
# ---------------------------------------------------------------------------

@app.post("/analyze_reverse")
async def analyze_reverse(payload: ReverseAnalysisRequest):
    """Analizza posizione in perdita: HOLD, CLOSE o REVERSE"""
    try:
        symbol = payload.symbol
        position = payload.current_position

        logger.info(f"Analyzing reverse for {symbol}: ROI={position.get('roi_pct', 0)*100:.2f}%")

        agents_data = {}

        async with httpx.AsyncClient(timeout=10.0) as http_client:
            for agent_name, endpoint in [
                ("technical", f"{AGENT_URLS['technical']}/analyze_multi_tf"),
                ("fibonacci", f"{AGENT_URLS['fibonacci']}/analyze_fib"),
                ("gann", f"{AGENT_URLS['gann']}/analyze_gann"),
                ("news", f"{AGENT_URLS['news']}/analyze_sentiment"),
                ("forecaster", f"{AGENT_URLS['forecaster']}/forecast"),
            ]:
                try:
                    resp = await http_client.post(endpoint, json={"symbol": symbol}, timeout=10.0)
                    if resp.status_code == 200:
                        agents_data[agent_name] = resp.json()
                except Exception as e:
                    logger.warning(f"Agent {agent_name} failed for {symbol}: {e}")
                    agents_data[agent_name] = {}

        pnl_dollars = position.get('pnl_dollars', 0)
        wallet_balance = position.get('wallet_balance', 0)
        if wallet_balance == 0:
            wallet_balance = abs(pnl_dollars) * 3

        base_size_pct = 0.15
        loss_amount = abs(pnl_dollars)
        recovery_extra = (loss_amount / max(wallet_balance, 100)) / 0.02
        recovery_size_pct = min(base_size_pct + recovery_extra, 0.25)

        prompt_data = {
            "symbol": symbol,
            "current_position": {
                "side": position.get('side'),
                "entry_price": position.get('entry_price'),
                "mark_price": position.get('mark_price'),
                "roi_pct": position.get('roi_pct', 0) * 100,
                "pnl_dollars": pnl_dollars,
                "leverage": position.get('leverage', 1)
            },
            "technical_analysis": agents_data.get('technical', {}),
            "fibonacci_analysis": agents_data.get('fibonacci', {}),
            "gann_analysis": agents_data.get('gann', {}),
            "news_sentiment": agents_data.get('news', {}),
            "forecast": agents_data.get('forecaster', {})
        }

        system_prompt = """Sei un TRADER ESPERTO che analizza posizioni in perdita.

DECISIONI POSSIBILI:
1. HOLD = Correzione temporanea, trend principale valido
2. CLOSE = Incertezza, meglio chiudere
3. REVERSE = CHIARA INVERSIONE DI TREND confermata da MULTIPLI INDICATORI (almeno 3)

FORMATO RISPOSTA JSON OBBLIGATORIO:
{
  "action": "HOLD" | "CLOSE" | "REVERSE",
  "confidence": 85,
  "rationale": "Spiegazione dettagliata basata sugli indicatori",
  "recovery_size_pct": 0.18
}"""

        user_prompt = f"""ANALIZZA QUESTA POSIZIONE IN PERDITA E DECIDI:

{json.dumps(prompt_data, indent=2)}

Recovery size calcolato: {recovery_size_pct:.2f} ({recovery_size_pct*100:.1f}%)

Analizza TUTTI gli indicatori e decidi: HOLD, CLOSE o REVERSE."""

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )

        if hasattr(response, 'usage') and response.usage:
            log_api_call(response.usage.prompt_tokens, response.usage.completion_tokens)

        content = response.choices[0].message.content
        logger.info(f"Reverse analysis response for {symbol}: {content}")

        decision = json.loads(content)

        action = decision.get("action", "HOLD").upper()
        if action not in ["HOLD", "CLOSE", "REVERSE"]:
            action = "HOLD"

        confidence = max(0, min(100, decision.get("confidence", 50)))
        rationale = decision.get("rationale", "No rationale provided")

        final_recovery_size = decision.get("recovery_size_pct", recovery_size_pct)
        final_recovery_size = max(0.05, min(0.25, final_recovery_size))

        result = {
            "action": action,
            "confidence": confidence,
            "rationale": rationale,
            "recovery_size_pct": final_recovery_size,
            "agents_data_summary": {k: bool(v) for k, v in agents_data.items()}
        }

        if action in ["CLOSE", "REVERSE"]:
            side_dir = normalize_position_side(position.get('side', '')) or "long"
            save_close_event(symbol, side_dir, f"{action}: {rationale[:100]}")

        logger.info(f"Reverse analysis complete for {symbol}: {action} (confidence: {confidence}%)")
        return result

    except Exception as e:
        logger.error(f"Reverse analysis error: {e}")
        return {
            "action": "HOLD",
            "confidence": 0,
            "rationale": f"Error during analysis: {str(e)}. Defaulting to HOLD.",
            "recovery_size_pct": 0.15,
            "agents_data_summary": {}
        }


# ---------------------------------------------------------------------------
# /manage_critical_positions - KEPT (fast path for critical losses)
# ---------------------------------------------------------------------------

@app.post("/manage_critical_positions")
async def manage_critical_positions(request: ManageCriticalPositionsRequest):
    """
    Gestione robusta di posizioni critiche in perdita.
    Hard timeout su LLM, fallback deterministico.
    """
    start_time = datetime.now()
    timeout_occurred = False
    actions_result = []

    try:
        logger.info(f"Managing {len(request.positions)} critical positions")
        learning_params = getattr(request, "learning_params", None) or {}
        learning_params_params = (learning_params.get("params") if isinstance(learning_params, dict) else {}) or {}
        learning_params_meta = {
            "status": learning_params.get("status") if isinstance(learning_params, dict) else None,
            "version": learning_params.get("version") if isinstance(learning_params, dict) else None,
            "evolved_at": learning_params.get("evolved_at") if isinstance(learning_params, dict) else None,
        }

        # Fast path: tech data in parallel
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            tech_tasks = [
                http_client.post(
                    f"{AGENT_URLS['technical']}/analyze_multi_tf_full",
                    json={"symbol": pos.symbol}
                )
                for pos in request.positions
            ]
            tech_results = await asyncio.gather(*tech_tasks, return_exceptions=True)
            tech_data_map = {}
            for i, pos in enumerate(request.positions):
                if isinstance(tech_results[i], Exception):
                    tech_data_map[pos.symbol] = {}
                else:
                    try:
                        tech_data_map[pos.symbol] = tech_results[i].json()
                    except Exception:
                        tech_data_map[pos.symbol] = {}

        for pos in request.positions:
            entry = pos.entry_price
            mark = pos.mark_price
            leverage = pos.leverage
            side = pos.side.lower()

            if entry > 0 and mark > 0:
                if side in ['long', 'buy']:
                    loss_pct_with_leverage = ((mark - entry) / entry) * leverage * 100
                else:
                    loss_pct_with_leverage = -((mark - entry) / entry) * leverage * 100
            else:
                loss_pct_with_leverage = 0.0

            logger.info(f"  {pos.symbol} {side}: loss={loss_pct_with_leverage:.2f}%")

            tech_data = tech_data_map.get(pos.symbol, {})

            # Count technical confirmations for REVERSE
            confirmations_count = 0
            confirmations_list = []

            if tech_data:
                rsi_1h = tech_data.get('timeframes', {}).get('1h', {}).get('rsi')
                if rsi_1h:
                    if side == 'long' and rsi_1h < 30:
                        confirmations_count += 1
                        confirmations_list.append(f"RSI 1h oversold ({rsi_1h:.1f})")
                    elif side == 'short' and rsi_1h > 70:
                        confirmations_count += 1
                        confirmations_list.append(f"RSI 1h overbought ({rsi_1h:.1f})")

                trend_1h = tech_data.get('timeframes', {}).get('1h', {}).get('trend')
                if trend_1h:
                    if (side == 'long' and trend_1h == 'bearish') or (side == 'short' and trend_1h == 'bullish'):
                        confirmations_count += 1
                        confirmations_list.append(f"Trend 1h opposto ({trend_1h})")

                macd_signal = tech_data.get('timeframes', {}).get('1h', {}).get('macd_signal')
                if macd_signal:
                    if (side == 'long' and macd_signal == 'bearish') or (side == 'short' and macd_signal == 'bullish'):
                        confirmations_count += 1
                        confirmations_list.append(f"MACD opposto ({macd_signal})")

                volume_trend = tech_data.get('timeframes', {}).get('1h', {}).get('volume_trend')
                if volume_trend == 'increasing':
                    confirmations_count += 1
                    confirmations_list.append("Volume in aumento")

            score_breakdown = {
                "technical_score": confirmations_count * 25,
                "loss_severity": min(100, abs(loss_pct_with_leverage) * 5),
                "trend_alignment": 50 if confirmations_count >= 2 else 0,
                "volume_confirmation": 25 if "Volume in aumento" in confirmations_list else 0
            }

            # LLM call with timeout
            system_prompt = """Sei un trader esperto che analizza posizioni critiche in perdita.

DECISIONI POSSIBILI:
1. HOLD = Correzione temporanea, trend principale valido
2. CLOSE = Incertezza, meglio chiudere
3. REVERSE = Inversione confermata (servono ALMENO 4 conferme)

Rispondi SOLO in JSON: {"action": "HOLD|CLOSE|REVERSE", "confidence": 0-100, "rationale": "breve spiegazione"}"""

            user_prompt = f"""POSIZIONE CRITICA:
Symbol: {pos.symbol}, Side: {side}, Loss: {loss_pct_with_leverage:.2f}%
Confirmations: {confirmations_count} - {confirmations_list}

LEARNING_POLICY:
{json.dumps(learning_params_params, indent=2)[:800]}

Technical 1h:
{json.dumps(tech_data.get('timeframes', {}).get('1h', {}), indent=2)[:500]}

DECIDI: HOLD, CLOSE o REVERSE"""

            decision_action = "CLOSE"
            decision_confidence = 50
            decision_rationale = "Timeout/error LLM, fallback CLOSE"

            try:
                async def call_llm():
                    return await asyncio.to_thread(
                        lambda: client.chat.completions.create(
                            model="deepseek-chat",
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.3
                        )
                    )

                response = await asyncio.wait_for(call_llm(), timeout=20.0)

                if hasattr(response, 'usage') and response.usage:
                    log_api_call(response.usage.prompt_tokens, response.usage.completion_tokens)

                content = response.choices[0].message.content
                decision_data = json.loads(content)

                decision_action = decision_data.get("action", "CLOSE").upper()
                decision_confidence = decision_data.get("confidence", 50)
                decision_rationale = decision_data.get("rationale", "No rationale")

                # Cap confidence by confirmations
                try:
                    decision_confidence = float(decision_confidence)
                except Exception:
                    decision_confidence = 50
                if confirmations_count <= 0:
                    decision_confidence = min(decision_confidence, 55)
                elif confirmations_count == 1:
                    decision_confidence = min(decision_confidence, 65)
                elif confirmations_count == 2:
                    decision_confidence = min(decision_confidence, 75)
                decision_confidence = int(max(0, min(100, decision_confidence)))

            except asyncio.TimeoutError:
                logger.warning(f"LLM timeout for {pos.symbol}, using fallback")
                timeout_occurred = True
            except Exception as e:
                logger.warning(f"LLM error for {pos.symbol}: {e}, using fallback")

            # Constraints
            if pos.is_disabled and decision_action == "REVERSE":
                decision_action = "CLOSE"
                decision_rationale = "Simbolo disabilitato, REVERSE bloccato. " + decision_rationale

            if decision_action == "REVERSE" and confirmations_count < 4:
                decision_action = "CLOSE"
                decision_rationale = f"Solo {confirmations_count} conferme (<4), REVERSE bloccato. " + decision_rationale

            if decision_action in ["CLOSE", "REVERSE"]:
                save_close_event(pos.symbol, side, f"{decision_action}: {decision_rationale[:100]}")

            actions_result.append({
                "symbol": pos.symbol,
                "action": decision_action,
                "confidence": decision_confidence,
                "rationale": decision_rationale,
                "score_breakdown": score_breakdown,
                "loss_pct_with_leverage": round(loss_pct_with_leverage, 2),
                "confirmations_count": confirmations_count,
                "confirmations": confirmations_list
            })

            logger.info(f"  {pos.symbol}: {decision_action} (confidence={decision_confidence}%)")

        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        return {
            "actions": actions_result,
            "meta": {
                "timeout_occurred": timeout_occurred,
                "processing_time_ms": elapsed_ms,
                "total_positions": len(request.positions),
                "learning_params": learning_params_meta,
            }
        }

    except Exception as e:
        logger.error(f"Critical positions management error: {e}")
        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        fallback_actions = []
        for pos in request.positions:
            entry = pos.entry_price
            mark = pos.mark_price
            leverage = pos.leverage
            side = pos.side.lower()

            if entry > 0 and mark > 0:
                if side in ['long', 'buy']:
                    loss_pct = ((mark - entry) / entry) * leverage * 100
                else:
                    loss_pct = -((mark - entry) / entry) * leverage * 100
            else:
                loss_pct = 0.0

            fallback_actions.append({
                "symbol": pos.symbol,
                "action": "CLOSE",
                "confidence": 0,
                "rationale": f"Error: {str(e)}. Fallback CLOSE.",
                "score_breakdown": {"technical_score": 0, "loss_severity": min(100, abs(loss_pct) * 5)},
                "loss_pct_with_leverage": round(loss_pct, 2),
                "confirmations_count": 0,
                "confirmations": []
            })

        return {
            "actions": fallback_actions,
            "meta": {
                "timeout_occurred": True,
                "processing_time_ms": elapsed_ms,
                "total_positions": len(request.positions),
                "error": str(e)
            }
        }


@app.get("/health")
def health():
    return {"status": "active"}
