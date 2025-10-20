import os, json, logging
from typing import Dict, Any

try: import ccxt
except Exception: ccxt = None

class ExchangeRouter:
    def __init__(self, cfg_path: str = "config/exchanges.json"):
        assert ccxt is not None, "ccxt non installato. pip install ccxt"
        raw = json.load(open(cfg_path, "r"))
        self.exchanges: Dict[str, Any] = {}
        for name, info in raw.items():
            ex_type = info["type"]
            api_key, api_secret = os.getenv(f"{name.upper()}_API_KEY"), os.getenv(f"{name.upper()}_API_SECRET")
            args = {"apiKey": api_key, "secret": api_secret, "enableRateLimit": info.get("rate_limit", True)}
            try:
                ex = getattr(ccxt, ex_type)(args)
                ex.load_markets()
                self.exchanges[name] = ex
                logging.info(f"Exchange '{name}' connesso con successo.")
            except Exception as e: logging.warning(f"[{name}] Connessione fallita: {e}")

    def get(self, name: str): return self.exchanges.get(name)

    def market_specs(self, name: str, symbol: str) -> Dict[str, float]:
        ex = self.get(name)
        if not ex: return {"tick_size": 0.01, "min_qty": 1.0}
        unified_symbol = symbol.replace("/", "")
        market = ex.market(unified_symbol) if unified_symbol in ex.markets else ex.market(symbol) if symbol in ex.markets else None
        if not market: return {"tick_size": 0.01, "min_qty": 1.0}
        precision, limits = market.get("precision", {}), market.get("limits", {})
        tick_size = float(precision.get("price", 0.01))
        min_qty = float(limits.get("amount", {}).get("min", 1.0))
        return {"tick_size": tick_size, "min_qty": min_qty}