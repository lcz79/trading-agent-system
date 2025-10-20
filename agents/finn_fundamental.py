import logging
from core.memory_hub import publish
class FinnFundamental:
    def run(self):
        res = {"macro_trend": "neutral", "score": 0.0, "reason": "Stub"}
        publish("FINN", "GLOBAL", res)
        logging.info("[FINN] Analisi macro: neutra (agente stub).")