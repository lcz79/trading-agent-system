import os, json, time, logging
from typing import Dict, Any

from core.memory_hub import read_agent, publish
from core.exchange_router import ExchangeRouter
from core.risk_manager import RiskManager

# ... (lascia gli import invariati)

class WebbyExecutor:
    def __init__(self, agents_cfg_path="config/agents_config.json", risk_cfg_path="config/risk_parameters.json", ex_cfg_path="config/exchanges.json"):
        logging.info("[WEBBY] Inizializzazione connessione exchange...")
        self.cfg = json.load(open(agents_cfg_path,"r"))
        self.risk = RiskManager(risk_cfg_path)
        self.router = ExchangeRouter(ex_cfg_path)
        
        # Pausa per dare tempo a Webby di caricare i mercati
        time.sleep(5)
        
        self.assets = self.cfg["assets"]
        self.dedupe_minutes = int(self.cfg.get("dedupe_minutes", 30))
        self.last_sent: Dict[str, float] = {}

    # ... (lascia il resto del file invariato)

# ... (il resto del file rimane uguale)
# COPIA SOLO IL COSTRUTTORE __init__ se preferisci modificare manualmente
    def _should_fire(self, symbol: str) -> bool:
        last = self.last_sent.get(symbol, 0)
        return (time.time() - last) > (self.dedupe_minutes * 60)

    def _record_fire(self, symbol: str):
        self.last_sent[symbol] = time.time()

    def run_once(self):
        logging.info("[WEBBY] Avvio ciclo di pianificazione trade...")
        sara = read_agent("SARA")
        if not sara:
            return

        equity = float(self.risk.cfg["account_equity"])
        publish("WEBBY", "proposals", {"trades": []})
        trade_proposals = []

        for symbol, decision_pack in sara.items():
            decision = decision_pack.get("data", {})
            bias = decision.get("bias")
            
            if bias not in ("LONG", "SHORT") or not self._should_fire(symbol):
                continue

            mark_signal = decision.get("src", {}).get("mark", {})
            if mark_signal.get("signal") not in ("LONG", "SHORT"):
                continue

            ex_name = "binance"
            specs = self.router.market_specs(ex_name, symbol)
            entry, sl, tp = float(mark_signal["entry"]), float(mark_signal["sl"]), float(mark_signal["tp"])
            qty_est = self.risk.position_size(equity, entry, sl)

            if qty_est <= 0: continue

            proposal = {
                "symbol": symbol, "side": bias, "entry": entry, "sl": sl, "tp": tp,
                "qty_est": qty_est, "score": decision.get("score", 0), "logic": mark_signal.get("logic", "N/A")
            }
            trade_proposals.append(proposal)
            logging.info(f"[WEBBY] Proposta di trade generata per {symbol} ({bias})")
            self._record_fire(symbol)

        if trade_proposals:
            publish("WEBBY", "proposals", {"trades": trade_proposals})
