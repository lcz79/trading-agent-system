import os
import json
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
from typing import Dict, Any, List, Literal
from openai import OpenAI

# Configurazione Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MasterAI")

app = FastAPI()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY non impostata nell'ambiente")

client = OpenAI(api_key=OPENAI_API_KEY)

# --- MODELLI DATI E SICUREZZA ---
class Decision(BaseModel):
    symbol: str
    # AGGIUNTO "CLOSE" PER PERMETTERE ALL'AI DI USCIRE DAI TRADE
    action: Literal["OPEN_LONG", "OPEN_SHORT", "HOLD", "CLOSE"]
    leverage: float
    size_pct: float
    rationale: str

    @field_validator("leverage")
    @classmethod
    def clamp_leverage(cls, v: float) -> float:
        # SICUREZZA: Forza la leva tra 1x e 10x anche se l'AI sbaglia
        if v < 1: return 1
        if v > 10: return 10
        return v

    @field_validator("size_pct")
    @classmethod
    def clamp_size_pct(cls, v: float) -> float:
        # SICUREZZA: Mai rischiare più del 20% del wallet su un singolo trade
        if v < 0: return 0
        if v > 0.2: return 0.2
        return v

class AnalysisPayload(BaseModel):
    global_data: Dict[str, Any]
    assets_data: Dict[str, Any]

# --- PROMPT AGENTE ALPHA HUNTER ---
SYSTEM_PROMPT = """
Sei il CAPO TRADER di un Hedge Fund Algoritmico.
Il tuo obiettivo è generare ALPHA (profitto), non solo evitare rischi.

FILOSOFIA DI TRADING:
1. Non cercare la perfezione: i mercati sono caotici, non servono conferme al 100%.
2. Pesa le probabilità: se alcuni segnali sono contrari al trend principale, puoi valutare scalp contro-trend.
3. Timeframe Mastery:
   - Se il 4H è confuso ma il 15m mostra un setup pulito -> valuta uno SCALP.
   - Se il 4H è direzionale e il 15m è allineato -> valuta uno SWING con più size.
4. Gestione Posizioni:
   - Se hai posizioni aperte che stanno invalidando la tesi -> NON ESITARE A DARE ORDINE "CLOSE".

FORMATO OUTPUT JSON (TASSATIVO):
Devi fornire un oggetto JSON con:
- "reasoning_chain": Una spiegazione strategica (Pensiero ad alta voce).
- "analysis_summary": Sintesi operativa brevissima.
- "decisions": Una lista di oggetti decisione.

Le azioni valide sono: "OPEN_LONG", "OPEN_SHORT", "HOLD", "CLOSE".
"""

@app.post("/decide_batch")
def decide_batch(payload: AnalysisPayload):
    logger.info("🧠 MASTER AI: Valutazione opportunità in corso...")

    # Log sintetico per debug
    try:
        asset_list = list(payload.assets_data.keys())
    except Exception:
        asset_list = []
    logger.info(f"Asset sotto esame: {asset_list}")

    # Serializzazione efficiente
    data_str = json.dumps(payload.dict(), separators=(",", ":"), ensure_ascii=False)

    full_prompt = f"""
Analizza i seguenti dati di mercato (globali + per asset).
Cerca opportunità concrete (SCALP o SWING), senza paralisi da analisi.

DATI:
{data_str}

Ricorda: Prima il ragionamento ('reasoning_chain'), poi la decisione.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-5.1", # TUA CONFIGURAZIONE ESPLICITA
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.5, # Bilanciamento creatività/logica
        )

        resp_content = response.choices[0].message.content

        try:
            decision_json = json.loads(resp_content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON non valido dall'AI: {e}")
            raise HTTPException(status_code=502, detail="Risposta AI malformata")

        reasoning_chain = decision_json.get("reasoning_chain", "Nessun ragionamento fornito.")
        analysis_summary = decision_json.get("analysis_summary", "Nessuna sintesi.")
        raw_decisions = decision_json.get("decisions", [])

        # --- LOG DEL PENSIERO (Fondamentale per capire l'AI) ---
        logger.info(f"\n🧠 STRATEGIA AI (GPT-5.1):\n{reasoning_chain[:1500]}...\n------------------------")

        # Validazione decisioni con Pydantic (Clamping automatico)
        decisions: List[Decision] = []
        for d in raw_decisions:
            try:
                validated_d = Decision(**d)
                decisions.append(validated_d)
            except Exception as e:
                logger.warning(f"⚠️ Decisione scartata per errore validazione: {e} | Dati: {d}")

        return {
            "analysis": analysis_summary,
            "decisions": [d.model_dump() for d in decisions],
            "full_thought": reasoning_chain # Utile per debug futuri
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Errore critico AI: {e}")
        raise HTTPException(status_code=500, detail=f"Errore interno Master AI: {str(e)}")


@app.get("/health")
def health():
    return {"status": "active", "mode": "ALPHA_HUNTER_SAFEGUARDED"}
