import logging
from core.exchange_router import ExchangeRouter

class SaraTrader:
    """
    Agente Sara: riceve proposte, invia notifiche ed ESEGUE ordini.
    """
    def __init__(self, exchange_router: ExchangeRouter):
        self.router = exchange_router
        logging.info("Agente SaraTrader inizializzato e pronto a ESEGUIRE.")

    def propose_trade(self, signal: dict):
        """Riceve una proposta di trade. Per ora, si limita a registrarla."""
        asset = signal.get("asset")
        side = signal.get("side")
        logging.info(f"SARA: Ricevuta proposta di trade per {asset} - {side}.")
        pass

    def execute_order(self, signal: dict) -> dict:
        """
        Esegue un ordine a mercato con SL/TP sull'exchange.
        ATTENZIONE: Questa funzione muove soldi veri!
        """
        if not signal:
            return {"status": "error", "message": "Dati del segnale non validi"}

        try:
            exchange = self.router.get("bybit")
            if not exchange:
                raise ConnectionError("Exchange non disponibile.")

            asset = signal.get('asset')
            side = signal.get('side').lower() # 'buy' o 'sell'
            amount = 0.001 # TODO: Calcolare la size dell'ordine! Per ora, usiamo una size minima.
            entry = float(signal.get('entry'))
            sl = float(signal.get('sl'))
            tp = float(signal.get('tp'))
            
            logging.warning(f"SARA: Tentativo di esecuzione ordine: {side} {amount} {asset} @ {entry}")

            # Crea l'ordine usando la sintassi di CCXT
            order = exchange.create_order(
                symbol=asset,
                type='market',
                side=side,
                amount=amount,
                params={
                    'stopLoss': sl,
                    'takeProfit': tp
                }
            )
            
            logging.warning(f"✅ ORDINE ESEGUITO CON SUCCESSO! Dettagli: {order}")
            return {"status": "success", "message": f"Ordine {order.get('id')} piazzato.", "details": order}

        except Exception as e:
            logging.error(f"❌ FALLIMENTO ESECUZIONE ORDINE: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
