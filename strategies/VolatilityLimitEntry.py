"""
VolatilityLimitEntry - ATR Breakout 3h con limit order su pullback

Mantiene il segnale ATR3h (che funzionava in backtest con 67% winrate)
ma invece di entrare a mercato sul breakout (tardi, prezzo già mosso),
piazza un ordine limit al 50% del movimento — aspetta il pullback.

Esempio:
  - BTC a 100, breakout a 107 (+7% su 3h, > ATR)
  - Invece di entrare a 107, piazza limit a 103.5 (50% del move)
  - Se BTC torna a 103.5 → ordine riempito a prezzo migliore
  - Se non torna entro 3 ore → ordine cancellato, skip del trade

Vantaggi:
  - Entry price migliore (non insegue il picco)
  - Filtro naturale: i falsi breakout tornano al livello e si entra,
    i breakout forti NON tornano (skip) → evita entrate su trend già esaurito
  - Exit: SOLO trailing stop (no exit signal che taglia i winner)
  - Trailing: attivo da +8%, trail 4%
"""

import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
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


class VolatilityLimitEntry(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True

    order_types = {
        'entry': 'limit',
        'exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False
    }

    # Ordine limit scade dopo 3 ore se non riempito
    unfilledtimeout = {'entry': 180, 'exit': 60, 'unit': 'minutes'}

    minimal_roi = {"0": 100}

    stoploss = -0.08
    use_custom_stoploss = False

    # Trailing: attivo da +8%, trail 4% sotto il picco
    trailing_stop = True
    trailing_stop_positive = 0.04
    trailing_stop_positive_offset = 0.08
    trailing_only_offset_is_reached = True

    ignore_roi_if_entry_signal = True
    position_adjustment_enable = False
    startup_candle_count = 50

    # Quanto risaliamo/scendiamo rispetto al breakout per piazzare il limit
    # 0.5 = 50% del move (pullback a metà), 0.3 = 30%, 0.7 = 70%
    pullback_ratio = DecimalParameter(0.2, 0.7, default=0.5, decimals=1, space='buy', optimize=True)
    atr_mult = DecimalParameter(1.5, 3.0, default=1.5, decimals=1, space='buy', optimize=True)

    use_macro_filter = True
    max_same_direction = 3

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df_3h = resample_to_3h(dataframe)
        df_3h['atr'] = calc_atr(df_3h) * self.atr_mult.value
        df_3h['close_change'] = df_3h['close'].diff()
        df_3h['prev_close'] = df_3h['close'].shift(1)  # close pre-breakout

        df_3h = df_3h.rename(columns={
            'atr': 'atr_3h',
            'close_change': 'close_change_3h',
            'prev_close': 'prev_close_3h',
        })[['date', 'atr_3h', 'close_change_3h', 'prev_close_3h']]

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
        dataframe.loc[long_signal, 'enter_tag'] = 'atr_breakout_limit_long'
        dataframe.loc[short_signal, 'enter_tag'] = 'atr_breakout_limit_short'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Nessun exit signal — solo trailing stop e stoploss
        # Evita che i winner vengano tagliati dal segnale opposto
        return dataframe

    def custom_entry_price(self, pair: str, trade: Optional[Trade],
                           current_time: datetime, proposed_rate: float,
                           entry_tag: Optional[str], side: str, **kwargs) -> float:
        """
        Piazza il limit a metà del breakout (pullback entry).
        Long: prezzo attuale - (close_change_3h * pullback_ratio)
        Short: prezzo attuale + (|close_change_3h| * pullback_ratio)
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) == 0:
            return proposed_rate

        last = dataframe.iloc[-1]
        move = abs(float(last['close_change_3h']))
        ratio = self.pullback_ratio.value

        if side == 'long':
            limit_price = proposed_rate - (move * ratio)
        else:
            limit_price = proposed_rate + (move * ratio)

        # Safety: non allontanarsi più del 5% dal proposed_rate
        max_deviation = proposed_rate * 0.05
        if side == 'long':
            limit_price = max(limit_price, proposed_rate - max_deviation)
        else:
            limit_price = min(limit_price, proposed_rate + max_deviation)

        return float(limit_price)

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

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float,
                 entry_tag: Optional[str], side: str, **kwargs) -> float:
        return 2.0
