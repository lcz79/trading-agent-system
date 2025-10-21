# ===============================================================
# SARA TRADER PRO — Smart Position & Risk Management (Bybit, CCXT)
# Autore: lcz79
# ===============================================================
import logging
import math
import time
from typing import Dict, Any, Optional, List

import pandas as pd
import pandas_ta as ta

from core.exchange_router import ExchangeRouter


class SaraTrader:
    # --------------------------- PARAMETRI DEFAULT ---------------------------
    DEFAULT_RISK_PER_TRADE = 0.015      # 1.5% del capitale per trade
    DEFAULT_MAX_TOTAL_RISK = 0.05       # 5% di rischio totale (somma rischi a SL)
    DEFAULT_PARTIAL_TP_RATIO = 0.5      # 50% size chiusa a 1R
    DEFAULT_TRAIL_MULT_ATR = 1.0        # trailing = 1.0 * ATR
    DEFAULT_TRAIL_MIN_PCT = 0.003       # trailing minimo 0.30% del prezzo
    DEFAULT_COOLDOWN_SEC = 90           # evita doppie esecuzioni entro 90s
    DEFAULT_LEVERAGE = 2                # leverage best-effort (se supportato)
    DEFAULT_SLIPPAGE_BPS = 5            # 5 bps slippage sicurezza

    def __init__(self, exchange_router: ExchangeRouter):
        self.router = exchange_router
        self.exchange = self.router.get("bybit")
        if not self.exchange:
            raise ConnectionError("❌ SaraPro: Exchange Bybit non disponibile.")

        # Parametri runtime
        self.risk_per_trade = self.DEFAULT_RISK_PER_TRADE
        self.max_total_risk = self.DEFAULT_MAX_TOTAL_RISK
        self.partial_tp_ratio = self.DEFAULT_PARTIAL_TP_RATIO
        self.trail_mult_atr = self.DEFAULT_TRAIL_MULT_ATR
        self.trail_min_pct = self.DEFAULT_TRAIL_MIN_PCT
        self.cooldown_sec = self.DEFAULT_COOLDOWN_SEC
        self.leverage = self.DEFAULT_LEVERAGE
        self.slippage_bps = self.DEFAULT_SLIPPAGE_BPS

        # Stato interno
        self._last_exec_ts: Dict[str, float] = {}     # cooldown per symbol
        self._executed_signals: Dict[str, float] = {} # idempotenza
        self._markets = {}
        try:
            self._markets = self.exchange.load_markets()
        except Exception as e:
            logging.warning(f"⚠️ load_markets fallito (continua): {e}")

        logging.info("✅ SaraTrader PRO inizializzata.")

    # ======================================================================
    #                             UTILITIES
    # ======================================================================
    def _symbol_market(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            return self._markets.get(symbol) if self._markets else None
        except Exception:
            return None

    def _price_prec(self, symbol: str) -> int:
        m = self._symbol_market(symbol)
        if not m: return 4
        p = m.get("precision", {}).get("price")
        return int(p) if isinstance(p, int) else 4

    def _amount_prec(self, symbol: str) -> int:
        m = self._symbol_market(symbol)
        if not m: return 4
        a = m.get("precision", {}).get("amount")
        return int(a) if isinstance(a, int) else 4

    def _min_amount(self, symbol: str) -> float:
        m = self._symbol_market(symbol)
        if not m: return 0.001
        limits = m.get("limits", {})
        amount_min = limits.get("amount", {}).get("min")
        return float(amount_min) if amount_min else 0.001

    def _round_amount(self, symbol: str, amount: float) -> float:
        prec = self._amount_prec(symbol)
        return max(round(amount, prec), self._min_amount(symbol))

    def _round_price(self, symbol: str, price: float) -> float:
        prec = self._price_prec(symbol)
        return round(price, prec)

    def _slip_price(self, price: float, side: str) -> float:
        slip = self.slippage_bps / 10000.0
        if side.lower() == "buy":
            return price * (1 + slip)
        else:
            return price * (1 - slip)

    def _fetch_usdt_balance(self) -> float:
        try:
            bal = self.exchange.fetch_balance()
            return float(bal["total"].get("USDT", 0))
        except Exception as e:
            logging.error(f"❌ Balance USDT non leggibile: {e}")
            return 0.0

    def _current_price(self, symbol: str) -> Optional[float]:
        try:
            t = self.exchange.fetch_ticker(symbol)
            return float(t["last"]) if "last" in t and t["last"] is not None else None
        except Exception as e:
            logging.error(f"❌ fetch_ticker fallito per {symbol}: {e}")
            return None

    def _fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 100) -> pd.DataFrame:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            return df.dropna()
        except Exception as e:
            logging.error(f"❌ fetch_ohlcv fallito per {symbol}: {e}")
            return pd.DataFrame()

    def _atr(self, df: pd.DataFrame, length: int = 14) -> Optional[float]:
        if df.empty: return None
        try:
            return float(ta.atr(df["high"], df["low"], df["close"], length=length).iloc[-1])
        except Exception:
            return None

    # ======================================================================
    #                   CALCOLO RISCHIO E SIZE / BUDGET
    # ======================================================================
    def _calc_trade_risk_usdt(self, amount: float, entry: float, sl: float) -> float:
        distance = abs(entry - sl)
        return distance * amount

    def _calc_dynamic_size(self, balance_usdt: float, entry: float, sl: float) -> float:
        risk_amount = balance_usdt * self.risk_per_trade
        distance = abs(entry - sl)
        if distance <= 0:
            raise ValueError("Stop Loss non valido (distance <= 0).")
        raw_amount = risk_amount / distance
        return max(raw_amount, 0.0)

    def _total_open_risk_usdt(self) -> float:
        total = 0.0
        try:
            positions = self.exchange.fetch_positions()
            open_orders = self.exchange.fetch_open_orders()
        except Exception as e:
            logging.error(f"⚠️ Impossibile leggere posizioni/ordini: {e}")
            return 0.0

        sl_by_symbol = {}
        for o in open_orders:
            if o.get("reduceOnly") and ("stop" in (o.get("type") or "").lower() or "triggerPrice" in (o.get("info") or {})):
                sym = o.get("symbol")
                trig = o.get("triggerPrice") or (o.get("info") or {}).get("triggerPrice")
                if sym and trig:
                    if sym not in sl_by_symbol:
                        sl_by_symbol[sym] = float(trig)
                    else:
                        last = self._current_price(sym) or float(trig)
                        if abs(last - float(trig)) < abs(last - sl_by_symbol[sym]):
                            sl_by_symbol[sym] = float(trig)

        for p in positions:
            try:
                sym = p.get("symbol")
                if not sym: continue
                size = float(p.get("contracts") or p.get("contracts", 0) or p.get("info", {}).get("size", 0))
                if size <= 0: continue
                entry = float(p.get("entryPrice") or 0)
                if entry <= 0: continue
                sl = sl_by_symbol.get(sym)
                if sl is None: 
                    continue
                total += abs(entry - sl) * size
            except Exception:
                continue
        return total

    def _can_open_new_risk(self, new_risk_usdt: float) -> bool:
        balance = self._fetch_usdt_balance()
        if balance <= 0:
            logging.error("❌ Balance USDT non disponibile o zero.")
            return False
        max_risk = balance * self.max_total_risk
        current_risk = self._total_open_risk_usdt()
        if current_risk + new_risk_usdt > max_risk:
            logging.warning(f"⛔ Rischio aggregato ({current_risk + new_risk_usdt:.2f} USDT) > budget max ({max_risk:.2f}).")
            return False
        return True

    # ======================================================================
    #                         ESECUZIONE ORDINE LIVE
    # ======================================================================
    def propose_trade(self, signal: dict):
        logging.info(f"SARA PRO: Proposta → {signal.get('asset')} {signal.get('side')} @ {signal.get('entry')}")

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

            now = time.time()
            if now - self._last_exec_ts.get(symbol, 0) < self.cooldown_sec:
                return {"status": "error", "message": f"Cooldown attivo per {symbol}."}

            sig_key = f"{symbol}|{side_exec}|{entry}|{sl}|{tp}"
            if sig_key in self._executed_signals and (now - self._executed_signals[sig_key]) < self.cooldown_sec:
                return {"status": "error", "message": "Segnale già eseguito di recente (idempotenza)."}

            try:
                m = self._symbol_market(symbol)
                if m and m.get("linear"):
                    self.exchange.set_leverage(self.leverage, symbol)
            except Exception as e:
                logging.info(f"ℹ️ set_leverage ignorato/non supportato: {e}")

            balance = self._fetch_usdt_balance()
            if balance <= 0:
                return {"status": "error", "message": "Saldo USDT insufficiente."}

            amount = self._calc_dynamic_size(balance, entry, sl)
            amount = self._round_amount(symbol, amount)
            if amount <= 0:
                return {"status": "error", "message": "Size calcolata nulla o < min."}

            new_risk = self._calc_trade_risk_usdt(amount, entry, sl)
            if not self._can_open_new_risk(new_risk):
                return {"status": "error", "message": "Nuovo trade oltre budget di rischio aggregato."}

            entry_exec_price = self._slip_price(entry, side_exec)
            logging.warning(
                f"🟡 LIVE → {side.upper()} {amount} {symbol} | "
                f"Entry≈{entry_exec_price:.6f} SL={sl:.6f} TP={tp:.6f} | "
                f"Risk new={new_risk:.2f} USDT"
            )

            entry_order = self.exchange.create_order(symbol=symbol, type="market", side=side_exec, amount=amount)

            side_close = "sell" if side_exec == "buy" else "buy"
            sl_price = self._round_price(symbol, sl)
            try:
                self.exchange.create_order(
                    symbol=symbol, type="stop", side=side_close, amount=amount,
                    params={"triggerPrice": sl_price, "reduceOnly": True}
                )
            except Exception as e:
                logging.error(f"⚠️ SL reduceOnly fallito: {e}")

            R = abs(entry - sl)
            tp1 = entry + R if side_exec == "buy" else entry - R
            tp1 = self._round_price(symbol, tp1)
            amount_tp1 = self._round_amount(symbol, amount * self.partial_tp_ratio)
            try:
                self.exchange.create_order(
                    symbol=symbol, type="limit", side=side_close, price=tp1, amount=amount_tp1,
                    params={"reduceOnly": True}
                )
            except Exception as e:
                logging.error(f"⚠️ TP1 reduceOnly fallito: {e}")

            tp_fin = self._round_price(symbol, tp)
            amount_rest = self._round_amount(symbol, max(amount - amount_tp1, 0))
            if amount_rest > 0:
                try:
                    self.exchange.create_order(
                        symbol=symbol, type="limit", side=side_close, price=tp_fin, amount=amount_rest,
                        params={"reduceOnly": True}
                    )
                except Exception as e:
                    logging.error(f"⚠️ TP finale reduceOnly fallito: {e}")

            self._last_exec_ts[symbol] = time.time()
            self._executed_signals[sig_key] = time.time()

            logging.warning(f"✅ Entry eseguita: {entry_order.get('id')}")
            return {
                "status": "success",
                "message": f"Entry OK ({entry_order.get('id')}); SL/TP piazzati.",
                "details": {"entryOrder": entry_order}
            }

        except Exception as e:
            logging.error(f"❌ Errore esecuzione ordine: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # ======================================================================
    #                     GESTIONE POSIZIONI: TRAILING
    # ======================================================================
    def _list_open_symbols(self) -> List[str]:
        try:
            pos = self.exchange.fetch_positions()
            return list(set([p['symbol'] for p in pos if p.get('symbol') and float(p.get('contracts', 0)) > 0]))
        except Exception as e:
            logging.error(f"⚠️ fetch_positions fallito: {e}")
            return []

    def _detect_side_from_position(self, p: dict) -> Optional[str]:
        try:
            side = p.get("side")
            if side in ("long", "short"): return side
            amt = float(p.get("contracts", 0))
            return "long" if amt > 0 else ("short" if amt < 0 else None)
        except Exception:
            return None

    def _best_trailing_step(self, symbol: str) -> Optional[float]:
        df = self._fetch_ohlcv(symbol, "15m", 100)
        atr = self._atr(df, 14)
        last = self._current_price(symbol)
        if not last: return None
        step_atr = (atr * self.trail_mult_atr) if atr else 0.0
        step_pct = last * self.trail_min_pct
        return max(step_atr, step_pct, 0.0)

    def _find_current_sl_order(self, symbol: str, side_close: str) -> Optional[dict]:
        try:
            open_orders = self.exchange.fetch_open_orders(symbol)
            candidates = [o for o in open_orders if o.get("reduceOnly") and (o.get("side") or "").lower() == side_close and ("stop" in (o.get("type") or "").lower() or o.get("triggerPrice"))]
            if not candidates: return None
            last = self._current_price(symbol) or 0
            candidates.sort(key=lambda x: abs((x.get("triggerPrice") or 0) - last))
            return candidates[0]
        except Exception as e:
            logging.error(f"⚠️ fetch_open_orders fallito per {symbol}: {e}")
            return None

    def manage_positions(self):
        symbols = self._list_open_symbols()
        if not symbols: return
        logging.info(f"🧭 Gestione posizioni attive: {symbols}")
        for symbol in symbols:
            try:
                positions = self.exchange.fetch_positions([symbol])
                if not positions: continue
                p = positions[0]
                side_pos = self._detect_side_from_position(p)
                if not side_pos: continue
                
                last = self._current_price(symbol)
                if not last: continue

                step = self._best_trailing_step(symbol)
                if not step or step <= 0: continue

                side_close = "sell" if side_pos == "long" else "buy"
                sl_order = self._find_current_sl_order(symbol, side_close)
                if not sl_order:
                    logging.info(f"ℹ️ Nessun SL attivo trovato per {symbol}.")
                    continue

                current_trigger = sl_order.get("triggerPrice")
                if current_trigger is None: continue
                current_trigger = float(current_trigger)

                new_sl = max(current_trigger, last - step) if side_pos == "long" else min(current_trigger, last + step)
                
                should_update = (side_pos == "long" and new_sl > current_trigger) or \
                                (side_pos == "short" and new_sl < current_trigger)

                if should_update:
                    new_sl_rounded = self._round_price(symbol, new_sl)
                    try:
                        self.exchange.cancel_order(sl_order.get("id"), symbol)
                        amt = float(sl_order.get("amount", p.get("contracts", 0)))
                        self.exchange.create_order(
                            symbol=symbol, type="stop", side=side_close, amount=amt,
                            params={"triggerPrice": new_sl_rounded, "reduceOnly": True}
                        )
                        logging.info(f"🔧 Trailing {side_pos.upper()} {symbol}: SL {current_trigger} → {new_sl_rounded}")
                    except Exception as e:
                        logging.error(f"⚠️ Aggiornamento SL fallito per {symbol}: {e}")
            except Exception as e:
                logging.error(f"❌ Errore manage_positions per {symbol}: {e}", exc_info=True)
