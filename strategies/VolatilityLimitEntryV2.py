"""
VolatilityLimitEntryV2 - ATR Breakout 3h con ADX regime filter

V2: aggiunto filtro ADX 4h per evitare falsi breakout in mercati range.
Solo in mercato TREND (ADX_4h > 20) vengono aperti nuovi trade.
In range (ADX < 20): nessun trade, il bot aspetta.

Logica:
  1. ADX 4h > 20 → mercato in trend → abilita entries
  2. ATR Breakout 3h + SMA200 → direzione confermata
  3. RSI 1h → momentum non esaurito
  4. Limit order al 50% pullback → entry ottimale
  5. Trailing stop da +8% → cattura il trend completo

Exit: SOLO trailing stop (niente exit signal che taglia i winner)
Trailing: attivo da +8%, trail 4%
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


class VolatilityLimitEntryV2(IStrategy):
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
    startup_candle_count = 210

    # Quanto risaliamo/scendiamo rispetto al breakout per piazzare il limit
    pullback_ratio = DecimalParameter(0.2, 0.7, default=0.5, decimals=1, space='buy', optimize=True)
    atr_mult = DecimalParameter(1.5, 3.0, default=1.5, decimals=1, space='buy', optimize=True)
    # RSI: evita entry quando il momentum è già esaurito
    rsi_limit_long = IntParameter(50, 75, default=65, space='buy', optimize=True)
    rsi_limit_short = IntParameter(25, 50, default=35, space='buy', optimize=True)

    use_macro_filter = True
    max_same_direction = 3

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Segnale direzione: resample a 3h dal 15min
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

        # ── ADX 4h: regime detection ─────────────────────────────────────────
        # Calcoliamo ADX sul timeframe 1h con period 56 (equiv. ADX14 su 4h)
        # Per semplicità e velocità, calcoliamo ADX direttamente su 1h con period lungo
        up_move = dataframe['high'].diff()
        down_move = -dataframe['low'].diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift(1)).abs(),
            (dataframe['low'] - dataframe['close'].shift(1)).abs()
        ], axis=1).max(axis=1)

        period = 56  # ADX14 su 4h = ADX56 su 1h
        atr_adx = tr.ewm(alpha=1/period, min_periods=period).mean()
        plus_di = 100 * pd.Series(plus_dm, index=dataframe.index).ewm(alpha=1/period, min_periods=period).mean() / atr_adx.replace(0, np.nan)
        minus_di = 100 * pd.Series(minus_dm, index=dataframe.index).ewm(alpha=1/period, min_periods=period).mean() / atr_adx.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        dataframe['adx_4h'] = dx.ewm(alpha=1/period, min_periods=period).mean()

        # Regime: True = trending (trade abilitati), False = range (nessun trade)
        dataframe['is_trending'] = dataframe['adx_4h'] >= 20.0

        # RSI 14 su 15min per confermare il momentum
        delta = dataframe['close'].diff()
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / 14, min_periods=14).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 14, min_periods=14).mean()
        rs = gain / loss
        dataframe['rsi'] = 100 - (100 / (1 + rs))

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Segnale ATR 3h: breakout direzionale
        long_signal = dataframe['close_change_3h'] > dataframe['atr_3h'].shift(1)
        short_signal = dataframe['close_change_3h'] * -1 > dataframe['atr_3h'].shift(1)

        # Conferma RSI 15min: non entrare se il momentum è già esaurito
        # Long: RSI non in ipercomprato (prezzo non ha già corso troppo)
        # Short: RSI non in ipervenduto (prezzo non ha già caduto troppo)
        rsi_ok_long = dataframe['rsi'] < self.rsi_limit_long.value
        rsi_ok_short = dataframe['rsi'] > self.rsi_limit_short.value

        long_signal = long_signal & rsi_ok_long
        short_signal = short_signal & rsi_ok_short

        if self.use_macro_filter:
            long_signal = long_signal & (dataframe['close'] > dataframe['sma200_1h'])
            short_signal = short_signal & (dataframe['close'] < dataframe['sma200_1h'])

        # ADX regime filter: solo in mercato TREND (ADX_4h equiv > 20)
        long_signal = long_signal & dataframe['is_trending']
        short_signal = short_signal & dataframe['is_trending']

        dataframe.loc[long_signal, 'enter_long'] = 1
        dataframe.loc[short_signal, 'enter_short'] = 1
        dataframe.loc[long_signal, 'enter_tag'] = 'v2_trend_long'
        dataframe.loc[short_signal, 'enter_tag'] = 'v2_trend_short'

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
