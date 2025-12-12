import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LearningAgent")

app = FastAPI()

# Configuration
EVOLUTION_INTERVAL_HOURS = int(os.getenv("EVOLUTION_INTERVAL_HOURS", "48"))
MIN_TRADES_FOR_EVOLUTION = int(os.getenv("MIN_TRADES_FOR_EVOLUTION", "5"))
BACKTEST_IMPROVEMENT_THRESHOLD = float(os.getenv("BACKTEST_IMPROVEMENT_THRESHOLD", "0.5"))
MAX_STRATEGY_ARCHIVE = int(os.getenv("MAX_STRATEGY_ARCHIVE", "20"))

DATA_DIR = "/data"
EVOLVED_PARAMS_FILE = f"{DATA_DIR}/evolved_params.json"
TRADING_HISTORY_FILE = f"{DATA_DIR}/trading_history.json"
EVOLUTION_LOG_FILE = f"{DATA_DIR}/evolution_log.json"
STRATEGY_ARCHIVE_DIR = f"{DATA_DIR}/strategy_archive"
API_COSTS_FILE = f"{DATA_DIR}/api_costs.json"

# Default parameters
DEFAULT_PARAMS = {
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "default_leverage": 5,
    "size_pct": 0.15,
    "reverse_threshold": 2.0,
    "atr_multiplier_sl": 2.0,
    "atr_multiplier_tp": 3.0,
    "min_rsi_for_long": 40,
    "max_rsi_for_short": 60,
}

# DeepSeek client
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com") if DEEPSEEK_API_KEY else None


def log_api_call(tokens_in: int, tokens_out: int):
    """
    Logga una chiamata API per il tracking dei costi DeepSeek.
    
    Args:
        tokens_in: Token input della richiesta
        tokens_out: Token output della risposta
    """
    try:
        # Carica i dati esistenti
        if os.path.exists(API_COSTS_FILE):
            with open(API_COSTS_FILE, 'r') as f:
                data = json.load(f)
        else:
            data = {'calls': []}
        
        # Aggiungi la nuova chiamata
        data['calls'].append({
            'timestamp': datetime.now().isoformat(),
            'tokens_in': tokens_in,
            'tokens_out': tokens_out
        })
        
        # Salva i dati aggiornati
        os.makedirs(os.path.dirname(API_COSTS_FILE), exist_ok=True)
        with open(API_COSTS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"API call logged: {tokens_in} in, {tokens_out} out")
    except Exception as e:
        logger.error(f"Error logging API call: {e}")



class TradeRecord(BaseModel):
    timestamp: str
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    leverage: float
    size_pct: float
    duration_minutes: Optional[int] = None
    market_conditions: Dict[str, Any] = {}


def ensure_directories():
    """Ensure all required directories exist"""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(STRATEGY_ARCHIVE_DIR, exist_ok=True)


def load_json_file(filepath: str, default: Any = None):
    """Load JSON file with error handling"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
        return default if default is not None else []
    except Exception as e:
        logger.error(f"Error loading {filepath}: {e}")
        return default if default is not None else []


def save_json_file(filepath: str, data: Any):
    """Save data to JSON file with error handling"""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")
        return False


def load_current_params() -> Dict[str, Any]:
    """Load current evolved parameters or defaults"""
    data = load_json_file(EVOLVED_PARAMS_FILE, {})
    return data.get("params", DEFAULT_PARAMS.copy())


def get_recent_trades(hours: int = 48) -> List[Dict[str, Any]]:
    """Get trades from the last N hours"""
    all_trades = load_json_file(TRADING_HISTORY_FILE, [])
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    recent_trades = []
    for trade in all_trades:
        try:
            trade_time = datetime.fromisoformat(trade.get('timestamp', ''))
            if trade_time >= cutoff_time:
                recent_trades.append(trade)
        except (ValueError, TypeError):
            continue
    
    return recent_trades


def calculate_performance(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate performance metrics from trade list"""
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_duration": 0,
            "max_drawdown": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
        }
    
    completed_trades = [t for t in trades if t.get('pnl_pct') is not None]
    
    if not completed_trades:
        return {
            "total_trades": len(trades),
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_duration": 0,
            "max_drawdown": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
        }
    
    total_pnl = sum(t.get('pnl_pct', 0) for t in completed_trades)
    winning_trades = [t for t in completed_trades if t.get('pnl_pct', 0) > 0]
    losing_trades = [t for t in completed_trades if t.get('pnl_pct', 0) <= 0]
    
    win_rate = len(winning_trades) / len(completed_trades) if completed_trades else 0
    
    durations = [t.get('duration_minutes', 0) for t in completed_trades if t.get('duration_minutes')]
    avg_duration = sum(durations) / len(durations) if durations else 0
    
    # Simple drawdown calculation
    cumulative_pnl = 0
    peak = 0
    max_drawdown = 0
    for trade in completed_trades:
        cumulative_pnl += trade.get('pnl_pct', 0)
        peak = max(peak, cumulative_pnl)
        drawdown = peak - cumulative_pnl
        max_drawdown = max(max_drawdown, drawdown)
    
    return {
        "total_trades": len(completed_trades),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "avg_duration": round(avg_duration, 0),
        "max_drawdown": round(max_drawdown, 2),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
    }


