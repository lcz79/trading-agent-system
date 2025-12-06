import os

# Docker passa le variabili automaticamente, non serve load_dotenv
BYBIT_API_KEY = os.getenv('BYBIT_API_KEY', '')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET', '')
BYBIT_TESTNET = str(os.getenv('BYBIT_TESTNET', 'False')).lower() == 'true'
REFRESH_INTERVAL = int(os.getenv('REFRESH_INTERVAL', 5))
