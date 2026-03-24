"""
VolatilitySystemOpt - Versione con parametri ottimizzabili per hyperopt

Parametri da ottimizzare:
- atr_mult: moltiplicatore ATR per l'entry (1.5-3.0)
- pHSL: hard stop loss
- pPF_1/pSL_1: primo livello trailing
- pPF_2/pSL_2: secondo livello trailing (= quando attivare trailing aggressivo)
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
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


class VolatilitySystemOpt(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True
    minimal_roi = {"0": 100}
    stoploss = -0.20
    use_custom_stoploss = True
    trailing_stop = False
    ignore_roi_if_entry_signal = True
    position_adjustment_enable = True
    startup_candle_count = 50

    # === BUY: ATR multiplier ===
    atr_mult = DecimalParameter(1.0, 4.0, default=2.0, decimals=1, space='buy', optimize=True)

    # === SELL: custom stoploss parametri (trailing lineare come MitragliereFutures) ===
    # Hard stop (protezione massima perdita)
    pHSL = DecimalParameter(-0.20, -0.05, default=-0.10, decimals=2, space='sell', optimize=True)

    # Livello 1: attiva il trailing quando raggiungi PF_1, stop a SL_1
    pPF_1 = DecimalParameter(0.05, 0.20, default=0.10, decimals=2, space='sell', optimize=True)
    pSL_1 = DecimalParameter(0.02, 0.10, default=0.05, decimals=2, space='sell', optimize=True)

    # Livello 2: trailing aggressivo quando raggiungi PF_2, stop a SL_2
    pPF_2 = DecimalParameter(0.15, 0.50, default=0.25, decimals=2, space='sell', optimize=True)
    pSL_2 = DecimalParameter(0.08, 0.30, default=0.15, decimals=2, space='sell', optimize=True)

    use_macro_filter = True
    max_same_direction = 3

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df_3h = resample_to_3h(dataframe)
        df_3h['atr'] = calc_atr(df_3h) * self.atr_mult.value
        df_3h['close_change'] = df_3h['close'].diff()

        df_3h = df_3h.rename(columns={
            'atr': 'atr_3h',
            'close_change': 'close_change_3h',
        })[['date', 'atr_3h', 'close_change_3h']]

        dataframe = pd.merge_asof(
            dataframe.sort_values('date'),
            df_3h.sort_values('date'),
            on='date',
            direction='backward'
        )

        dataframe['sma200_1h'] = dataframe['close'].rolling(200).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_signal = dataframe['close_change_3h'] > dataframe['atr_3h'].shift(1)
        short_signal = dataframe['close_change_3h'] * -1 > dataframe['atr_3h'].shift(1)

        if self.use_macro_filter:
            long_signal = long_signal & (dataframe['close'] > dataframe['sma200_1h'])
            short_signal = short_signal & (dataframe['close'] < dataframe['sma200_1h'])

        dataframe.loc[long_signal, 'enter_long'] = 1
        dataframe.loc[short_signal, 'enter_short'] = 1
        dataframe.loc[long_signal, 'enter_tag'] = 'vol_long'
        dataframe.loc[short_signal, 'enter_tag'] = 'vol_short'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        short_signal = dataframe['close_change_3h'] * -1 > dataframe['atr_3h'].shift(1)
        long_signal = dataframe['close_change_3h'] > dataframe['atr_3h'].shift(1)
        dataframe.loc[short_signal, 'exit_long'] = 1
        dataframe.loc[long_signal, 'exit_short'] = 1
        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float:
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value

        # Interpolazione lineare tra i livelli
        if current_profit > PF_2:
            sl_profit = SL_2 + (current_profit - PF_2)
        elif current_profit > PF_1:
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            sl_profit = HSL

        if sl_profit >= current_profit:
            return -0.99

        return stoploss_from_open(sl_profit, current_profit,
                                  is_short=trade.is_short,
                                  leverage=trade.leverage)

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
        return max_stake / self.config.get('max_open_trades', 4) * 0.5

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                               current_rate: float, current_profit: float,
                               min_stake: Optional[float], max_stake: float,
                               current_entry_rate: float, current_exit_rate: float,
                               current_entry_profit: float, current_exit_profit: float,
                               **kwargs) -> Optional[float]:
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
