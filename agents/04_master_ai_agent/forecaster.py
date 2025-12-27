import pandas as pd
from datetime import datetime, timezone
from prophet import Prophet
from pybit.unified_trading import HTTP
import warnings
import logging

# Sopprimiamo i warning di Prophet
warnings.filterwarnings('ignore')
logging.getLogger('cmdstanpy').setLevel(logging.WARNING)

# Supported intervals for forecasting
SUPPORTED_INTERVALS = ["15m", "1h"]

class BybitForecaster:
    # Supported intervals - only these are validated and allowed
    SUPPORTED_INTERVALS = ['15m', '1h']
    
    def __init__(self, testnet: bool = False):
        # Se testnet=True usa i server di test, altrimenti mainnet
        self.session = HTTP(testnet=testnet)

    def _fetch_candles(self, coin: str, interval: str, limit: int) -> pd.DataFrame:
        # Validate supported intervals
        if interval not in self.SUPPORTED_INTERVALS:
            logging.warning(f"Unsupported interval '{interval}' for {coin}. Only {self.SUPPORTED_INTERVALS} are supported.")
            return pd.DataFrame()
        
        # Mappatura intervalli Bybit: 15m -> "15", 1h -> "60"
        bybit_interval = "15" if interval == "15m" else "60"
        
        symbol = coin.upper()
        if "USDT" not in symbol:
            symbol += "USDT"

        try:
            response = self.session.get_kline(
                category="linear",
                symbol=symbol,
                interval=bybit_interval,
                limit=limit
            )
            
            if response['retCode'] != 0:
                logging.warning(f"get_kline returned non-zero retCode for {symbol}: retCode={response['retCode']}, message={response.get('retMsg', 'N/A')}")
                return pd.DataFrame()

            data = response['result']['list']
            # Bybit restituisce i dati dal più recente al più vecchio. Li invertiamo.
            data.reverse()

            df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
            
            # Conversione timestamp e tipi
            df['ds'] = pd.to_datetime(df['ts'].astype(int), unit='ms')
            df['y'] = df['close'].astype(float)
            
            return df[['ds', 'y']]

        except Exception as e:
            logging.error(f"Error fetching candles for {symbol}: {e}")
            return pd.DataFrame()

    def forecast(self, coin: str, interval: str) -> tuple:
        limit = 300 if interval == "15m" else 500
        freq = "15min" if interval == "15m" else "H"
        
        df = self._fetch_candles(coin, interval, limit)
        
        if df.empty or len(df) < 50:
            return None, 0.0

        last_price = df["y"].iloc[-1]

        # Configurazione Prophet leggera
        model = Prophet(
            daily_seasonality=True, 
            weekly_seasonality=True,
            yearly_seasonality=False,
            changepoint_prior_scale=0.05
        )
        model.fit(df)

        future = model.make_future_dataframe(periods=1, freq=freq)
        forecast = model.predict(future)

        return forecast.tail(1)[["ds", "yhat", "yhat_lower", "yhat_upper"]], last_price

    def forecast_many(self, tickers: list, intervals=("15m", "1h")):
        results = []
        for coin in tickers:
            for interval in intervals:
                try:
                    forecast_data, last_price = self.forecast(coin, interval)
                    
                    if forecast_data is None:
                        continue

                    fc = forecast_data.iloc[0]
                    variazione_pct = ((fc["yhat"] - last_price) / last_price) * 100
                    
                    timeframe_str = "Prossimi 15 Minuti" if interval == "15m" else "Prossima Ora"
                    
                    results.append({
                        "Ticker": coin,
                        "Timeframe": timeframe_str,
                        "Ultimo Prezzo": round(last_price, 2),
                        "Previsione": round(fc["yhat"], 2),
                        "Limite Inferiore": round(fc["yhat_lower"], 2),
                        "Limite Superiore": round(fc["yhat_upper"], 2),
                        "Variazione %": round(variazione_pct, 2),
                        "Timestamp Previsione": fc["ds"]
                    })
                except Exception as e:
                    logging.error(f"Forecast error for {coin} ({interval}): {e}")
                    continue
                    
        return results

def get_crypto_forecasts(tickers=['BTC', 'ETH', 'SOL']):
    # Imposta testnet=False per dati veri
    forecaster = BybitForecaster(testnet=False) 
    results = forecaster.forecast_many(tickers)
    
    if not results:
        return "Nessuna previsione disponibile.", []
        
    df = pd.DataFrame(results)
    return df.to_string(index=False), df.to_dict(orient='records')
