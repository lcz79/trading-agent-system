from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from main import manage_trade

app = FastAPI(
    title="Trade Guardian Agent",
    description="Un agente che monitora una posizione aperta e decide come gestirla.",
    version="1.0.0",
)

class GuardianInput(BaseModel):
    current_price: float
    entry_price: float
    direction: str
    tech_analysis: Dict[str, Any]

@app.post("/manage_position/")
async def manage_position_endpoint(input_data: GuardianInput):
    """
    Riceve i dati di una posizione aperta e l'analisi tecnica aggiornata,
    e restituisce una decisione di gestione.
    """
    try:
        decision = manage_trade(
            current_price=input_data.current_price,
            entry_price=input_data.entry_price,
            direction=input_data.direction,
            tech_analysis=input_data.tech_analysis
        )
        return decision
    except Exception as e:
        # Questo è un gestore di errori generico, va bene così
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def health_check():
    return {"status": "Trade Guardian Agent is running"}