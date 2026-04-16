"""
DualMode v3 - Swing Multi-Intensity

Il grid mean reversion non funziona in crypto: WR < 25% anche in range.
La media reversion richiede condizioni troppo precise che cambiano ogni ciclo.

Approccio: UN solo layer swing, ma con DUE soglie ATR diverse per catturare
sia i grandi breakout (ATR x1.5) che i movimenti medi (ATR x0.8).

STRONG SWING (ATR > 1.5x, trade 2-7 giorni):
  Trigger: ATR Breakout 3h forte + ADX >= 20 + SMA200 filter
  Entry: limit al 50% pullback
  Exit: trailing stop da +8%, trail 4%
  Max 2 posizioni

LIGHT SWING (ATR 0.8x-1.5x, trade 12h-3 giorni):
  Trigger: ATR Breakout 3h moderato + ADX >= 15 + EMA21 > EMA50 direction
  Entry: limit al 30% pullback (meno aggressivo)
  Exit: TP fisso +3% OPPURE trailing stop da +5%, trail 3%
  Max 2 posizioni

Totale: max 4 posizioni (2 strong + 2 light).
In entrambi i casi: entry con limit → preserva il vantaggio del pullback.
"""

import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy, DecimalParameter
from freqtrade.persistence import Trade


def resample_to_interval(df: DataFrame, interval: str = '3h') -> DataFrame:
    df = df.copy().set_index('date')
    resampled = df.resample(interval).agg({
        'open': 'first', 'high': 'max',
        'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()
    return resampled.reset_index()


def calc_atr(df: DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period).mean()


class DualMode(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True

    order_types = {
        'entry': 'limit',
        'exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False
    }

    unfilledtimeout = {'entry': 180, 'exit': 60, 'unit': 'minutes'}

    minimal_roi = {"0": 100}

    stoploss = -0.08
    use_custom_stoploss = True

    # Trailing: attivo da +8% per strong swing, trail 4%
    trailing_stop = True
    trailing_stop_positive = 0.04
    trailing_stop_positive_offset = 0.08
    trailing_only_offset_is_reached = True

    startup_candle_count = 250
    leverage_num = 2.0
    position_adjustment_enable = False

    # ─── Parametri strong swing ─────────────────────────────────────────────
    strong_atr_mult = DecimalParameter(1.2, 2.0, default=1.5, space='buy', optimize=False)
    strong_pullback = DecimalParameter(0.3, 0.7, default=0.5, space='buy', optimize=False)
    strong_adx_min = DecimalParameter(18.0, 28.0, default=20.0, space='buy', optimize=False)

    # ─── Parametri light swing ───────────────────────────────────────────────
    light_atr_mult = DecimalParameter(0.5, 1.2, default=0.8, space='buy', optimize=False)
    light_pullback = DecimalParameter(0.1, 0.4, default=0.15, space='buy', optimize=False)
    light_adx_min = DecimalParameter(12.0, 20.0, default=15.0, space='buy', optimize=False)
    light_tp = DecimalParameter(0.02, 0.05, default=0.03, space='buy', optimize=False)
    light_sl = DecimalParameter(0.02, 0.06, default=0.04, space='sell', optimize=False)

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: Optional[str],
                 side: str) -> float:
        return min(self.leverage_num, max_leverage)

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float:
        """
        Light swing: SL stretto -4% (TP +3%, R:R = 0.75, break-even WR = 57%)
        Strong swing: SL standard -8% (trailing gestisce i winner)
        """
        entry_tag = trade.enter_tag or ''
        if entry_tag.startswith('light_'):
            sl = -self.light_sl.value  # -4%
            if current_profit <= sl:
                return -0.001  # chiudi subito
            return sl
        return self.stoploss  # -8% per strong swing

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        """Light swing: TP fisso a +3% (non aspettare il trailing)"""
        entry_tag = trade.enter_tag or ''
        if entry_tag.startswith('light_'):
            if current_profit >= self.light_tp.value:
                return 'light_tp'
        return None

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ── SMA 200 (filtro macro) ─────────────────────────────────────────
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()

        # ── EMA per direction filter ───────────────────────────────────────
        dataframe['ema21'] = dataframe['close'].ewm(span=21, min_periods=21).mean()
        dataframe['ema50'] = dataframe['close'].ewm(span=50, min_periods=50).mean()

        # ── RSI 14 (filtro momentum per light swing) ───────────────────────
        delta = dataframe['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
        dataframe['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

        # ── ADX (regime / trend strength) ─────────────────────────────────
        up_move = dataframe['high'].diff()
        down_move = -dataframe['low'].diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift(1)).abs(),
            (dataframe['low'] - dataframe['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        period = 56  # ADX14 equiv su 4h
        atr_adx = tr.ewm(alpha=1/period, min_periods=period).mean()
        plus_di = 100 * pd.Series(plus_dm, index=dataframe.index).ewm(
            alpha=1/period, min_periods=period).mean() / atr_adx.replace(0, np.nan)
        minus_di = 100 * pd.Series(minus_dm, index=dataframe.index).ewm(
            alpha=1/period, min_periods=period).mean() / atr_adx.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        dataframe['adx'] = dx.ewm(alpha=1/period, min_periods=period).mean()

        # ── ATR Breakout 3h ───────────────────────────────────────────────
        df_3h = resample_to_interval(dataframe, '3h')
        df_3h['atr_3h'] = calc_atr(df_3h)  # ATR grezzo, moltiplichiamo sotto
        df_3h['close_change_3h'] = df_3h['close'].diff()
        df_3h = df_3h[['date', 'atr_3h', 'close_change_3h']]

        dataframe = pd.merge_asof(
            dataframe.sort_values('date'),
            df_3h.sort_values('date'),
            on='date', direction='backward'
        )

        sma200_slope = dataframe['sma200'] - dataframe['sma200'].shift(10)

        # ── STRONG SWING: ATR breakout forte + trend confermato ───────────
        strong_atr_threshold = dataframe['atr_3h'].shift(1) * self.strong_atr_mult.value
        strong_base = dataframe['adx'] >= self.strong_adx_min.value

        dataframe['strong_long'] = (
            strong_base &
            (dataframe['close_change_3h'] > strong_atr_threshold) &
            (dataframe['close'] > dataframe['sma200'])
        )
        dataframe['strong_short'] = (
            strong_base &
            (dataframe['close_change_3h'] * -1 > strong_atr_threshold) &
            (dataframe['close'] < dataframe['sma200']) &
            (sma200_slope < 0)
        )

        # ── LIGHT SWING: ATR breakout moderato, anche in trend debole ─────
        # Usa EMA direction come filtro invece di SMA200 (più reattivo)
        light_atr_min = dataframe['atr_3h'].shift(1) * self.light_atr_mult.value
        light_atr_max = dataframe['atr_3h'].shift(1) * self.strong_atr_mult.value  # non sovrapporsi
        light_base = (
            (dataframe['adx'] >= self.light_adx_min.value) &
            (dataframe['adx'] < self.strong_adx_min.value)  # solo in trend debole/medio
        )

        dataframe['light_long'] = (
            light_base &
            (dataframe['close_change_3h'] > light_atr_min) &
            (dataframe['close_change_3h'] <= light_atr_max) &  # non overlap con strong
            (dataframe['ema21'] > dataframe['ema50']) &  # struttura bullish
            (dataframe['close'] > dataframe['ema50']) &  # sopra la media media
            (dataframe['rsi'] < 70)  # non già ipercomprato
        )
        dataframe['light_short'] = (
            light_base &
            (dataframe['close_change_3h'] * -1 > light_atr_min) &
            (dataframe['close_change_3h'] * -1 <= light_atr_max) &
            (dataframe['ema21'] < dataframe['ema50']) &  # struttura bearish
            (dataframe['close'] < dataframe['ema50']) &
            (dataframe['rsi'] > 30)  # non già ipervenduto
        )

        # Ore notturne (no trade 02-05 UTC)
        dataframe['hour'] = dataframe['date'].dt.hour
        dataframe['no_trade'] = dataframe['hour'].between(2, 5)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0
        dataframe['enter_tag'] = ''

        base = (dataframe['volume'] > 0) & ~dataframe['no_trade']

        strong_long = base & dataframe['strong_long']
        strong_short = base & dataframe['strong_short']
        light_long = base & dataframe['light_long']
        light_short = base & dataframe['light_short']

        dataframe.loc[light_long, 'enter_tag'] = 'light_long'
        dataframe.loc[light_short, 'enter_tag'] = 'light_short'
        dataframe.loc[strong_long, 'enter_tag'] = 'strong_long'
        dataframe.loc[strong_short, 'enter_tag'] = 'strong_short'

        dataframe.loc[strong_long | light_long, 'enter_long'] = 1
        dataframe.loc[strong_short | light_short, 'enter_short'] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_short'] = 0
        return dataframe

    def custom_entry_price(self, pair: str, trade: Optional[Trade],
                           current_time: datetime, proposed_rate: float,
                           entry_tag: Optional[str], side: str, **kwargs) -> float:
        """
        Strong swing: limit al 50% del breakout (pullback profondo)
        Light swing: limit al 25% del breakout (pullback leggero, non perdiamo il trade)
        """
        if not entry_tag:
            return proposed_rate

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return proposed_rate

        last = dataframe.iloc[-1]
        close_change = abs(float(last.get('close_change_3h', 0)))

        if entry_tag.startswith('strong_'):
            pullback = close_change * self.strong_pullback.value
        elif entry_tag.startswith('light_'):
            pullback = close_change * self.light_pullback.value
        else:
            return proposed_rate

        if side == 'long':
            return proposed_rate - pullback
        else:
            return proposed_rate + pullback

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: Optional[str], side: str, **kwargs) -> bool:
        """
        Max 2 strong swing e max 2 light swing contemporanei.
        """
        open_trades = Trade.get_open_trades()
        tag = entry_tag or ''

        if tag.startswith('strong_'):
            count = sum(1 for t in open_trades if (t.enter_tag or '').startswith('strong_'))
            if count >= 2:
                return False
        elif tag.startswith('light_'):
            count = sum(1 for t in open_trades if (t.enter_tag or '').startswith('light_'))
            if count >= 2:
                return False

        return True
