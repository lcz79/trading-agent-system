"""
MitragliereFutures v2 - Adaptive Regime Strategy
Combines: BB_RPB_TSL_RNG (multi-entry) + Solipsis v5 (trend-aware exits) + Regime Detection

TRENDING (ADX > 25): Supertrend + EMA crossover entries
RANGING  (ADX < 25): BB bounce + RSI mean reversion entries
ALWAYS: HTF SMA50 bias filter, linear interpolation stoploss, breakeven, trend-aware exits
"""
import numpy as np
import pandas as pd
from pandas import DataFrame, Series
from functools import reduce
from datetime import datetime

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter, CategoricalParameter
from freqtrade.strategy import merge_informative_pair, stoploss_from_open, informative
from freqtrade.persistence import Trade


def supertrend(df, period=10, multiplier=3.0):
    """Supertrend indicator."""
    hl2 = (df['high'] + df['low']) / 2
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    direction = pd.Series(1, index=df.index)

    for i in range(period, len(df)):
        if df['close'].iloc[i] > upper.iloc[i-1]:
            direction.iloc[i] = 1
        elif df['close'].iloc[i] < lower.iloc[i-1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i-1]
        if direction.iloc[i] == 1:
            lower.iloc[i] = max(lower.iloc[i], lower.iloc[i-1]) if direction.iloc[i-1] == 1 else lower.iloc[i]
        else:
            upper.iloc[i] = min(upper.iloc[i], upper.iloc[i-1]) if direction.iloc[i-1] == -1 else upper.iloc[i]

    return direction


def williams_r(dataframe, period=14):
    highest = dataframe['high'].rolling(period).max()
    lowest = dataframe['low'].rolling(period).min()
    return ((highest - dataframe['close']) / (highest - lowest)) * -100


def EWO(dataframe, fast=5, slow=35):
    return (dataframe['close'].ewm(span=fast).mean() - dataframe['close'].ewm(span=slow).mean()) / dataframe['low'] * 100


