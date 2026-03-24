"""
VolatilitySystemV2 - ATR Breakout con trade più corti

Modifiche vs V1:
- Trailing stop attivo: una volta in profitto, blocca il guadagno
- Minimal ROI più aggressivo: esci prima se raggiungi target
- Resample 1h (più veloce, segnali più frequenti)
- Filtro ATR% per evitare entrate in spike di volatilità estrema
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


def calc_atr(df: DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


class VolatilitySystemV2(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True

    # Esci a 10% profit oppure 5% dopo 2 giorni, 2% dopo 4 giorni
    minimal_roi = {"0": 0.10, "48": 0.05, "96": 0.02}

    stoploss = -0.15
    use_custom_stoploss = False

    # Trailing stop: inizia a trailing dopo 3% di profitto
    trailing_stop = True
    trailing_stop_positive = 0.03        # trailing a 3% sotto il picco
    trailing_stop_positive_offset = 0.05  # attiva il trailing solo dopo 5% profitto
    trailing_only_offset_is_reached = True

    ignore_roi_if_entry_signal = False
    position_adjustment_enable = True
    startup_candle_count = 50

    atr_mult = DecimalParameter(1.5, 3.0, default=2.0, decimals=1, space='buy', optimize=True)
    max_same_direction = 3

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ATR su 1h direttamente (no resampling)
        dataframe['atr'] = calc_atr(dataframe) * self.atr_mult.value
        dataframe['close_change'] = dataframe['close'].diff()
        dataframe['abs_close_change'] = dataframe['close_change'].abs()
        dataframe['atr_pct'] = dataframe['atr'] / dataframe['close']

        # SMA per macro filter
        dataframe['sma50'] = dataframe['close'].rolling(50).mean()
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        above_sma200 = dataframe['close'] > dataframe['sma200']
        below_sma200 = dataframe['close'] < dataframe['sma200']

        # No entry in volatilità estrema (spike isolati)
        not_extreme_vol = dataframe['atr_pct'] < 0.05

        long_signal = (
            (dataframe['close_change'] > dataframe['atr'].shift(1)) &
            above_sma200 &
            not_extreme_vol
        )
        short_signal = (
            (dataframe['close_change'] * -1 > dataframe['atr'].shift(1)) &
            below_sma200 &
            not_extreme_vol
        )

        dataframe.loc[long_signal, 'enter_long'] = 1
        dataframe.loc[short_signal, 'enter_short'] = 1
        dataframe.loc[long_signal, 'enter_tag'] = 'vol_long'
        dataframe.loc[short_signal, 'enter_tag'] = 'vol_short'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        short_signal = dataframe['close_change'] * -1 > dataframe['atr'].shift(1)
        long_signal = dataframe['close_change'] > dataframe['atr'].shift(1)

        dataframe.loc[short_signal, 'exit_long'] = 1
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
