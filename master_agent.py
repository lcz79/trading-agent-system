import os
import json
import logging
import httpx
import asyncio
import sqlite3
from datetime import datetime, timedelta
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any, Literal, Optional, List
from openai import OpenAI

# --- CONFIGURAZIONE E LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MasterAI_V2")

app = FastAPI()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# Lock asincrono per evitare race conditions su DB/Files
db_lock = asyncio.Lock()

# --- AGENT MAPPING ---
AGENT_URLS = {
    "technical": "http://01_technical_analyzer:8000",
    "fibonacci": "http://03_fibonacci_agent:8000",
    "gann": "http://05_gann_analyzer_agent:8000",
    "news": "http://06_news_sentiment_agent:8000",
    "forecaster": "http://08_forecaster_agent:8000",
    "learning": "http://10_learning_agent:8000",
}

# --- DATABASE SQLITE (Sostituisce i JSON fragili) ---
DB_PATH = "/data/trading_system.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Tabella per Cooldown e Chiusure
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS recent_closes 
                     (symbol TEXT, side TEXT, reason TEXT, timestamp DATETIME)"""
    )
    # Tabella per Decisioni AI
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS ai_decisions 
                     (symbol TEXT, action TEXT, confidence INT, rationale TEXT, timestamp DATETIME)"""
    )
    conn.commit()
    conn.close()


init_db()

# --- UTILS ASINCRONE ---


async def save_close_event_db(symbol: str, side: str, reason: str):
    async with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO recent_closes VALUES (?, ?, ?, ?)",
            (symbol, side, reason, datetime.now().isoformat()),
        )
        # Cleanup vecchi record (>24h)
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        cursor.execute("DELETE FROM recent_closes WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()


async def get_recent_closes_db(minutes: int = 15):
    async with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        cursor.execute(
            "SELECT symbol, side FROM recent_closes WHERE timestamp > ?", (cutoff,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"symbol": r[0], "side": r[1]} for r in rows]


# --- CORE LOGIC: PARALLEL DATA COLLECTION ---


async def fetch_agent_data(client: httpx.AsyncClient, agent_key: str, endpoint: str, payload: dict):
    """Chiamata sicura con timeout e gestione errori per singolo agente"""
    url = f"{AGENT_URLS[agent_key]}/{endpoint}"
    try:
        resp = await client.post(url, json=payload, timeout=8.0)  # Timeout stretto per scalping
        return resp.json() if resp.status_code == 200 else {}
    except Exception as e:
        logger.warning(f"⚠️ Agent {agent_key} failed: {e}")
        return {}


async def collect_all_data_parallel(symbol: str, original_tech_data: dict):
    """Raccoglie dati da TUTTI gli agenti in parallelo (BOOST DI VELOCITÀ)"""
    async with httpx.AsyncClient() as http_client:
        payload = {"symbol": symbol}

        # Prepariamo i task paralleli
        tasks = {
            "fibonacci": fetch_agent_data(http_client, "fibonacci", "analyze_fib", payload),
            "gann": fetch_agent_data(http_client, "gann", "analyze_gann", payload),
            "news": fetch_agent_data(http_client, "news", "analyze_sentiment", payload),
            "forecast": fetch_agent_data(http_client, "forecaster", "forecast", payload),
        }

        # Esecuzione simultanea
        results = await asyncio.gather(*tasks.values())

        # Mappatura risultati
        final_data = dict(zip(tasks.keys(), results))
        final_data["technical"] = original_tech_data
        return final_data


# --- MODELLI DATI ---


class Decision(BaseModel):
    symbol: str
    action: Literal["OPEN_LONG", "OPEN_SHORT", "HOLD", "CLOSE"]
    leverage: float = 1.0
    size_pct: float = 0.0
    confidence: int
    rationale: str
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    time_in_trade_limit_sec: int = 1800
    blocked_by: List[str] = []


class AnalysisPayload(BaseModel):
    global_data: Dict[str, Any]
    assets_data: Dict[str, Any]
    learning_params: Optional[Dict[str, Any]] = None


# --- ENDPOINT PRINCIPALE ---


@app.post("/decide_batch")
async def decide_batch(payload: AnalysisPayload):
    start_time = datetime.now()

    # 1. Recupero Cooldown e Performance in parallelo
    recent_closes = await get_recent_closes_db()

    # 2. Arricchimento dati Asset in parallelo
    asset_tasks = []
    symbols = list(payload.assets_data.keys())
    for symbol in symbols:
        asset_tasks.append(
            collect_all_data_parallel(symbol, payload.assets_data[symbol].get("tech", {}))
        )

    enriched_results = await asyncio.gather(*asset_tasks)
    full_market_context = dict(zip(symbols, enriched_results))

    # 3. Prompt Engineering Ottimizzato
    system_instructions = """Sei un TRADER SCALPER PRO. Decidi AZIONE, LEVA (3-10x) e SIZE.
    REGOLE: 
    - Min 3 conferme per OPEN. 
    - Se return_5m < -0.6% blocca LONG (Crash Guard).
    - Se return_5m > 0.6% blocca SHORT.
    - Rispetta i cooldown.
    FORMATO JSON: {"analysis_summary": "...", "decisions": [...] }"""

    # 4. Chiamata LLM con Timeout
    try:
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": f"DATA: {json.dumps(full_market_context)}"},
                ],
                response_format={"type": "json_object"},
                timeout=15.0,  # Timeout per non bloccare lo scalping
            )
        )
        ai_content = json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"❌ LLM Critical Failure: {e}")
        return {"analysis": "Fallback: LLM Timeout", "decisions": []}

    # 5. Post-Process & Safety Guardrails
    valid_decisions = []
    for d in ai_content.get("decisions", []):
        # Esempio Guardrail Hard-Coded (Crash Guard)
        symbol = d["symbol"]
        ret_5m = (
            full_market_context.get(symbol, {})
            .get("technical", {})
            .get("summary", {})
            .get("return_5m", 0)
        )

        if d["action"] == "OPEN_LONG" and ret_5m <= -0.6:
            d["action"] = "HOLD"
            d["blocked_by"].append("CRASH_GUARD")

        valid_decisions.append(d)

    total_time = (datetime.now() - start_time).total_seconds()
    logger.info(f"✅ Batch Decision completed in {total_time:.2f}s")

    return {
        "analysis": ai_content.get("analysis_summary"),
        "decisions": valid_decisions,
        "meta": {"processing_time": total_time},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