async def call_deepseek(prompt: str) -> str:
    """Call DeepSeek API for analysis"""
    if not client:
        logger.warning("DeepSeek client not configured")
        return "{}"
    
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an expert trading strategy analyst. Respond ONLY with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        
        # Logga i costi API per tracking DeepSeek
        if hasattr(response, 'usage') and response.usage:
            log_api_call(
                tokens_in=response.usage.prompt_tokens,
                tokens_out=response.usage.completion_tokens
            )
        
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return "{}"


def parse_suggestions(suggestions_json: str) -> Dict[str, Any]:
    """Parse DeepSeek suggestions into parameter dictionary"""
    try:
        data = json.loads(suggestions_json)
        suggested_params = data.get("suggested_params", {})
        
        # Validate and constrain parameters
        params = DEFAULT_PARAMS.copy()
        
        if "rsi_overbought" in suggested_params:
            params["rsi_overbought"] = max(60, min(80, suggested_params["rsi_overbought"]))
        if "rsi_oversold" in suggested_params:
            params["rsi_oversold"] = max(20, min(40, suggested_params["rsi_oversold"]))
        if "default_leverage" in suggested_params:
            params["default_leverage"] = max(1, min(10, suggested_params["default_leverage"]))
        if "size_pct" in suggested_params:
            params["size_pct"] = max(0.05, min(0.25, suggested_params["size_pct"]))
        if "reverse_threshold" in suggested_params:
            params["reverse_threshold"] = max(0.5, min(5.0, suggested_params["reverse_threshold"]))
        if "atr_multiplier_sl" in suggested_params:
            params["atr_multiplier_sl"] = max(1.0, min(4.0, suggested_params["atr_multiplier_sl"]))
        if "atr_multiplier_tp" in suggested_params:
            params["atr_multiplier_tp"] = max(1.5, min(6.0, suggested_params["atr_multiplier_tp"]))
        if "min_rsi_for_long" in suggested_params:
            params["min_rsi_for_long"] = max(30, min(50, suggested_params["min_rsi_for_long"]))
        if "max_rsi_for_short" in suggested_params:
            params["max_rsi_for_short"] = max(50, min(70, suggested_params["max_rsi_for_short"]))
        
        return params
    except Exception as e:
        logger.error(f"Error parsing suggestions: {e}")
        return DEFAULT_PARAMS.copy()


