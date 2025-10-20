import logging

class SaraTrader:
    """
    Agente Sara: riceve le proposte di trade e gestisce le notifiche.
    La sua logica è principalmente reattiva, non ha un ciclo di analisi proprio.
    """
    def __init__(self):
        logging.info("Agente SaraTrader inizializzato. Pronta a ricevere proposte e inviare notifiche.")
        # In futuro, qui potremmo inizializzare il bot di Telegram
        # self.telegram_bot = TelegramNotifier()

    def propose_trade(self, signal: dict):
        """
        Riceve un segnale (proposta di trade) da un altro agente (es. Mark).
        Per ora, si limita a registrarlo. In futuro, invierà una notifica.
        """
        if not signal:
            return

        asset = signal.get("asset")
        side = signal.get("side")
        
        logging.info(f"SARA: Ricevuta proposta di trade per {asset} - {side}.")

        # --- Logica Futura ---
        # 1. Formattare il messaggio per la notifica
        # message = f"🔥 Proposta di Trade! 🔥\n\nAsset: {asset}\nSide: {side}\nEntry: {signal.get('entry')}"
        
        # 2. Inviare la notifica
        # self.telegram_bot.send_message(message)
        
        # Per ora, non fa altro che confermare la ricezione.
        # La logica di salvataggio nel DB è già gestita da MarkAnalyst.
        pass
