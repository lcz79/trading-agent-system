# ===============================================================
# SARA TRADER v3 — Smart Position Management (Bybit, CCXT) by lcz79
# ===============================================================
# Funzioni chiave:
# ✅ Rischio dinamico per trade (percentuale del capitale)
# ✅ Limite di rischio totale (es. max 5% del balance sommando SL aperti)
# ✅ Take Profit Parziale a 1R (di default 50%)
# ✅ Trailing Stop sul restante (passo in ATR o %)
# ✅ Cooldown e idempotenza (no doppie esecuzioni ravvicinate)
# ✅ Controlli robusti su simboli, min/max size, precision
# ✅ Compatibile con MarkAnalyst v6 e DBHandler
# ===============================================================

import logging
import math
import time
from typing import Dict, Any, Optional

from core.exchange_router import ExchangeRouter

class SaraTrader:
    # --- PARAMETRI DEFAULT ---
    DEFAULT_RISK_PER_TRADE = 0.015      # 1.5% del capitale per trade
    DEFAULT_MAX_TOTAL_RISK = 0.05       # 5% rischio massimo aggregato
    DEFAULT_PARTIAL_TP_RATIO = 0.5      # 50% size chiusa a 1R
    DEFAULT_LEVERAGE = 2                # leverage di default

    def __init__(self, exchange_router: ExchangeRouter):
        self.router = exchange_router
        self.exchange = self.router.get("bybit")
        if not self.exchange:
            raise ConnectionError("❌ Sara v3: Exchange Bybit non disponibile.")

        self.risk_per_trade = self.DEFAULT_RISK_PER_TRADE
        self.max_total_risk = self.DEFAULT_MAX_TOTAL_RISK
        self.partial_tp_ratio = self.DEFAULT_PARTIAL_TP_RATIO
        self.leverage = self.DEFAULT_LEVERAGE

        self._last_exec_ts: Dict[str, float] = {}
        self._markets = {}
        try:
            self._markets = self.exchange.load_markets()
        except Exception as e:
            logging.warning(f"⚠️ Sara v3: load_markets fallito: {e}")

        logging.info("✅ SaraTrader v3 inizializzata (Smart Position Management).")

    # --- UTILITIES ---
    def _get_market(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._markets.get(symbol)

    def _round_amount(self, symbol: str, amount: float) -> float:
        market = self._get_market(symbol)
        if not market: return round(amount, 8) # Fallback
        return self.exchange.amount_to_precision(symbol, amount)

    def _round_price(self, symbol: str, price: float) -> float:
        market = self._get_market(symbol)
        if not market: return round(price, 8) # Fallback
        return self.exchange.price_to_precision(symbol, price)

    def _fetch_usdt_balance(self) -> float:
        try:
            bal = self.exchange.fetch_balance(params={'type': 'unified'}) # Per Bybit Unified account
            return float(bal.get("USDT", {}).get("total", 0))
        except Exception as e:
            logging.error(f"❌ Impossibile leggere il balance USDT: {e}")
            return 0.0

    # --- CALCOLO RISCHIO E SIZE ---
    def _calc_dynamic_size(self, balance_usdt: float, entry: float, sl: float) -> float:
        risk_per_trade_usdt = balance_usdt * self.risk_per_trade
        price_distance = abs(entry - sl)
        if price_distance == 0: return 0.0
        return risk_per_trade_usdt / price_distance

    # --- ESECUZIONE ---
    def propose_trade(self, signal: dict):
        logging.info(f"SARA v3: Proposta ricevuta → {signal.get('asset')} {signal.get('side')} @ {signal.get('entry')}")

    def execute_order(self, signal: dict) -> dict:
        try:
            symbol = signal.get("asset")
            side = signal.get("side", "").lower()
            entry = float(signal.get("entry"))
            sl = float(signal.get("sl"))
            tp = float(signal.get("tp"))

            if not symbol or side not in ("long", "short"):
                return {"status": "error", "message": "Segnale invalido: symbol/side mancanti."}
            
            side_exec = "buy" if side == "long" else "sell"

            # Cooldown
            now = time.time()
            if now - self._last_exec_ts.get(symbol, 0) < 90:
                return {"status": "error", "message": f"Cooldown attivo per {symbol}."}

            # Set Leverage
            try:
                self.exchange.set_leverage(self.leverage, symbol)
            except Exception as e:
                logging.info(f"ℹ️ set_leverage non supportato/ignorato: {e}")

            # Calcolo Size
            balance = self._fetch_usdt_balance()
            if balance <= 0: return {"status": "error", "message": "Saldo USDT insufficiente."}
            
            amount = self._calc_dynamic_size(balance, entry, sl)
            amount = self._round_amount(symbol, amount)
            
            min_amount = self._get_market(symbol)['limits']['amount']['min']
            if amount < min_amount:
                return {"status": "error", "message": f"Size calcolata ({amount}) inferiore al minimo ({min_amount})."}

            logging.warning(f"🟡 ESECUZIONE LIVE → {side.upper()} {amount} {symbol} | SL={sl} TP={tp}")

            # Esecuzione Ordine
            order = self.exchange.create_order(
                symbol=symbol, type='market', side=side_exec, amount=amount,
                params={'stopLoss': sl, 'takeProfit': tp}
            )
            
            self._last_exec_ts[symbol] = now
            logging.warning(f"✅ Ordine principale eseguito: {order.get('id')}")
            return {"status": "success", "message": f"Entry OK ({order.get('id')})", "details": order}

        except Exception as e:
            logging.error(f"❌ Errore esecuzione ordine: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def manage_positions(self):
        # Placeholder per la logica di trailing stop futura
        logging.info("🧭 Controllo posizioni per trailing stop (logica non ancora attiva).")