def backtest_strategy(trades: List[Dict[str, Any]], new_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simple backtest: simulate how trades would have performed with new parameters.
    This is a simplified version - in practice, you'd re-evaluate entry/exit decisions.
    """
    # For simplicity, we'll adjust the PnL based on leverage and size changes
    current_params = load_current_params()
    
    adjusted_trades = []
    total_pnl = 0
    
    for trade in trades:
        if trade.get('pnl_pct') is None:
            continue
        
        # Simulate adjustment based on parameter changes
        leverage_ratio = new_params.get('default_leverage', 5) / current_params.get('default_leverage', 5)
        size_ratio = new_params.get('size_pct', 0.15) / current_params.get('size_pct', 0.15)
        
        # Adjust PnL (simplified - real backtest would be more complex)
        adjusted_pnl = trade['pnl_pct'] * leverage_ratio * size_ratio
        adjusted_trades.append({**trade, 'pnl_pct': adjusted_pnl})
        total_pnl += adjusted_pnl
    
    performance = calculate_performance(adjusted_trades)
    return performance


def save_evolved_params(new_params: Dict[str, Any], current_perf: Dict[str, Any], 
                        backtest_perf: Dict[str, Any], mutation_log: str = ""):
    """Save evolved parameters to file"""
    # Get current version and increment
    current_data = load_json_file(EVOLVED_PARAMS_FILE, {})
    current_version = current_data.get("version", "v0.0")
    
    try:
        version_num = float(current_version.replace("v", ""))
        new_version = f"v{version_num + 0.1:.1f}"
    except:
        new_version = "v1.0"
    
    data = {
        "version": new_version,
        "evolved_at": datetime.now().isoformat(),
        "params": new_params,
        "performance": {
            "before": current_perf,
            "after_backtest": backtest_perf
        },
        "mutation_log": mutation_log
    }
    
    save_json_file(EVOLVED_PARAMS_FILE, data)
    logger.info(f"✅ Saved evolved params {new_version}")
    
    return new_version


def archive_strategy(params: Dict[str, Any], version: str):
    """Archive strategy to strategy_archive directory"""
    try:
        filepath = f"{STRATEGY_ARCHIVE_DIR}/strategy_{version}.json"
        data = {
            "version": version,
            "timestamp": datetime.now().isoformat(),
            "params": params
        }
        save_json_file(filepath, data)
        
        # Clean old archives if exceeding limit
        archives = sorted([f for f in os.listdir(STRATEGY_ARCHIVE_DIR) if f.endswith('.json')])
        if len(archives) > MAX_STRATEGY_ARCHIVE:
            for old_archive in archives[:-MAX_STRATEGY_ARCHIVE]:
                os.remove(f"{STRATEGY_ARCHIVE_DIR}/{old_archive}")
                logger.info(f"🗑️ Removed old archive: {old_archive}")
        
        logger.info(f"📁 Archived strategy {version}")
    except Exception as e:
        logger.error(f"Error archiving strategy: {e}")


def log_evolution(status: str, details: Dict[str, Any]):
    """Log evolution events"""
    try:
        log_entries = load_json_file(EVOLUTION_LOG_FILE, [])
        log_entries.append({
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "details": details
        })
        # Keep only last 50 entries
        log_entries = log_entries[-50:]
        save_json_file(EVOLUTION_LOG_FILE, log_entries)
    except Exception as e:
        logger.error(f"Error logging evolution: {e}")


async def profit_evolution_cycle():
    """Main ProFiT evolution cycle - runs every 48 hours"""
    logger.info("🧬 PROFIT EVOLUTION START")
    
    try:
        # 1. Collect recent trades
        trades = get_recent_trades(hours=EVOLUTION_INTERVAL_HOURS)
        logger.info(f"📊 Analyzing last {EVOLUTION_INTERVAL_HOURS} hours: {len(trades)} trades")
        
        if len(trades) < MIN_TRADES_FOR_EVOLUTION:
            logger.info(f"⏸️ Not enough trades for evolution (need {MIN_TRADES_FOR_EVOLUTION}, got {len(trades)}), skipping")
            log_evolution("skipped", {"reason": "insufficient_trades", "count": len(trades)})
            return
        
        # 2. Calculate current performance
        current_performance = calculate_performance(trades)
        current_params = load_current_params()
        
        logger.info(f"📈 Current performance:")
        logger.info(f"   - Win rate: {current_performance['win_rate']*100:.1f}%")
        logger.info(f"   - Total PnL: {current_performance['total_pnl']:.2f}%")
        logger.info(f"   - Max drawdown: {current_performance['max_drawdown']:.2f}%")
        
        # 3. Ask DeepSeek for analysis and improvements
        logger.info("🤖 Asking DeepSeek for improvements...")
        
        analysis_prompt = f"""
Analyze these trading performance metrics and propose improvements to the parameters.

Performance over last {EVOLUTION_INTERVAL_HOURS} hours:
- Trades total: {current_performance['total_trades']}
- Win rate: {current_performance['win_rate']*100:.1f}%
- Total PnL: {current_performance['total_pnl']:.2f}%
- Average trade duration: {current_performance['avg_duration']:.0f} minutes
- Max drawdown: {current_performance['max_drawdown']:.2f}%
- Winning trades: {current_performance['winning_trades']}
- Losing trades: {current_performance['losing_trades']}

Current parameters:
{json.dumps(current_params, indent=2)}

Sample trades (first 5):
{json.dumps(trades[:5], indent=2)}

Propose SPECIFIC modifications to the parameters to improve performance.
Consider:
- If win rate is low, consider adjusting RSI thresholds
- If drawdown is high, consider reducing leverage or size
- If PnL is negative, consider more conservative settings

Respond ONLY with valid JSON in this format:
{{
  "suggested_params": {{
    "rsi_overbought": <value 60-80>,
    "rsi_oversold": <value 20-40>,
    "default_leverage": <value 1-10>,
    "size_pct": <value 0.05-0.25>,
    "reverse_threshold": <value 0.5-5.0>,
    "atr_multiplier_sl": <value 1.0-4.0>,
    "atr_multiplier_tp": <value 1.5-6.0>,
    "min_rsi_for_long": <value 30-50>,
    "max_rsi_for_short": <value 50-70>
  }},
  "reasoning": "Brief explanation of changes"
}}
"""
        
        suggestions = await call_deepseek(analysis_prompt)
        new_params = parse_suggestions(suggestions)
        
        # Extract reasoning
        try:
            suggestion_data = json.loads(suggestions)
            reasoning = suggestion_data.get("reasoning", "No reasoning provided")
        except (json.JSONDecodeError, TypeError):
            reasoning = "Could not parse reasoning"
        
        logger.info(f"💡 DeepSeek suggests:")
        for key, value in new_params.items():
            if key in current_params and current_params[key] != value:
                logger.info(f"   - {key}: {current_params[key]} → {value}")
        logger.info(f"   Reasoning: {reasoning}")
        
        # 4. Backtest with new parameters
        logger.info("🧪 Backtesting new strategy...")
        backtest_result = backtest_strategy(trades, new_params)
        
        logger.info(f"📊 Backtest result:")
        logger.info(f"   - Win rate: {backtest_result['win_rate']*100:.1f}% ({(backtest_result['win_rate']-current_performance['win_rate'])*100:+.1f}%)")
        logger.info(f"   - Total PnL: {backtest_result['total_pnl']:.2f}% ({backtest_result['total_pnl']-current_performance['total_pnl']:+.2f}%)")
        logger.info(f"   - Max drawdown: {backtest_result['max_drawdown']:.2f}%")
        
        # 5. Decide if new strategy is better
        pnl_improvement = backtest_result['total_pnl'] - current_performance['total_pnl']
        
        if pnl_improvement > BACKTEST_IMPROVEMENT_THRESHOLD:
            new_version = save_evolved_params(new_params, current_performance, backtest_result, reasoning)
            archive_strategy(new_params, new_version)
            logger.info(f"✅ Evolution successful! New strategy {new_version} saved")
            logger.info(f"💾 Saved: {EVOLVED_PARAMS_FILE}")
            logger.info(f"📁 Archived: {STRATEGY_ARCHIVE_DIR}/strategy_{new_version}.json")
            logger.info(f"🔄 Master AI will use new params from next cycle")
            
            log_evolution("success", {
                "version": new_version,
                "improvement": pnl_improvement,
                "new_params": new_params
            })
        else:
            logger.info(f"❌ New strategy didn't improve significantly (improvement: {pnl_improvement:.2f}%), keeping current params")
            logger.info(f"   Required improvement: >{BACKTEST_IMPROVEMENT_THRESHOLD}%")
            
            log_evolution("rejected", {
                "reason": "insufficient_improvement",
                "improvement": pnl_improvement,
                "threshold": BACKTEST_IMPROVEMENT_THRESHOLD
            })
        
    except Exception as e:
        logger.error(f"❌ Evolution cycle error: {e}", exc_info=True)
        log_evolution("error", {"error": str(e)})


async def evolution_loop():
    """Background task that runs evolution every N hours"""
    interval_seconds = EVOLUTION_INTERVAL_HOURS * 3600
    
    logger.info(f"🔄 Starting evolution loop (every {EVOLUTION_INTERVAL_HOURS} hours)")
    
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await profit_evolution_cycle()
        except Exception as e:
            logger.error(f"Evolution loop error: {e}")
            await asyncio.sleep(3600)  # Wait 1 hour on error


# API Endpoints

@app.post("/record_trade")
async def record_trade(trade: TradeRecord):
    """Record a completed trade for analysis"""
    try:
        trades = load_json_file(TRADING_HISTORY_FILE, [])
        trades.append(trade.model_dump())
        save_json_file(TRADING_HISTORY_FILE, trades)
        
        logger.info(f"📝 Recorded trade: {trade.symbol} {trade.side} PnL: {trade.pnl_pct}%")
        
        return {"status": "success", "message": "Trade recorded"}
    except Exception as e:
        logger.error(f"Error recording trade: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/trigger_evolution")
async def trigger_evolution():
    """Manually trigger an evolution cycle"""
    try:
        await profit_evolution_cycle()
        return {"status": "success", "message": "Evolution cycle completed"}
    except Exception as e:
        logger.error(f"Error triggering evolution: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/current_params")
async def get_current_params():
    """Get current evolved parameters"""
    try:
        data = load_json_file(EVOLVED_PARAMS_FILE, {})
        if not data:
            return {
                "status": "default",
                "version": "v0.0",
                "params": DEFAULT_PARAMS
            }
        
        return {
            "status": "evolved",
            "version": data.get("version", "unknown"),
            "params": data.get("params", DEFAULT_PARAMS),
            "evolved_at": data.get("evolved_at", "unknown")
        }
    except Exception as e:
        logger.error(f"Error getting params: {e}")
        return {"status": "error", "params": DEFAULT_PARAMS}


@app.get("/performance")
async def get_performance():
    """Get recent performance metrics"""
    try:
        trades = get_recent_trades(hours=EVOLUTION_INTERVAL_HOURS)
        performance = calculate_performance(trades)
        
        return {
            "status": "success",
            "period_hours": EVOLUTION_INTERVAL_HOURS,
            "performance": performance
        }
    except Exception as e:
        logger.error(f"Error getting performance: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/evolution_log")
async def get_evolution_log():
    """Get recent evolution log entries"""
    try:
        log_entries = load_json_file(EVOLUTION_LOG_FILE, [])
        return {
            "status": "success",
            "entries": log_entries[-10:]  # Last 10 entries
        }
    except Exception as e:
        logger.error(f"Error getting evolution log: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/health")
def health():
    return {
        "status": "active",
        "evolution_interval_hours": EVOLUTION_INTERVAL_HOURS,
        "min_trades_for_evolution": MIN_TRADES_FOR_EVOLUTION
    }


@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    ensure_directories()
    logger.info("🚀 Learning Agent started")
    logger.info(f"📊 Configuration:")
    logger.info(f"   - Evolution interval: {EVOLUTION_INTERVAL_HOURS} hours")
    logger.info(f"   - Min trades for evolution: {MIN_TRADES_FOR_EVOLUTION}")
    logger.info(f"   - Improvement threshold: {BACKTEST_IMPROVEMENT_THRESHOLD}%")
    logger.info(f"   - Max strategy archive: {MAX_STRATEGY_ARCHIVE}")
    
    # Start evolution loop in background
    asyncio.create_task(evolution_loop())
