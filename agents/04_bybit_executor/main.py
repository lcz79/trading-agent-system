# agents/04_bybit_executor/main.py (VERSIONE FINALE E CORRETTA)

from pybit.unified_trading import HTTP
import os

# --- Configurazione Sicura delle Chiavi API ---
api_key = os.getenv("BYBIT_API_KEY")
api_secret = os.getenv("BYBIT_API_SECRET")

if not api_key or not api_secret:
    raise ValueError("Errore: le variabili d'ambiente BYBIT_API_KEY e BYBIT_API_SECRET non sono state impostate.")

session = HTTP(
    testnet=False,
    api_key=api_key,
    api_secret=api_secret,
)

def get_wallet_balance(target_coin: str = "USDT"):
    """
    Recupera il saldo di una specifica moneta dal portafoglio di Bybit,
    navigando la complessa struttura della risposta API.
    """
    try:
        response = session.get_wallet_balance(
            accountType="UNIFIED",
            coin=target_coin,
        )
        
        if response and response.get('retCode') == 0:
            # Percorso: result -> list[0] -> coin[0]
            
            result = response.get('result', {})
            outer_list = result.get('list', [])

            if outer_list:
                # Estraiamo il primo dizionario dalla lista esterna
                account_info = outer_list[0]
                
                # Estraiamo la lista interna dalla chiave "coin"
                inner_list_coin = account_info.get('coin', [])

                if inner_list_coin:
                    # Estraiamo il dizionario finale dalla lista interna
                    balance_data = inner_list_coin[0]
                    
                    wallet_balance = balance_data.get('walletBalance', 'N/A')
                    coin_name = balance_data.get('coin', 'N/A')

                    print(f"Connessione a Bybit riuscita.")
                    print(f"Saldo per {coin_name}: {wallet_balance}")
                    
                    return {"status": "success", "coin": coin_name, "balance": wallet_balance}

            # Se in qualsiasi punto il percorso si interrompe, diamo un errore chiaro
            print("Errore: Struttura della risposta di Bybit inattesa o vuota.")
            return {"status": "error", "message": "Struttura risposta inattesa."}
        else:
            print(f"Errore da Bybit: {response.get('retMsg')}")
            return {"status": "error", "message": response.get('retMsg')}

    except Exception as e:
        print(f"Errore generico durante la connessione a Bybit: {e}")
        return {"status": "error", "message": str(e)}

# --- Esempio di come eseguire la funzione ---
if __name__ == "__main__":
    get_wallet_balance()