class MitragliereFutures(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True

    # Disabled ROI - we use custom exits
    minimal_roi = {"0": 100}

    # Fallback stoploss - custom_stoploss overrides
    stoploss = -0.08
    use_custom_stoploss = True
    trailing_stop = False
    ignore_roi_if_entry_signal = True

    # Max open trades
    position_adjustment_enable = False
    startup_candle_count = 0

    # === REGIME DETECTION ===
    adx_regime_threshold = IntParameter(20, 35, default=25, space='buy', optimize=True)

    # === TRENDING ENTRY (Supertrend) ===
    st_period = IntParameter(7, 21, default=8, space='buy', optimize=True)
    st_mult = DecimalParameter(2.0, 5.0, default=3.0, decimals=1, space='buy', optimize=True)

    # === RANGING ENTRY (BB + RSI) ===
    buy_rsi = IntParameter(15, 40, default=38, space='buy', optimize=True)
    sell_rsi = IntParameter(60, 85, default=60, space='buy', optimize=True)
    buy_bb_factor = DecimalParameter(0.97, 1.0, default=0.99, decimals=3, space='buy', optimize=True)

    # === EWO FILTER ===
    buy_ewo_low = DecimalParameter(-8.0, -2.0, default=-5.0, decimals=1, space='buy', optimize=True)
    buy_ewo_high = DecimalParameter(2.0, 8.0, default=4.0, decimals=1, space='buy', optimize=True)

    # === STOPLOSS (linear interpolation from BB_RPB_TSL) ===
    pHSL = DecimalParameter(-0.10, -0.04, default=-0.06, decimals=3, space='sell', optimize=True)
    pPF_1 = DecimalParameter(0.008, 0.030, default=0.015, decimals=3, space='sell', optimize=True)
    pSL_1 = DecimalParameter(0.008, 0.025, default=0.012, decimals=3, space='sell', optimize=True)
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.065, decimals=3, space='sell', optimize=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.050, decimals=3, space='sell', optimize=True)

    # Track trends per pair (from Solipsis)
    custom_trade_info = {}

    @informative('4h')
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sma50'] = dataframe['close'].rolling(50).mean()
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # === ATR ===
        tr = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift()).abs(),
            (dataframe['low'] - dataframe['close'].shift()).abs()
        ], axis=1).max(axis=1)
        dataframe['atr'] = tr.ewm(alpha=1/14, min_periods=14).mean()

        # === ADX (regime detection) ===
        up = dataframe['high'] - dataframe['high'].shift()
        down = dataframe['low'].shift() - dataframe['low']
        plus_dm = np.where((up > down) & (up > 0), up, 0)
        minus_dm = np.where((down > up) & (down > 0), down, 0)
        atr14 = tr.ewm(alpha=1/14, min_periods=14).mean()
        plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/14, min_periods=14).mean() / atr14
        minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/14, min_periods=14).mean() / atr14
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
        dataframe['adx'] = dx.ewm(alpha=1/14, min_periods=14).mean()
        dataframe['plus_di'] = plus_di
        dataframe['minus_di'] = minus_di

        # === SUPERTREND (trending entries) ===
        dataframe['st_dir'] = supertrend(dataframe, self.st_period.value, self.st_mult.value)

        # === BOLLINGER BANDS (ranging entries) ===
        bb = dataframe['close'].rolling(20).agg(['mean', 'std'])
        dataframe['bb_mid'] = dataframe['close'].rolling(20).mean()
        dataframe['bb_std'] = dataframe['close'].rolling(20).std()
        dataframe['bb_upper'] = dataframe['bb_mid'] + 2 * dataframe['bb_std']
        dataframe['bb_lower'] = dataframe['bb_mid'] - 2 * dataframe['bb_std']

        # === RSI ===
        delta = dataframe['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
        dataframe['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))

        # === EMA ===
        dataframe['ema_8'] = dataframe['close'].ewm(span=8).mean()
        dataframe['ema_26'] = dataframe['close'].ewm(span=26).mean()
        dataframe['ema_50'] = dataframe['close'].ewm(span=50).mean()

        # === EWO ===
        dataframe['ewo'] = EWO(dataframe, 50, 200)

        # === Williams %R ===
        dataframe['r_14'] = williams_r(dataframe, 14)

        # === Volume ===
        dataframe['vol_ma'] = dataframe['volume'].rolling(20).mean()

        # === SSL Channel (trend direction for exits, from Solipsis) ===
        sma_high = dataframe['high'].rolling(21).mean() + dataframe['atr']
        sma_low = dataframe['low'].rolling(21).mean() - dataframe['atr']
        hlv = np.where(dataframe['close'] > sma_high, 1, np.where(dataframe['close'] < sma_low, -1, np.nan))
        hlv = pd.Series(hlv).ffill().values
        dataframe['ssl_dir'] = hlv

        # === SROC (for stoploss bailout, from Solipsis) ===
        roc = dataframe['close'].pct_change(21) * 100
        ema13 = dataframe['close'].ewm(span=13).mean()
        dataframe['sroc'] = ema13.pct_change(21) * 100

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        is_trending = dataframe['adx'] > self.adx_regime_threshold.value
        is_ranging = ~is_trending

        # === TRENDING LONG: Supertrend up + EMA bullish + HTF above SMA50 ===
        trend_long = (
            is_trending &
            (dataframe['st_dir'] == 1) &
            (dataframe['ema_8'] > dataframe['ema_26']) &
            (dataframe['close'] > dataframe['sma50_4h']) &
            (dataframe['plus_di'] > dataframe['minus_di']) &
            (dataframe['volume'] > dataframe['vol_ma'] * 0.5)
        )

        # === TRENDING SHORT: Supertrend down + EMA bearish + HTF below SMA50 ===
        trend_short = (
            is_trending &
            (dataframe['st_dir'] == -1) &
            (dataframe['ema_8'] < dataframe['ema_26']) &
            (dataframe['close'] < dataframe['sma50_4h']) &
            (dataframe['minus_di'] > dataframe['plus_di']) &
            (dataframe['volume'] > dataframe['vol_ma'] * 0.5)
        )

        # === RANGING LONG: BB bounce + RSI oversold ===
        range_long = (
            is_ranging &
            (dataframe['close'] < dataframe['bb_lower'] * self.buy_bb_factor.value) &
            (dataframe['rsi'] < self.buy_rsi.value) &
            (dataframe['r_14'] < -80) &
            (dataframe['close'] > dataframe['sma50_4h'] * 0.97) &  # Not too far below HTF trend
            (dataframe['volume'] > dataframe['vol_ma'] * 0.5)
        )

        # === RANGING SHORT: BB rejection + RSI overbought ===
        range_short = (
            is_ranging &
            (dataframe['close'] > dataframe['bb_upper'] * (2 - self.buy_bb_factor.value)) &
            (dataframe['rsi'] > self.sell_rsi.value) &
            (dataframe['r_14'] > -20) &
            (dataframe['close'] < dataframe['sma50_4h'] * 1.03) &
            (dataframe['volume'] > dataframe['vol_ma'] * 0.5)
        )

        # Combine
        dataframe.loc[trend_long | range_long, 'enter_long'] = 1
        dataframe.loc[trend_short | range_short, 'enter_short'] = 1

        # Tags
        dataframe.loc[trend_long, 'enter_tag'] = 'trend_long'
        dataframe.loc[range_long, 'enter_tag'] = 'range_long'
        dataframe.loc[trend_short, 'enter_tag'] = 'trend_short'
        dataframe.loc[range_short, 'enter_tag'] = 'range_short'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit LONG only when BOTH Supertrend AND SSL flip bearish
        dataframe.loc[
            (dataframe['st_dir'] == -1) & (dataframe['ssl_dir'] == -1),
            'exit_long'
        ] = 1

        # Exit SHORT only when BOTH Supertrend AND SSL flip bullish
        dataframe.loc[
            (dataframe['st_dir'] == 1) & (dataframe['ssl_dir'] == 1),
            'exit_short'
        ] = 1

        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float:
        """
        Linear interpolation stoploss from BB_RPB_TSL_RNG:
        - Below PF_1: hard stoploss (HSL)
        - Between PF_1 and PF_2: linear interpolation from SL_1 to SL_2
        - Above PF_2: stoploss rises with profit (locks gains)

        Enhanced with Solipsis-style SROC bailout.
        """
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value

        if current_profit > PF_2:
            sl_profit = SL_2 + (current_profit - PF_2)
        elif current_profit > PF_1:
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            sl_profit = HSL

        if sl_profit >= current_profit:
            return -0.99

        # SROC bailout (from Solipsis): if momentum drops sharply while in loss, bail
        if current_profit < -0.02:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if not dataframe.empty:
                last = dataframe.iloc[-1]
                if last.get('sroc', 0) < -3.0:
                    return 0.01  # immediate exit

        return stoploss_from_open(sl_profit, current_profit, is_short=trade.is_short)

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float,
                 entry_tag: str | None, side: str, **kwargs) -> float:
        return 2.0

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None,
                            max_stake: float, leverage: float, entry_tag: str | None,
                            side: str, **kwargs) -> float:
        max_trades = self.config.get('max_open_trades', 4)
        return max_stake / max_trades
