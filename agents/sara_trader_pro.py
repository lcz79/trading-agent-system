# ===============================================================
# SARA TRADER PRO v1.1 — Unified Account & Market Specificity
# ===============================================================
# Fix: Specifica 'unified' per il balance e 'linear' per gli ordini
# per garantire l'uso del conto corretto su Bybit.
# ===============================================================
import logging
import math
import time
from typing import Dict, Any, Optional, List

import pandas as pd
import pandas_ta as ta

from core.exchange_router import ExchangeRouter

class SaraTrader:
    # --- (Parametri Default Invariati) ---
    DEFAULT_RISK_PER_TRADE = 0.015
    DEFAULT_MAX_TOTAL_RISK = 0.05
    DEFAULT_PARTIAL_TP_RATIO = 0.5
    DEFAULT_TRAIL_MULT_ATR = 1.0
    DEFAULT_TRAIL_MIN_PCT = 0.003
    DEFAULT_COOLDOWN_SEC = 90
    DEFAULT_LEVERAGE = 2
    DEFAULT_SLIPPAGE_BPS = 5

    def __init__(self, exchange_router: ExchangeRouter):
        self.router = exchange_router
        self.exchange = self.router.get("bybit")
        if not self.exchange: raise ConnectionError("❌ SaraPro: Exchange Bybit non disponibile.")
        self.risk_per_trade = self.DEFAULT_RISK_PER_TRADE
        self.max_total_risk = self.DEFAULT_MAX_TOTAL_RISK
        self.partial_tp_ratio = self.DEFAULT_PARTIAL_TP_RATIO
        self.trail_mult_atr = self.DEFAULT_TRAIL_MULT_ATR
        self.trail_min_pct = self.DEFAULT_TRAIL_MIN_PCT
        self.cooldown_sec = self.DEFAULT_COOLDOWN_SEC
        self.leverage = self.DEFAULT_LEVERAGE
        self.slippage_bps = self.DEFAULT_SLIPPAGE_BPS
        self._last_exec_ts: Dict[str, float] = {}
        self._executed_signals: Dict[str, float] = {}
        self._markets = {}
        try:
            self._markets = self.exchange.load_markets()
        except Exception as e:
            logging.warning(f"⚠️ load_markets fallito (continua): {e}")
        logging.info("✅ SaraTrader PRO v1.1 inizializzata.")

    # --- (UTILITIES Invariate, tranne _fetch_usdt_balance) ---
    def _symbol_market(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._markets.get(symbol)
    def _price_prec(self, symbol: str) -> int:
        m = self._symbol_market(symbol); p = m.get("precision", {}).get("price") if m else None; return int(p) if isinstance(p, int) else 4
    def _amount_prec(self, symbol: str) -> int:
        m = self._symbol_market(symbol); a = m.get("precision", {}).get("amount") if m else None; return int(a) if isinstance(a, int) else 4
    def _min_amount(self, symbol: str) -> float:
        m = self._symbol_market(symbol); limits = m.get("limits", {}) if m else {}; amount_min = limits.get("amount", {}).get("min"); return float(amount_min) if amount_min else 0.001
    def _round_amount(self, symbol: str, amount: float) -> float:
        prec = self._amount_prec(symbol); return max(round(amount, prec), self._min_amount(symbol))
    def _round_price(self, symbol: str, price: float) -> float:
        prec = self._price_prec(symbol); return round(price, prec)
    def _slip_price(self, price: float, side: str) -> float:
        slip = self.slippage_bps / 10000.0; return price * (1 + slip) if side.lower() == "buy" else price * (1 - slip)
    
    # --- FIX: Specifica l'account 'UNIFIED' per il balance ---
    def _fetch_usdt_balance(self) -> float:
        try:
            # Chiedi esplicitamente il balance dell'account UNIFIED
            bal = self.exchange.fetch_balance(params={'accountType': 'UNIFIED'})
            return float(bal['total'].get("USDT", 0))
        except Exception as e:
            logging.error(f"❌ Balance USDT non leggibile: {e}")
            return 0.0

    def _current_price(self, symbol: str) -> Optional[float]:
        try: t = self.exchange.fetch_ticker(symbol); return float(t["last"]) if "last" in t and t["last"] is not None else None
        except Exception as e: logging.error(f"❌ fetch_ticker fallito per {symbol}: {e}"); return None
    def _fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 100) -> pd.DataFrame:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"]); df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True); return df.dropna()
        except Exception as e: logging.error(f"❌ fetch_ohlcv fallito per {symbol}: {e}"); return pd.DataFrame()
    def _atr(self, df: pd.DataFrame, length: int = 14) -> Optional[float]:
        if df.empty: return None
        try: return float(ta.atr(df["high"], df["low"], df["close"], length=length).iloc[-1])
        except Exception: return None

    # --- (CALCOLO RISCHIO Invariato) ---
    def _calc_trade_risk_usdt(self, amount: float, entry: float, sl: float) -> float: return abs(entry - sl) * amount
    def _calc_dynamic_size(self, balance_usdt: float, entry: float, sl: float) -> float:
        risk_amount = balance_usdt * self.risk_per_trade; distance = abs(entry - sl)
        if distance <= 0: raise ValueError("Stop Loss non valido.")
        return max(risk_amount / distance, 0.0)
    def _total_open_risk_usdt(self) -> float: return 0.0 # Semplificato per ora
    def _can_open_new_risk(self, new_risk_usdt: float) -> bool: return True # Semplificato per ora

    # --- (ESECUZIONE ORDINE con FIX) ---
    def execute_order(self, signal: dict) -> dict:
        try:
            symbol = signal.get("asset")
            side = signal.get("side", "").lower()
            entry = float(signal.get("entry"))
            sl = float(signal.get("sl"))
            tp = float(signal.get("tp"))

            if not symbol or side not in ("buy", "sell", "long", "short"):
                return {"status": "error", "message": "Segnale invalido."}
            
            side_exec = "buy" if side in ("buy", "long") else "sell"

            now = time.time()
            if now - self._last_exec_ts.get(symbol, 0) < self.cooldown_sec:
                return {"status": "error", "message": f"Cooldown attivo per {symbol}."}

            try: self.exchange.set_leverage(self.leverage, symbol)
            except Exception as e: logging.info(f"ℹ️ set_leverage ignorato: {e}")

            balance = self._fetch_usdt_balance()
            if balance <= 0: return {"status": "error", "message": "Saldo USDT insufficiente in Unified Account."}

            amount = self._calc_dynamic_size(balance, entry, sl)
            amount = self._round_amount(symbol, amount)
            if amount <= 0: return {"status": "error", "message": "Size calcolata nulla o < min."}

            logging.warning(f"🟡 LIVE → {side.upper()} {amount} {symbol} | SL={sl:.6f} TP={tp:.6f}")

            # --- FIX: Specifica la categoria 'linear' per gli ordini di derivati ---
            order_params = {
                'category': 'linear',
                'stopLoss': self._round_price(symbol, sl),
                'takeProfit': self._round_price(symbol, tp)
            }

            entry_order = self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=side_exec,
                amount=amount,
                params=order_params
            )

            self._last_exec_ts[symbol] = time.time()
            logging.warning(f"✅ Entry eseguita: {entry_order.get('id')}")
            return {"status": "success", "message": f"Entry OK ({entry_order.get('id')})", "details": entry_order}

        except Exception as e:
            logging.error(f"❌ Errore esecuzione ordine: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    # --- (PROPOSE TRADE e MANAGE POSITIONS Invariati) ---
    def propose_trade(self, signal: dict): logging.info(f"SARA PRO: Proposta → {signal.get('asset')} {signal.get('side')}")
    def manage_positions(self): logging.info("🧭 Gestione posizioni (Trailing) in attesa...")
