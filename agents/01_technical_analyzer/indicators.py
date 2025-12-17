import pandas as pd
import ta
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from pybit.unified_trading import HTTP

INTERVAL_TO_BYBIT = {
    "1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"
}

class CryptoTechnicalAnalysisBybit:
    def __init__(self):
        self.session = HTTP()

    def fetch_ohlcv(self, coin: str, interval: str, limit: int = 200) -> pd.DataFrame:
        if interval not in INTERVAL_TO_BYBIT: interval = "15m"
        bybit_interval = INTERVAL_TO_BYBIT[interval]
        
        symbol = coin.replace("-", "").upper()
        if "USDT" not in symbol: symbol += "USDT"

        try:
            resp = self.session.get_kline(category="linear", symbol=symbol, interval=bybit_interval, limit=limit)
            
            # Safely check response code
            ret_code = resp.get('retCode')
            if ret_code is None:
                print(f"Error fetching {symbol}: Missing retCode in response")
                return pd.DataFrame()
            
            if ret_code != 0:
                ret_msg = resp.get('retMsg', 'Unknown error')
                print(f"Error fetching {symbol}: API returned code {ret_code}, message: {ret_msg}")
                return pd.DataFrame()
            
            # Safely extract result data
            result = resp.get('result')
            if not result:
                print(f"Error fetching {symbol}: Missing result in response")
                return pd.DataFrame()
            
            raw_data = result.get('list')
            if not raw_data or not isinstance(raw_data, list) or len(raw_data) == 0:
                print(f"Error fetching {symbol}: No data in result.list")
                return pd.DataFrame()
            
            df = pd.DataFrame(raw_data, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
            
            for col in ['open', 'high', 'low', 'close', 'vol']:
                df[col] = df[col].astype(float)
            
            df['timestamp'] = pd.to_datetime(pd.to_numeric(df['ts']), unit='ms', utc=True)
            df.rename(columns={'vol': 'volume'}, inplace=True)
            df = df.iloc[::-1].reset_index(drop=True)
            return df
        except KeyError as e:
            print(f"Error fetching {symbol}: Missing key in response - {e}")
            return pd.DataFrame()
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            return pd.DataFrame()

    def calculate_ema(self, data: pd.Series, period: int) -> pd.Series:
        return ta.trend.EMAIndicator(data, window=period).ema_indicator()

    def calculate_macd(self, data: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        macd = ta.trend.MACD(data)
        return macd.macd(), macd.macd_signal(), macd.macd_diff()

    def calculate_rsi(self, data: pd.Series, period: int) -> pd.Series:
        return ta.momentum.RSIIndicator(data, window=period).rsi()

    def calculate_atr(self, high, low, close, period):
        return ta.volatility.AverageTrueRange(high, low, close, window=period).average_true_range()

    def calculate_pivot_points(self, high, low, close):
        pp = (high + low + close) / 3.0
        return {
            "pp": pp, 
            "s1": (2 * pp) - high, 
            "s2": pp - (high - low), 
            "r1": (2 * pp) - low, 
            "r2": pp + (high - low)
        }

    def get_complete_analysis(self, ticker: str) -> Dict:
        df = self.fetch_ohlcv(ticker, "15m", limit=200)
        if df.empty: return {}

        df["ema_20"] = self.calculate_ema(df["close"], 20)
        df["ema_50"] = self.calculate_ema(df["close"], 50)
        macd_line, macd_sig, macd_diff = self.calculate_macd(df["close"])
        df["macd_line"] = macd_line
        df["macd_signal"] = macd_sig
        df["rsi_7"] = self.calculate_rsi(df["close"], 7)
        df["rsi_14"] = self.calculate_rsi(df["close"], 14)
        df["atr_14"] = self.calculate_atr(df["high"], df["low"], df["close"], 14)
        
        last = df.iloc[-1]
        pp = self.calculate_pivot_points(last["high"], last["low"], last["close"])

        trend = "BULLISH" if last["close"] > last["ema_50"] else "BEARISH"
        macd_trend = "POSITIVE" if last["macd_line"] > last["macd_signal"] else "NEGATIVE"

        return {
            "symbol": ticker,
            "price": last["close"],
            "trend": trend,
            "rsi": round(last["rsi_14"], 2),
            "macd": macd_trend,
            "support": round(last["close"] - (2 * last["atr_14"]), 2),
            "resistance": round(last["close"] + (2 * last["atr_14"]), 2),
            "details": {
                "ema_20": round(last["ema_20"], 2),
                "ema_50": round(last["ema_50"], 2),
                "rsi_7": round(last["rsi_7"], 2),
                "atr": round(last["atr_14"], 2),
                "pivot_pp": round(pp["pp"], 2)
            }
        }
    def get_multi_tf_analysis(self, ticker: str) -> Dict:
        """Analisi su 4 timeframe: 15m, 1H, 4H, 1D"""
        timeframes = ["15m", "1h", "4h", "1d"]
        result = {"symbol":  ticker, "timeframes": {}}
        
        # Fetch additional short timeframes for crash guard metrics
        crash_guard_timeframes = ["1m", "5m"]
        
        for tf in timeframes:
            try:
                df = self.fetch_ohlcv(ticker, tf, limit=100)
                if df.empty:
                    continue
                
                df["ema_20"] = self.calculate_ema(df["close"], 20)
                df["ema_50"] = self.calculate_ema(df["close"], 50)
                macd_line, macd_sig, macd_hist = self.calculate_macd(df["close"])
                df["rsi_14"] = self.calculate_rsi(df["close"], 14)
                df["atr_14"] = self.calculate_atr(df["high"], df["low"], df["close"], 14)
                
                last = df.iloc[-1]
                trend = "BULLISH" if last["close"] > last["ema_50"] else "BEARISH"
                macd_trend = "POSITIVE" if macd_line.iloc[-1] > macd_sig.iloc[-1] else "NEGATIVE"
                
                if len(macd_hist) >= 3:
                    macd_momentum = "RISING" if macd_hist.iloc[-1] > macd_hist.iloc[-3] else "FALLING"
                else: 
                    macd_momentum = "NEUTRAL"
                
                # Calculate crash guard metrics
                crash_metrics = {}
                
                # Return % (close-to-close change)
                if len(df) >= 2:
                    close_current = float(df.iloc[-1]["close"])
                    close_prev = float(df.iloc[-2]["close"])
                    if close_prev > 0:
                        return_pct = ((close_current - close_prev) / close_prev) * 100
                        crash_metrics[f"return_{tf}"] = round(return_pct, 3)
                
                # Range % (high-low / close)
                high_val = float(last["high"])
                low_val = float(last["low"])
                close_val = float(last["close"])
                if close_val > 0:
                    range_pct = ((high_val - low_val) / close_val) * 100
                    crash_metrics[f"range_{tf}_pct"] = round(range_pct, 3)
                
                # Volume spike (current volume / average volume over last 20 periods)
                if len(df) >= 20 and "volume" in df.columns:
                    current_vol = float(last["volume"])
                    avg_vol = float(df["volume"].tail(20).mean())
                    if avg_vol > 0:
                        volume_spike = current_vol / avg_vol
                        crash_metrics[f"volume_spike_{tf}"] = round(volume_spike, 3)
                
                result["timeframes"][tf] = {
                    "price": round(float(last["close"]), 2),
                    "trend":  trend,
                    "rsi": round(float(last["rsi_14"]), 2),
                    "macd": macd_trend,
                    "macd_momentum": macd_momentum,
                    "ema_20": round(float(last["ema_20"]), 2),
                    "ema_50": round(float(last["ema_50"]), 2),
                    "atr":  round(float(last["atr_14"]), 4),
                    **crash_metrics  # Include crash guard metrics
                }
            except Exception as e: 
                print(f"Error analyzing {ticker} on {tf}: {e}")
                continue
        
        # Add crash guard timeframes (1m, 5m) with minimal indicators
        for tf in crash_guard_timeframes:
            try:
                df = self.fetch_ohlcv(ticker, tf, limit=100)
                if df.empty:
                    continue
                
                # Calculate only essential metrics for crash guard
                last = df.iloc[-1]
                
                crash_metrics = {}
                
                # Return % (close-to-close change)
                if len(df) >= 2:
                    close_current = float(df.iloc[-1]["close"])
                    close_prev = float(df.iloc[-2]["close"])
                    if close_prev > 0:
                        return_pct = ((close_current - close_prev) / close_prev) * 100
                        crash_metrics[f"return_{tf}"] = round(return_pct, 3)
                
                # Range % (high-low / close)
                high_val = float(last["high"])
                low_val = float(last["low"])
                close_val = float(last["close"])
                if close_val > 0:
                    range_pct = ((high_val - low_val) / close_val) * 100
                    crash_metrics[f"range_{tf}_pct"] = round(range_pct, 3)
                
                # Volume spike
                if len(df) >= 20 and "volume" in df.columns:
                    current_vol = float(last["volume"])
                    avg_vol = float(df["volume"].tail(20).mean())
                    if avg_vol > 0:
                        volume_spike = current_vol / avg_vol
                        crash_metrics[f"volume_spike_{tf}"] = round(volume_spike, 3)
                
                result["timeframes"][tf] = {
                    "price": round(float(last["close"]), 2),
                    **crash_metrics
                }
            except Exception as e:
                print(f"Error analyzing {ticker} on {tf}: {e}")
                continue
        
        tf_1d = result["timeframes"].get("1d", {})
        tf_4h = result["timeframes"].get("4h", {})
        tf_1h = result["timeframes"].get("1h", {})
        tf_15m = result["timeframes"].get("15m", {})
        tf_5m = result["timeframes"].get("5m", {})
        tf_1m = result["timeframes"].get("1m", {})
        
        result["summary"] = {
            "regime": tf_1d.get("trend", "UNKNOWN"),
            "regime_rsi": tf_1d.get("rsi", 50),
            "bias": tf_4h.get("trend", "UNKNOWN"),
            "bias_rsi": tf_4h.get("rsi", 50),
            "bias_macd": tf_4h.get("macd", "NEUTRAL"),
            "confirm": tf_1h.get("trend", "UNKNOWN"),
            "confirm_rsi": tf_1h.get("rsi", 50),
            "confirm_macd": tf_1h.get("macd", "NEUTRAL"),
            "confirm_macd_momentum": tf_1h.get("macd_momentum", "NEUTRAL"),
            "entry_trend": tf_15m.get("trend", "UNKNOWN"),
            "entry_rsi": tf_15m.get("rsi", 50),
            "entry_price": tf_15m.get("price", 0),
            "entry_atr": tf_15m.get("atr", 0),
            # Crash guard metrics for decision making
            "return_1m": tf_1m.get("return_1m", 0),
            "return_5m": tf_5m.get("return_5m", 0),
            "return_15m": tf_15m.get("return_15m", 0),
            "range_5m_pct": tf_5m.get("range_5m_pct", 0),
            "volume_spike_5m": tf_5m.get("volume_spike_5m", 1.0)
        }
        
        result["summary"]["tf_aligned"] = (tf_4h.get("trend") == tf_1h.get("trend"))
        
        return result
