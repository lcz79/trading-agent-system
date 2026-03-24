"""
VolatilitySystem Pandas - ATR Breakout Strategy

Basata su: https://www.tradingview.com/script/3hhs0XbR/
Adattata da: freqtrade official futures strategies
Riscritta senza talib/technical libraries (pandas only)

LOGICA:
- Resample 1h → 3h candles
- ATR(14) * 2.0 sulla timeframe 3h
- LONG quando close_change_3h > ATR_3h (breakout rialzista)
- SHORT quando close_change_3h < -ATR_3h (breakout ribassista)
- Exit quando segnale opposto
- Position scaling: entra 50% poi aggiunge altri 50% su conferma

DIFFERENZA vs altre strategie:
- Segue i BREAKOUT di volatilità invece di mean reversion
- Trades mediamente più lunghi (3h resolution)
- Position size dinamica (DCA in direzione del trend)
"""

import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from freqtrade.strategy import stoploss_from_open
from freqtrade.persistence import Trade
from freqtrade.exchange import date_minus_candles


def resample_to_3h(df: DataFrame) -> DataFrame:
    """Resample 1h OHLCV to 3h."""
    df = df.copy()
    df = df.set_index('date')
    resampled = df.resample('3h').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    resampled.index.name = 'date'
    return resampled.reset_index()


def calc_atr(df: DataFrame, period: int = 14) -> pd.Series:
    """ATR calculation without talib."""
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


class VolatilitySystemPandas(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True

    minimal_roi = {"0": 100}  # Exit solo su segnale opposto

    stoploss = -0.15  # Hard stop molto largo (speriamo non venga mai toccato)
    use_custom_stoploss = False  # NO custom stop — questa strategia non usa stop fissi
    trailing_stop = False
    ignore_roi_if_entry_signal = True
    position_adjustment_enable = True  # Per il DCA
    startup_candle_count = 50

    # ATR multiplier (default 2.0 dall'originale)
    atr_mult = DecimalParameter(1.5, 3.0, default=2.0, decimals=1, space='buy', optimize=True)

    # Macro filter opzionale
    use_macro_filter = True

    max_same_direction = 3

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # === Resample a 3h ===
        df_3h = resample_to_3h(dataframe)
        df_3h['atr'] = calc_atr(df_3h) * self.atr_mult.value
        df_3h['close_change'] = df_3h['close'].diff()
        df_3h['abs_close_change'] = df_3h['close_change'].abs()

        # Merge 3h back to 1h con forward fill
        df_3h = df_3h.rename(columns={
            'atr': 'atr_3h',
            'close_change': 'close_change_3h',
            'abs_close_change': 'abs_close_change_3h'
        })[['date', 'atr_3h', 'close_change_3h', 'abs_close_change_3h']]

        dataframe = pd.merge_asof(
            dataframe.sort_values('date'),
            df_3h.sort_values('date'),
            on='date',
            direction='backward'
        )

        # === 1h SMA per macro filter ===
        dataframe['sma50_1h'] = dataframe['close'].rolling(50).mean()
        dataframe['sma200_1h'] = dataframe['close'].rolling(200).mean()

        # === ATR 1h per custom stop in futuro ===
        tr_1h = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift(1)).abs(),
            (dataframe['low'] - dataframe['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        dataframe['atr_1h'] = tr_1h.ewm(alpha=1 / 14, min_periods=14).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Breakout rialzista 3h: close_change > ATR
        long_signal = dataframe['close_change_3h'] > dataframe['atr_3h'].shift(1)
        # Breakout ribassista 3h: close_change < -ATR
        short_signal = dataframe['close_change_3h'] * -1 > dataframe['atr_3h'].shift(1)

        if self.use_macro_filter:
            above_sma200 = dataframe['close'] > dataframe['sma200_1h']
            below_sma200 = dataframe['close'] < dataframe['sma200_1h']
            long_signal = long_signal & above_sma200
            short_signal = short_signal & below_sma200

        dataframe.loc[long_signal, 'enter_long'] = 1
        dataframe.loc[short_signal, 'enter_short'] = 1
        dataframe.loc[long_signal, 'enter_tag'] = 'vol_breakout_long'
        dataframe.loc[short_signal, 'enter_tag'] = 'vol_breakout_short'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit LONG quando segnale SHORT (breakout opposto)
        short_signal = dataframe['close_change_3h'] * -1 > dataframe['atr_3h'].shift(1)
        dataframe.loc[short_signal, 'exit_long'] = 1

        # Exit SHORT quando segnale LONG
        long_signal = dataframe['close_change_3h'] > dataframe['atr_3h'].shift(1)
        dataframe.loc[long_signal, 'exit_short'] = 1

        return dataframe

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: Optional[str], side: str, **kwargs) -> bool:
        if 2 <= current_time.hour < 6:
            return False
        is_short = (side == 'short')
        open_trades = Trade.get_open_trades()
        same_dir_count = sum(1 for t in open_trades if t.is_short == is_short)
        if same_dir_count >= self.max_same_direction:
            return False
        return True

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                             proposed_stake: float, min_stake: Optional[float],
                             max_stake: float, leverage: float, entry_tag: Optional[str],
                             side: str, **kwargs) -> float:
        # Entra con 50% del capitale disponibile (come l'originale)
        return max_stake / self.config.get('max_open_trades', 4) * 0.5

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                               current_rate: float, current_profit: float,
                               min_stake: Optional[float], max_stake: float,
                               current_entry_rate: float, current_exit_rate: float,
                               current_entry_profit: float, current_exit_profit: float,
                               **kwargs) -> Optional[float]:
        """Aggiunge 50% in più sulla stessa direzione se segnale si ripete."""
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
            if len(dataframe) < 2:
                return None

            last = dataframe.iloc[-1]
            prev = dataframe.iloc[-2]
            signal_col = 'enter_long' if not trade.is_short else 'enter_short'

            prior_date = date_minus_candles(self.timeframe, 1, current_time)

            if (
                last[signal_col] == 1 and
                prev[signal_col] != 1 and
                trade.nr_of_successful_entries < 2 and
                trade.orders and
                trade.orders[-1].order_date_utc < prior_date
            ):
                return trade.stake_amount
        except Exception:
            pass
        return None

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float,
                 entry_tag: Optional[str], side: str, **kwargs) -> float:
        return 2.0
