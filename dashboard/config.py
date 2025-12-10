import os

# Docker passa le variabili automaticamente, non serve load_dotenv
BYBIT_API_KEY = os.getenv('BYBIT_API_KEY', '')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET', '')
BYBIT_TESTNET = str(os.getenv('BYBIT_TESTNET', 'False')).lower() == 'true'
REFRESH_INTERVAL = int(os.getenv('REFRESH_INTERVAL', 5))

# Local data directory (dashboard-specific data)
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
EQUITY_HISTORY_FILE = os.path.join(DATA_DIR, 'equity_history.json')
CLOSED_POSITIONS_FILE = os.path.join(DATA_DIR, 'closed_positions.json')

# Shared data directory (cross-container data)
SHARED_DATA_DIR = '/data'
AI_DECISIONS_FILE = os.path.join(SHARED_DATA_DIR, 'ai_decisions.json')

# Starting values for performance calculations
STARTING_DATE = "2024-12-01"
STARTING_BALANCE = 1000.0
