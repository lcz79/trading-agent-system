import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import ccxt

# --- CARICAMENTO CONFIGURAZIONE ---
API_KEY = os.getenv("EXCHANGE_API_KEY")
API_SECRET = os.getenv("EXCHANGE_API_SECRET")
# Per default, usiamo il testnet. Cambiare in 'mainnet' per andare live con soldi veri.
ENVIRONMENT = os.getenv("ENVIRONMENT", "testnet")

# --- VALIDAZIONE ---
if not API_KEY or not API_SECRET:
    raise ValueError("Le variabili d'ambiente EXCHANGE_API_KEY e EXCHANGE_API_SECRET sono obbligatorie.")

app = FastAPI()

# --- INIZIALIZZAZIONE CLIENT EXCHANGE ---
def get_exchange_client():
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
    })
    # Imposta l'ambiente di test o di produzione
    if ENVIRONMENT == 'testnet':
        exchange.set_sandbox_mode(True)
    return exchange

# --- MODELLI DATI ---
class TradingPlan(BaseModel):
    decision: str
    symbol: str # Assicuriamoci che il master agent lo invii!
    position_size_eur: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None

class OrderConfirmation(BaseModel):
    status: str
    order_id: Optional[str] = None
    symbol: str
    message: str

@app.post("/execute", response_model=OrderConfirmation)
def execute_order(plan: TradingPlan):
    if plan.decision not in ["BUY", "SELL"]:
        return OrderConfirmation(status="ignored", symbol=plan.symbol, message="Decisione ignorata.")

    try:
        exchange = get_exchange_client()
        
        # Converte il simbolo per l'exchange (es. 'BTCUSDT' -> 'BTC/USDT')
        market_symbol = f"{plan.symbol[:-4]}/{plan.symbol[-4:]}"

        # Ottiene il prezzo corrente per calcolare la quantità
        ticker = exchange.fetch_ticker(market_symbol)
        current_price = ticker['last']
        
        # Calcola la quantità di crypto da comprare/vendere
        amount_to_trade = plan.position_size_eur / current_price

        # Parametri per l'ordine
        order_type = 'market' # Eseguiamo a prezzo di mercato per semplicità iniziale
        side = 'buy' if plan.decision == "BUY" else 'sell'
        
        print(f"--- ESECUZIONE ORDINE ({ENVIRONMENT.upper()}) ---")
        print(f"Tentativo di {side} {amount_to_trade:.6f} di {market_symbol} a prezzo di mercato.")
        print(f"Piano: Size={plan.position_size_eur} EUR, SL={plan.stop_loss_price}, TP={plan.take_profit_price}")

        # --- CREAZIONE DELL'ORDINE REALE ---
        # Per ora, creiamo solo l'ordine di entrata. Gli ordini SL/TP richiedono una logica più complessa (ordini OCO)
        # che implementeremo come passo successivo per non complicare troppo ora.
        order = exchange.create_order(
            symbol=market_symbol,
            type=order_type,
            side=side,
            amount=amount_to_trade
        )

        print("--- ORDINE CREATO CON SUCCESSO ---")
        print(order)

        return OrderConfirmation(
            status=f"executed_on_{ENVIRONMENT}",
            order_id=order['id'],
            symbol=plan.symbol,
            message=f"Ordine {side} per {market_symbol} eseguito con successo su {ENVIRONMENT}."
        )

    except ccxt.BaseError as e:
        error_message = f"Errore CCXT: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)
    except Exception as e:
        error_message = f"Errore generico: {str(e)}"
        print(error_message)
        raise HTTPException(status_code=500, detail=error_message)

@app.get("/")
def health_check():
    return {"status": f"Order Executor Agent is running in {ENVIRONMENT} mode."}
