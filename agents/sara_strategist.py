import logging
from typing import List, Dict, Any

from core.memory_hub import read_agent, publish

class SaraStrategist:
    def __init__(self, assets: List[str]):
        self.assets = assets

    def run_once(self):
        logging.info("[SARA] Avvio processo decisionale...")
        
        mark_data = read_agent("MARK")
        vittoria_data = read_agent("VITTORIA")
        finn_data = read_agent("FINN")

        if not mark_data:
            return

        for symbol in self.assets:
            # Pulisce il simbolo per la ricerca nel memory hub
            clean_symbol = symbol.split(':')[0]

            mark_signal = mark_data.get(clean_symbol, {}).get("data", {})
            vittoria_sentiment = vittoria_data.get("sentiment", 0.0)
            finn_macro = finn_data.get("macro_view", "NEUTRAL")

            bias = mark_signal.get("signal", "NEUTRAL")
            logic = mark_signal.get("logic", "")
            
            score = 0
            if bias == "LONG": score += 1
            if bias == "SHORT": score -= 1
            
            # Per ora, gli altri agenti non influenzano la decisione
            # In futuro, potremmo aggiungere logica come:
            # if vittoria_sentiment > 0.5: score += 1
            # if finn_macro == "BULLISH": score += 1

            decision = "NEUTRAL"
            if score > 0: decision = "LONG"
            if score < 0: decision = "SHORT"

            if decision != "NEUTRAL":
                decision_data = {
                    "bias": decision,
                    "score": score,
                    "src": {
                        "mark": mark_signal,
                        "vittoria": {"sentiment": vittoria_sentiment},
                        "finn": {"macro": finn_macro}
                    }
                }
                
                # --- LA CORREZIONE È QUI ---
                # Prima: publish("SARA", f"{clean_symbol}:USDT", {"data": decision_data})
                # Ora: Pubblichiamo usando solo il simbolo pulito.
                publish("SARA", clean_symbol, {"data": decision_data})
                # -------------------------

                logging.info(f"[SARA] {clean_symbol} -> Decisione: {decision} (Punteggio: {score:.2f})")
