from fastapi import FastAPI
from pydantic import BaseModel
from indicators import CryptoTechnicalAnalysisBybit

app = FastAPI()
analyzer = CryptoTechnicalAnalysisBybit()

class TechRequest(BaseModel):
    symbol: str

@app.post("/analyze_multi_tf")
def analyze_endpoint(req: TechRequest):
    """Endpoint per analisi multi-timeframe"""
    data = analyzer.get_multi_tf_analysis(req.symbol)
    if not data or not data.get("timeframes"):
        return {"symbol": req.symbol, "error": "Multi-TF Analysis Failed", "timeframes": {}}
    return data

@app.get("/health")
def health(): return {"status": "active"}

@app.post("/analyze_multi_tf_full")
def analyze_multi_tf_endpoint(req: TechRequest):
    """Endpoint per analisi multi-timeframe completa"""
    data = analyzer.get_multi_tf_analysis(req.symbol)
    if not data or not data.get("timeframes"):
        return {"symbol": req.symbol, "error": "Multi-TF Analysis Failed", "timeframes": {}}
    return data
