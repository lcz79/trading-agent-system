import os
import json
import logging
from typing import Dict, Any

try:
    import ccxt
except ImportError:
    ccxt = None

class ExchangeRouter:
    def __init__(self, cfg_path: str = "config/exchanges.json"):
        if ccxt is None:
            raise ImportError("La libreria 'ccxt' non è installata. Esegui: pip install ccxt")
        
        try:
            with open(cfg_path, "r") as f:
                raw = json.load(f)
        except FileNotFoundError:
            logging.error(f"File di configurazione exchange non trovato in {cfg_path}")
            raw = {}

        self.exchanges: Dict[str, Any] = {}
        for name, info in raw.items():
            ex_type = info.get("type")
            if not ex_type:
                logging.warning(f"Nessun 'type' specificato per l'exchange '{name}' in {cfg_path}")
                continue

            api_key = os.getenv(f"{name.upper()}_API_KEY")
            api_secret = os.getenv(f"{name.upper()}_API_SECRET")
            
            if not (api_key and api_secret):
                logging.warning(f"Chiavi API non trovate per l'exchange '{name}'. Questo exchange potrebbe non funzionare per operazioni autenticate.")

            args = {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": info.get("rate_limit", True)
            }

            try:
                exchange_class = getattr(ccxt, ex_type)
                ex = exchange_class(args)
                ex.load_markets()
                self.exchanges[name] = ex
                logging.info(f"Exchange '{name}' connesso con successo.")
            except Exception as e:
                logging.warning(f"[{name}] Connessione fallita: {e}")

    def get(self, name: str):
        return self.exchanges.get(name)

    def market_specs(self, name: str, symbol: str) -> Dict[str, Any]:
        ex = self.get(name)
        default_specs = {"tick_size": 0.01, "min_qty": 1.0, "precision": {"amount": 3, "price": 4}}
        if not ex:
            return default_specs

        # --- LOGICA DI PULIZIA DEL SIMBOLO ---
        # Rimuove eventuali suffissi ":USDT" o simili che ccxt a volte aggiunge
        clean_symbol = symbol.split(':')[0]
        # ------------------------------------

        unified_symbol = clean_symbol.replace("/", "")
        
        market = None
        if unified_symbol in ex.markets:
            market = ex.market(unified_symbol)
        elif clean_symbol in ex.markets:
            market = ex.market(clean_symbol)
        elif f"{unified_symbol}.P" in ex.markets:  # Per simboli come MATICUSDT.P
            market = ex.market(f"{unified_symbol}.P")

        if not market:
            logging.warning(f"[ROUTER] Specifiche di mercato non trovate per {symbol}. Uso default.")
            return default_specs

        precision = market.get("precision", default_specs["precision"])
        limits = market.get("limits", {"amount": {"min": 1.0}})
        
        tick_size = float(precision.get("price", 0.01))
        min_qty = float(limits.get("amount", {}).get("min", 1.0))
        
        return {"tick_size": tick_size, "min_qty": min_qty, "precision": precision}
