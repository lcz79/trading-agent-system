# agents/04_bybit_executor/server.py

from flask import Flask, jsonify, request
# Importiamo la nostra funzione per il saldo dal file main.py
from .main import get_wallet_balance 
import os

app = Flask(__name__)

@app.route('/get-balance', methods=['GET'])
def balance_endpoint():
    """
    Endpoint per recuperare il saldo di una specifica moneta.
    Per ora, la moneta è fissa (USDT), ma in futuro potremmo
    passarla come parametro.
    """
    print(">>> Agente 4 (Executor): Ricevuta richiesta su /get-balance")
    
    # Eseguiamo la funzione che contatta Bybit
    balance_result = get_wallet_balance(target_coin="USDT")
    
    # Controlliamo se l'operazione è andata a buon fine
    if balance_result.get("status") == "success":
        print(f">>> Agente 4 (Executor): Saldo recuperato con successo. Invio risposta a n8n.")
        return jsonify(balance_result), 200
    else:
        # Se c'è stato un errore (es. chiavi API non impostate), lo comunichiamo
        print(f">>> Agente 4 (Executor): Errore durante il recupero del saldo. Dettagli: {balance_result.get('message')}")
        return jsonify(balance_result), 500

# Aggiungeremo qui altri endpoint, come /execute-trade
# @app.route('/execute-trade', methods=['POST'])
# def execute_trade_endpoint():
#     # ... logica per eseguire un ordine ...
#     pass

if __name__ == '__main__':
    # Facciamo girare il server sulla porta 5004 per non fare a pugni con gli altri agenti
    app.run(host='0.0.0.0', port=5004, debug=True)
