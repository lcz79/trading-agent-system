from pybit.unified_trading import HTTP
from datetime import datetime, timezone, timedelta
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
                        entry_price = self.safe_float(pos.get('avgPrice', 0))
                        mark_price = self.safe_float(pos.get('markPrice', pos.get('avgPrice', 0)))
                        leverage = self.safe_float(pos.get('leverage', 1))
                        side = pos.get('side', '').lower()

                        # Calculate PnL % with leverage (matching Bybit ROI display)
                        if entry_price > 0:
                            if side in ['sell', 'short']:
                                pnl_pct = ((entry_price - mark_price) / entry_price) * leverage * 100
                            else:  # buy/long
                                pnl_pct = ((mark_price - entry_price) / entry_price) * leverage * 100
                        else:
                            pnl_pct = 0
                        
                        positions.append({
                            'Symbol': pos.get('symbol'),
                            'Side': pos.get('side'),
                            'Size': float(pos.get('size')),
                            'Entry Price': float(pos.get('avgPrice')),
                            'Unrealized PnL': float(pos.get('unrealisedPnl')),
                            'PnL %': round(pnl_pct, 2),
                            'Leverage': leverage
                        })
                return positions
            return []
        except Exception as e:
            print(f"Error positions: {e}")
            return []

    def get_execution_fees(self):
        """
        Recupera le commissioni trading dall'API executions di Bybit.
        Filtra solo executions dal 9 dicembre 2025 in poi.
        
        Returns:
            Dict con chiavi: today, week, month, total
            Ogni valore è un float che rappresenta la somma delle commissioni per quel periodo.
            In caso di errore, restituisce tutti i valori a 0.0
        """
        try:
            # Data minima filtro: 9 dicembre 2025 00:00:00 UTC (REQUISITO BUSINESS)
            min_date = datetime(2025, 12, 9, 0, 0, 0, tzinfo=timezone.utc)
            min_timestamp_ms = int(min_date.timestamp() * 1000)
            
            # Calcola i timestamp per i periodi
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=today_start.weekday())
            month_start = today_start.replace(day=1)
            
            today_ts = int(today_start.timestamp() * 1000)
            week_ts = int(week_start.timestamp() * 1000)
            month_ts = int(month_start.timestamp() * 1000)
            
            # Chiama API executions
            response = self.session.get_executions(category='linear', limit=200)
            
            if response.get('retCode') != 0:
                return {'today': 0.0, 'week': 0.0, 'month': 0.0, 'total': 0.0}
            
            fees = {'today': 0.0, 'week': 0.0, 'month': 0.0, 'total': 0.0}
            
            # Processa ogni execution
            executions = response.get('result', {}).get('list', [])
            for execution in executions:
                # Ottieni timestamp execution (in millisecondi)
                exec_time_str = execution.get('execTime', '0')
                exec_time_ms = int(exec_time_str)
                
                # Filtra solo executions dopo la data minima
                if exec_time_ms < min_timestamp_ms:
                    continue
                
                # Ottieni la fee (sempre positiva)
                exec_fee = abs(self.safe_float(execution.get('execFee', 0)))
                
                # Aggrega per periodo
                fees['total'] += exec_fee
                if exec_time_ms >= month_ts:
                    fees['month'] += exec_fee
                if exec_time_ms >= week_ts:
                    fees['week'] += exec_fee
                if exec_time_ms >= today_ts:
                    fees['today'] += exec_fee
            
            return fees
            
        except Exception as e:
            print(f"Errore nel recupero delle commissioni: {e}")
            return {'today': 0.0, 'week': 0.0, 'month': 0.0, 'total': 0.0}

    def get_closed_pnl(self, limit=20, start_date=None):
        """
        Recupera le posizioni chiuse con filtro data opzionale.
        
        Args:
            limit: numero massimo di trade da recuperare
            start_date: datetime con timezone - filtra solo trade dopo questa data
                       Default: 9 dicembre 2025 00:00:00 UTC (REQUISITO BUSINESS)
        
        Note:
            La data di default 9 dicembre 2025 è un requisito business specifico
            per filtrare tutti i dati storici e mostrare solo trade recenti.
        """
        try:
            # IMPORTANTE: Data di default è requisito business - non modificare
            # Se start_date non specificato, usa 9 dicembre 2025
            if start_date is None:
                start_date = datetime(2025, 12, 9, 0, 0, 0, tzinfo=timezone.utc)
            
            response = self.session.get_closed_pnl(category="linear", limit=limit)
            if response['retCode'] == 0:
                closed = []
                for trade in response['result']['list']:
                    trade_ts = int(trade.get('updatedTime'))
                    
                    # Filtra solo trade dopo start_date
                    if trade_ts >= start_date.timestamp() * 1000:
                        closed.append({
                            'Symbol': trade.get('symbol'),
                            'Side': trade.get('side'),
                            'Closed PnL': float(trade.get('closedPnl')),
                            'Exit Time': datetime.fromtimestamp(trade_ts/1000).strftime('%Y-%m-%d %H:%M:%S'),
                            'ts': trade_ts,
                            'exec_fee': abs(self.safe_float(trade.get('cumExecFee', 0))),  # Fee totale per il trade
                            'fee': abs(self.safe_float(trade.get('cumExecFee', 0)))  # Alias per compatibilità
                        })
                closed.sort(key=lambda x: x['ts'], reverse=True)
                return closed
            return []
        except Exception:
            return []
