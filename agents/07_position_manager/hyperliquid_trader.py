import json
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Any

import eth_account
from eth_account.signers.local import LocalAccount

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants



class HyperLiquidTrader:
    def __init__(
        self,
        secret_key: str,
        account_address: str,
        testnet: bool = True,
        skip_ws: bool = True,
    ):
        self.secret_key = secret_key
        self.account_address = account_address

        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        self.base_url = base_url

        # crea account signer
        account: LocalAccount = eth_account.Account.from_key(secret_key)

        # Filter corrupted spot_meta entries (testnet has out-of-range token indices)
        from hyperliquid.api import API
        _api = API(base_url)
        _spot_meta = _api.post("/info", {"type": "spotMeta"})
        _n_tokens = len(_spot_meta.get("tokens", []))
        _spot_meta["universe"] = [
            u for u in _spot_meta.get("universe", [])
            if all(idx < _n_tokens for idx in u.get("tokens", []))
        ]
        self.info = Info(base_url, skip_ws=skip_ws, spot_meta=_spot_meta)
        self.exchange = Exchange(account, base_url, account_address=account_address, spot_meta=_spot_meta)

        # cache meta per tick-size e min-size
        self.meta = self.info.meta()

    def _to_hl_size(self, size_decimal: Decimal) -> str:
        # HL accetta max 8 decimali
        size_clamped = size_decimal.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        return format(size_clamped, "f")   # HL vuole stringa decimale perfetta
    
    def _round_price(self, price: float) -> float:
        """
        Arrotonda il prezzo in base alla sua grandezza (Magnitude).
        Hyperliquid rifiuta prezzi con troppi decimali per asset ad alto valore.
        """
        if price > 5000:
            # Per BTC o prezzi molto alti, arrotonda a 0 o 1 decimale max
            return round(price, 0) # Es: 92150.0
        elif price > 500:
            # Per ETH, BNB, ecc. max 1 o 2 decimali
            return round(price, 1) # Es: 3080.1
        elif price > 10:
            # Per SOL, AVAX, ecc.
            return round(price, 2) # Es: 145.23
        elif price > 1:
            # Per ARB, MATIC, ecc.
            return round(price, 4)
        else:
            # Per memecoin o prezzi < 1$
            return round(price, 5) # Es: 0.00123
    # ----------------------------------------------------------------------
    #                            VALIDAZIONE INPUT
    # ----------------------------------------------------------------------
    def _validate_order_input(self, order_json: Dict[str, Any]):
        required_fields = [
            "operation",
            "symbol",
            "direction",
            "target_portion_of_balance",
            "leverage",
            "reason",
        ]

        for f in required_fields:
            if f not in order_json:
                raise ValueError(f"Missing required field: {f}")

        if order_json["operation"] not in ("open", "close", "hold"):
            raise ValueError("operation must be 'open', 'close', or 'hold'")

        if order_json["direction"] not in ("long", "short"):
            raise ValueError("direction must be 'long' or 'short'")

        try:
            float(order_json["target_portion_of_balance"])
        except:
            raise ValueError("target_portion_of_balance must be a number")

    # ----------------------------------------------------------------------
    #                           MIN SIZE / TICK SIZE
    # ----------------------------------------------------------------------
    def _get_min_tick_for_symbol(self, symbol: str) -> Decimal:
        """
        Hyperliquid definisce per ogni asset un tick size.
        Lo leggiamo da meta().
        """
        for perp in self.meta["universe"]:
            if perp["name"] == symbol:
                return Decimal(str(perp["szDecimals"]))
        return Decimal("0.00000001")  # fallback a 1e-8

    def _round_size(self, size: Decimal, decimals: int) -> float:
        """
        Hyperliquid accetta massimo 8 decimali.
        Inoltre dobbiamo rispettare il tick size.
        """
        # prima clamp a 8 decimali
        size = size.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        # poi count of decimals per il tick
        fmt = f"{{0:.{decimals}f}}"
        return float(fmt.format(size))

    # ----------------------------------------------------------------------
    #                        GESTIONE LEVA
    # ----------------------------------------------------------------------
    def get_current_leverage(self, symbol: str) -> Dict[str, Any]:
        """Ottieni info sulla leva corrente per un simbolo"""
        try:
            user_state = self.info.user_state(self.account_address)
            
            # Cerca nelle posizioni aperte
            for position in user_state.get('assetPositions', []):
                pos = position.get('position', {})
                coin = pos.get('coin', '')
                if coin == symbol:
                    leverage_info = pos.get('leverage', {})
                    return {
                        'value': leverage_info.get('value', 0),
                        'type': leverage_info.get('type', 'unknown'),
                        'coin': coin
                    }
            
            # Se non c'è posizione aperta, controlla cross leverage default
            cross_leverage = user_state.get('crossLeverage', 20)
            return {
                'value': cross_leverage,
                'type': 'cross',
                'coin': symbol,
                'note': 'No open position, showing account default'
            }
            
        except Exception as e:
            print(f"Errore ottenendo leva corrente: {e}")
            return {'value': 20, 'type': 'unknown', 'error': str(e)}

    def set_leverage_for_symbol(self, symbol: str, leverage: int, is_cross: bool = True) -> Dict[str, Any]:
        """Imposta la leva per un simbolo specifico usando il metodo corretto"""
        try:
            print(f"🔧 Impostando leva {leverage}x per {symbol} ({'cross' if is_cross else 'isolated'} margin)")
            
            # Usa il metodo update_leverage con i parametri corretti
            result = self.exchange.update_leverage(
                leverage=leverage,      # int
                name=symbol,           # str - nome del simbolo come "BTC"
                is_cross=is_cross      # bool
            )
            
            if result.get('status') == 'ok':
                print(f"✅ Leva impostata con successo a {leverage}x per {symbol}")
            else:
                print(f"⚠️ Risposta dall'exchange: {result}")
                
            return result
            
        except Exception as e:
            print(f"❌ Errore impostando leva per {symbol}: {e}")
            return {"status": "error", "error": str(e)}

    # ----------------------------------------------------------------------
    #                        ESECUZIONE SEGNALE AI
    # ----------------------------------------------------------------------
    def cancel_reduce_only_orders(self, symbol: str):
        """Cancel all existing reduce-only (SL/TP) orders for a symbol."""
        try:
            open_orders = self.info.open_orders(self.account_address)
            cancelled = 0
            for order in open_orders:
                if order.get("coin") == symbol and order.get("reduceOnly", False):
                    oid = order.get("oid")
                    if oid:
                        self.exchange.cancel(symbol, oid)
                        cancelled += 1
            if cancelled > 0:
                print(f"🗑️ Cancelled {cancelled} existing SL/TP orders for {symbol}")
        except Exception as e:
            print(f"⚠️ Error cancelling orders for {symbol}: {e}")

    def _place_stop_loss(self, symbol: str, is_buy_sl: bool, size: float, trigger_price: float):
        """
        Piazza un ordine Trigger Market (Stop Loss) con reduce_only=True.
        """
        print(f"🛡️ Piazzando STOP LOSS per {symbol} a ${trigger_price} (Size: {size})")
        
        # Struttura specifica per ordine Trigger su Hyperliquid
        order_type = {
            "trigger": {
                "triggerPx": float(trigger_price),
                "isMarket": True, 
                "tpsl": "sl"
            }
        }

        try:
            result = self.exchange.order(
                name=symbol,
                is_buy=is_buy_sl,
                sz=size,
                limit_px=float(trigger_price), # Cap price per il trigger
                order_type=order_type,
                reduce_only=True # FONDAMENTALE: chiude solo, non apre nuove posizioni
            )

            if result["status"] == "ok":
                print(f"✅ Stop Loss piazzato: {result['response']['data']['statuses'][0]}")
            else:
                print(f"❌ Errore piazzamento Stop Loss: {result}")
            return result
            
        except Exception as e:
            print(f"❌ Eccezione durante piazzamento SL: {e}")
            return {"status": "error", "error": str(e)}

    def _place_take_profit(self, symbol: str, is_buy_tp: bool, size: float, trigger_price: float):
        """
        Piazza un ordine Trigger Market (Take Profit) con reduce_only=True.
        """
        print(f"🎯 Piazzando TAKE PROFIT per {symbol} a ${trigger_price} (Size: {size})")

        order_type = {
            "trigger": {
                "triggerPx": float(trigger_price),
                "isMarket": True,
                "tpsl": "tp"
            }
        }

        try:
            result = self.exchange.order(
                name=symbol,
                is_buy=is_buy_tp,
                sz=size,
                limit_px=float(trigger_price),
                order_type=order_type,
                reduce_only=True
            )

            if result["status"] == "ok":
                print(f"✅ Take Profit piazzato: {result['response']['data']['statuses'][0]}")
            else:
                print(f"❌ Errore piazzamento Take Profit: {result}")
            return result

        except Exception as e:
            print(f"❌ Eccezione durante piazzamento TP: {e}")
            return {"status": "error", "error": str(e)}

    # ----------------------------------------------------------------------
    #                       ESECUZIONE SEGNALE COMPLETA
    # ----------------------------------------------------------------------
    def execute_signal(self, order_json: Dict[str, Any]) -> Dict[str, Any]:
        from decimal import Decimal, ROUND_DOWN
        import time

        # 1. Validazione Input
        self._validate_order_input(order_json)

        op = order_json["operation"]
        symbol = order_json["symbol"]
        
        # Gestione operazioni non-trade
        if op == "hold":
            print(f"[HyperLiquidTrader] HOLD — nessuna azione per {symbol}.")
            return {"status": "hold", "message": "No action taken."}

        if op == "close":
            print(f"[HyperLiquidTrader] Market CLOSE per {symbol}")
            return self.exchange.market_close(symbol)

        # ------------------ LOGICA OPEN ------------------
        direction = order_json["direction"]
        portion = Decimal(str(order_json["target_portion_of_balance"]))
        leverage = int(order_json.get("leverage", 1))
        
        # Parametri Stop Loss (Percentuale o Prezzo Fisso)
        stop_loss_percent = order_json.get("stop_loss_percent", 0)/100
        sl_percent = float(stop_loss_percent)
        sl_price_explicit = order_json.get("stop_loss_price")

        # Parametri Take Profit (Percentuale o Prezzo Fisso)
        take_profit_percent = order_json.get("take_profit_percent", 0)/100
        tp_percent = float(take_profit_percent)
        tp_price_explicit = order_json.get("take_profit_price")

        # 2. Impostazione Leva
        leverage_result = self.set_leverage_for_symbol(symbol, leverage, is_cross=True)
        if leverage_result.get('status') != 'ok':
            print(f"⚠️ Warning leva: {leverage_result}")
        
        time.sleep(0.5) # Attesa propagazione

        # 3. Calcolo Size
        user = self.info.user_state(self.account_address)
        balance_usd = Decimal(str(user["marginSummary"]["accountValue"]))

        if balance_usd <= 0:
            raise RuntimeError("Balance account = 0")

        # Recupera prezzo attuale (Mark Price)
        mids = self.info.all_mids()
        if symbol not in mids:
            raise RuntimeError(f"Symbol {symbol} non presente su HL")
        
        mark_px = float(mids[symbol]) # Float per calcoli SL
        mark_px_dec = Decimal(str(mark_px)) # Decimal per calcoli Size

        # Calcolo nozionale e size grezza
        notional = balance_usd * portion * Decimal(str(leverage))
        raw_size = notional / mark_px_dec

        # Recupera meta-info del simbolo
        symbol_info = next((p for p in self.meta["universe"] if p["name"] == symbol), None)
        if not symbol_info:
            raise RuntimeError(f"Symbol {symbol} non trovato nei metadata")

        min_size = Decimal(str(symbol_info.get("minSz", "0.001")))
        sz_decimals = int(symbol_info.get("szDecimals", 8))

        # Arrotondamento Size
        quantizer = Decimal(10) ** -sz_decimals
        size_decimal = raw_size.quantize(quantizer, rounding=ROUND_DOWN)

        if size_decimal < min_size:
            print(f"⚠️ Size calcolata < min size. Uso min size: {min_size}")
            size_decimal = min_size

        size_float = float(size_decimal)
        is_buy = (direction == "long")

        # 4. Esecuzione Ordine Market (ENTRY)
        print(
            f"\n[HyperLiquidTrader] Market {'BUY' if is_buy else 'SELL'} {size_float} {symbol}\n"
            f"  💰 Prezzo Mark: ${mark_px}\n"
            f"  🎯 Leva: {leverage}x\n"
        )

        res = self.exchange.market_open(
            symbol,
            is_buy,
            size_float,
            None,
            0.01 # Slippage tolerance 1%
        )

        # 5. Gestione Stop Loss + Take Profit (Solo se l'ordine di apertura è OK)
        if res["status"] == "ok":
            # Cancel any pre-existing SL/TP for this symbol (prevents duplicates)
            import time as _time
            _time.sleep(0.3)
            self.cancel_reduce_only_orders(symbol)

            final_sl_price = None

            # A) Priorità al prezzo esplicito
            if sl_price_explicit:
                final_sl_price = float(sl_price_explicit)
            
            # B) Calcolo percentuale
            elif sl_percent > 0:
                print(f"🧮 Calcolo SL automatico: {sl_percent*100}% da {mark_px}")
                if is_buy: # Se sono Long, SL è sotto
                    raw_price = mark_px * (1 - sl_percent)
                else:      # Se sono Short, SL è sopra
                    raw_price = mark_px * (1 + sl_percent)
                
                final_sl_price = self._round_price(raw_price)

            # C) Invio ordine Trigger
            if final_sl_price:
                # Se ho aperto LONG, lo SL deve VENDERE (is_buy=False)
                # Se ho aperto SHORT, lo SL deve COMPRARE (is_buy=True)
                is_sl_buy = not is_buy 

                sl_res = self._place_stop_loss(
                    symbol=symbol,
                    is_buy_sl=is_sl_buy,
                    size=size_float,
                    trigger_price=final_sl_price
                )
                
                # Arricchisce la risposta con i dati dello SL
                res["stop_loss_order"] = sl_res
                res["stop_loss_price"] = final_sl_price

            # 6. Gestione Take Profit (safety net per crash/disconnessioni)
            final_tp_price = None

            # A) Priorità al prezzo esplicito
            if tp_price_explicit:
                final_tp_price = float(tp_price_explicit)

            # B) Calcolo percentuale
            elif tp_percent > 0:
                print(f"🧮 Calcolo TP automatico: {tp_percent*100:.2f}% da {mark_px}")
                if is_buy:  # Se sono Long, TP è sopra
                    raw_tp = mark_px * (1 + tp_percent)
                else:       # Se sono Short, TP è sotto
                    raw_tp = mark_px * (1 - tp_percent)

                final_tp_price = self._round_price(raw_tp)

            # C) Invio ordine Trigger TP
            if final_tp_price:
                is_tp_buy = not is_buy

                tp_res = self._place_take_profit(
                    symbol=symbol,
                    is_buy_tp=is_tp_buy,
                    size=size_float,
                    trigger_price=final_tp_price
                )

                res["take_profit_order"] = tp_res
                res["take_profit_price"] = final_tp_price

        return res

    # ----------------------------------------------------------------------
    #                           STATO ACCOUNT
    # ----------------------------------------------------------------------
    def get_account_status(self) -> Dict[str, Any]:
        data = self.info.user_state(self.account_address)
        balance = float(data["marginSummary"]["accountValue"])

        mids = self.info.all_mids()
        positions = []

        # Gestisci il formato corretto dei dati
        asset_positions = data.get("assetPositions", [])
        
        for p in asset_positions:
            # Estrai la posizione dal formato corretto
            if isinstance(p, dict) and "position" in p:
                pos = p["position"]
                coin = pos.get("coin", "")
            else:
                # Se il formato è diverso, prova ad adattarti
                pos = p
                coin = p.get("coin", p.get("symbol", ""))
                
            if not pos or not coin:
                continue
                
            size = float(pos.get("szi", 0))
            if size == 0:
                continue

            entry = float(pos.get("entryPx", 0))
            mark = float(mids.get(coin, entry))

            # Calcola P&L
            pnl = (mark - entry) * size
            
            # Estrai info sulla leva
            leverage_info = pos.get("leverage", {})
            leverage_value = leverage_info.get("value", "N/A")
            leverage_type = leverage_info.get("type", "unknown")

            positions.append({
                "symbol": coin,
                "side": "long" if size > 0 else "short",
                "size": abs(size),
                "entry_price": entry,
                "mark_price": mark,
                "pnl_usd": round(pnl, 4),
                "leverage": f"{leverage_value}x ({leverage_type})"
            })

        return {
            "balance_usd": balance,
            "open_positions": positions,
        }
    
    # ----------------------------------------------------------------------
    #                           UTILITY DEBUG
    # ----------------------------------------------------------------------
    def debug_symbol_limits(self, symbol: str = None):
        """Mostra i limiti di trading per un simbolo o tutti"""
        print("\n📊 LIMITI TRADING HYPERLIQUID")
        print("-" * 60)
        
        for perp in self.meta["universe"]:
            if symbol and perp["name"] != symbol:
                continue
                
            print(f"\nSymbol: {perp['name']}")
            print(f"  Min Size: {perp.get('minSz', 'N/A')}")
            print(f"  Size Decimals: {perp.get('szDecimals', 'N/A')}")
            print(f"  Price Decimals: {perp.get('pxDecimals', 'N/A')}")
            print(f"  Max Leverage: {perp.get('maxLeverage', 'N/A')}")
            print(f"  Only Isolated: {perp.get('onlyIsolated', False)}")