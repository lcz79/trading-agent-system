import time
import logging

class Scheduler:
    """
    Una classe semplice per eseguire una funzione ripetutamente a un dato intervallo.
    """
    def run_every(self, interval_seconds, func, *args, **kwargs):
        """
        Esegue una funzione in un ciclo infinito, attendendo l'intervallo specificato
        tra un'esecuzione e l'altra.
        """
        logging.info(f"Scheduler avviato per la funzione '{func.__name__}' con un intervallo di {interval_seconds} secondi.")
        
        while True:
            try:
                logging.info(f"Esecuzione del task schedulato: '{func.__name__}'...")
                func(*args, **kwargs)
                logging.info(f"Task '{func.__name__}' completato.")
            except Exception as e:
                logging.error(f"Errore nel task schedulato '{func.__name__}': {e}", exc_info=True)
            
            logging.info(f"In attesa di {interval_seconds} secondi prima della prossima esecuzione di '{func.__name__}'.")
            time.sleep(interval_seconds)