import time, logging
from typing import Callable
class Scheduler:
    def run_every(self, seconds: int, fn: Callable, *args, **kwargs):
        logging.info(f"Scheduler: Avvio di '{fn.__name__}' ogni {seconds} secondi.")
        while True:
            try: fn(*args, **kwargs)
            except KeyboardInterrupt:
                logging.info(f"Scheduler: Stop per '{fn.__name__}'."); break
            except Exception as e:
                logging.error(f"Scheduler error in '{fn.__name__}': {e}", exc_info=True)
            time.sleep(seconds)