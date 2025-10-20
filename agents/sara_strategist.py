import logging
from typing import Dict, Any, List
from core.memory_hub import read_latest, publish

class SaraStrategist:
    def __init__(self, assets: List[str]): self.assets = assets
    def combine(self, symbol: str):
        mark = read_latest("MARK", symbol) or {"signal": "NEUTRAL"}
        news = read_latest("VITTORIA", "GLOBAL") or {"sentiment": 0.0}
        finn = read_latest("FINN", "GLOBAL") or {"macro_trend": "neutral"}
        score, bias = 0.0, "NEUTRAL"
        if mark.get("signal")=="LONG": score+=1.0
        elif mark.get("signal")=="SHORT": score-=1.0
        sentiment = news.get("sentiment",0.0)
        if sentiment > 0.15: score+=0.3
        elif sentiment < -0.15: score-=0.3
        if finn.get("macro_trend")=="positive": score+=0.2
        elif finn.get("macro_trend")=="negative": score-=0.2
        if score >= 0.8: bias = "LONG"
        elif score <= -0.8: bias = "SHORT"
        decision = {"symbol":symbol, "bias":bias, "score":round(score,2), "src":{"mark":mark,"news":news,"finn":finn}}
        publish("SARA", symbol, decision)
        if bias != "NEUTRAL": logging.info(f"[SARA] {symbol} -> Decisione: {bias} (Punteggio: {score:.2f})")
    def run(self):
        logging.info("[SARA] Avvio processo decisionale...")
        for s in self.assets: self.combine(s)