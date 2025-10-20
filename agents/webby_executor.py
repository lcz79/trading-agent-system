import os
import json
import time
import logging
from typing import Dict, Any

from core.memory_hub import read_agent, publish, read_latest
from core.exchange_router import ExchangeRouter
from core.risk_manager import RiskManager

class WebbyExecutor:
    def __init__(self, agents_cfg_path="config/agents_config.json", risk_cfg_path="config/risk_parameters.json", ex_cfg_path="config/exchanges.json"):
        logging.info("[WEBBY] Inizializzazione...")
        self.cfg = json.load(open(agents_cfg_path, "r"))
        self.risk = RiskManager(risk_cfg_path)
        self.router = ExchangeRouter(ex_cfg_path)
        
        time.sleep(5) 
        
        self.assets = self.cfg["assets"]
        self.dedupe_minutes = int(self.cfg.get("dedupe_minutes", 30))
        self.last_sent: Dict[str, float] = {}
        
        self.live_enabled = os.getenv("CONFIRM_LIVE", "NO").upper() == "YES"
        if self.live_enabled:
            logging.warning("[WEBBY] MODALITÀ LIVE ABILITATA. GLI ORDINI VERRANNO ESEGUITI SUL MERCATO REALE.")
        else:
            logging.info("[WEBBY] Modalità Dry Run. Gli ordini verranno solo simulati.")

    def _should_fire(self, symbol: str) -> bool:
        last = self.last_sent.get(symbol, 0)
        return (time.time() - last) > (self.dedupe_minutes * 60)

    def _record_fire(self, symbol: str):
        self.last_sent[symbol] = time.time()

    def place_real_order(self, trade_details: Dict[str, Any]):
        symbol = trade_details["symbol"]
        side = trade_details["side"].lower()
        qty = trade_details["qty_est"]
        ex_name = "bybit"
        exchange = self.router.get(ex_name)

        if not exchange:
            logging.error(f"[WEBBY][EXECUTE] Exchange '{ex_name}' non trovato.")
            return

        logging.info(f"[WEBBY][EXECUTE] Tentativo di esecuzione ordine per {symbol}...")
        
        try:
            if self.live_enabled:
                logging.warning(f"[WEBBY][LIVE] ESECUZIONE ORDINE A MERCATO: {side.upper()} {qty:.4f} {symbol}")
                order = exchange.create_market_order(symbol, side, qty)
                logging.info(f"[WEBBY][LIVE] Ordine eseguito con successo. ID: {order.get('id')}")
            else:
                logging.info(f"[WEBBY][DRY RUN] Simulazione ordine a mercato: {side.upper()} {qty:.4f} {symbol}")
        except Exception as e:
            logging.error(f"[WEBBY][EXECUTE] ERRORE durante l'esecuzione dell'ordine per {symbol}: {e}")

    def check_and_execute_commands(self):
        command = read_latest("COMMAND", "execute")
        if not command:
            return

        logging.warning(f"[WEBBY] Comando di esecuzione ricevuto per {command['symbol']}!")
        self.place_real_order(command)
        publish("COMMAND", "execute", None)

    def plan_new_proposals(self):
        sara = read_agent("SARA")
        if not sara:
            return

        equity = float(self.risk.cfg["account_equity"])
        trade_proposals = []

        # --- LA CORREZIONE È QUI ---
        # Prima: for symbol, decision_pack in sara.items():
        # Ora: Iteriamo sulla lista di asset puliti per garantire coerenza
        for clean_symbol in self.assets:
            decision_pack = sara.get(clean_symbol)
            if not decision_pack:
                continue

            decision = decision_pack.get("data", {})
            bias = decision.get("bias")
            
            if bias not in ("LONG", "SHORT") or not self._should_fire(clean_symbol):
                continue

            mark_signal = decision.get("src", {}).get("mark", {})
            if mark_signal.get("signal") not in ("LONG", "SHORT"):
                continue

            ex_name = "bybit"
            specs = self.router.market_specs(ex_name, clean_symbol)
            entry, sl, tp = float(mark_signal["entry"]), float(mark_signal["sl"]), float(mark_signal["tp"])
            qty_est = self.risk.position_size(equity, entry, sl)
            
            amount_precision = specs.get('precision', {}).get('amount')
            if amount_precision is not None:
                qty_est = round(qty_est, int(amount_precision))

            if qty_est <= specs.get('min_qty', 0): continue

            # Usiamo 'clean_symbol' per creare la proposta
            proposal = {
                "symbol": clean_symbol, "side": bias, "entry": entry, "sl": sl, "tp": tp,
                "qty_est": qty_est, "score": decision.get("score", 0), "logic": mark_signal.get("logic", "N/A")
            }
            trade_proposals.append(proposal)
            self._record_fire(clean_symbol)

        if trade_proposals:
            logging.info(f"[WEBBY] Generate {len(trade_proposals)} nuove proposte di trade.")
            publish("WEBBY", "proposals", {"trades": trade_proposals})

    def run_once(self):
        self.check_and_execute_commands()
        self.plan_new_proposals()
