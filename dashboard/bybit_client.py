from pybit.unified_trading import HTTP
from datetime import datetime
import pandas as pd
from config import BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET

class BybitClient:
    def __init__(self):
        self.session = HTTP(
            testnet=BYBIT_TESTNET,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET,
        )

    def safe_float(self, value):
        if value is None or value == "":
            return 0.0
        try:
            return float(value)
        except Exception:
            return 0.0
    
    def get_wallet_balance(self):
        try:
            response = self.session.get_wallet_balance(accountType="UNIFIED")
            if response.get('retCode') == 0 and response.get('result', {}).get('list'):
                result = response['result']['list'][0]
                return {
                    'equity': self.safe_float(result.get('totalEquity')),
                    'available': self.safe_float(result.get('totalAvailableBalance')),
                    'wallet_balance': self.safe_float(result.get('totalWalletBalance')),
                    'unrealized_pnl': self.safe_float(result.get('totalPerpUPL')),
                    'account_type': 'UNIFIED'
                }
        except Exception as e:
            print(f"Error wallet: {e}")
        return None
    
    def get_open_positions(self):
        try:
            response = self.session.get_positions(category="linear", settleCoin="USDT")
            if response['retCode'] == 0:
                positions = []
                for pos in response['result']['list']:
                    if float(pos.get('size', 0)) > 0:
                        positions.append({
                            'Symbol': pos.get('symbol'),
                            'Side': pos.get('side'),
                            'Size': float(pos.get('size')),
                            'Entry Price': float(pos.get('avgPrice')),
                            'Unrealized PnL': float(pos.get('unrealisedPnl')),
                            'PnL %': float(pos.get('unrealisedPnl')) / float(pos.get('positionValue')) * 100 if float(pos.get('positionValue')) > 0 else 0
                        })
                return positions
            return []
        except Exception as e:
            print(f"Error positions: {e}")
            return []

    def get_closed_pnl(self, limit=20):
        try:
            response = self.session.get_closed_pnl(category="linear", limit=limit)
            if response['retCode'] == 0:
                closed = []
                for trade in response['result']['list']:
                    closed.append({
                        'Symbol': trade.get('symbol'),
                        'Side': trade.get('side'),
                        'Closed PnL': float(trade.get('closedPnl')),
                        'Exit Time': datetime.fromtimestamp(int(trade.get('updatedTime'))/1000).strftime('%Y-%m-%d %H:%M:%S'),
                        'ts': int(trade.get('updatedTime'))
                    })
                closed.sort(key=lambda x: x['ts'], reverse=True)
                return closed
            return []
        except Exception:
            return []
