"""
MitragliereFutures v13 - Time-Based Early Exit

ANALISI v12: exit signals aiutano (+0.41% → +0.69%) ma hard stops -5% persistono.
MOTIVO: stoploss fires INTRA-CANDELA mentre exit signal su close → next candle.
Quindi per trade con drop violento in 1 candela, exit signal arriva tardi.

FIX v13: Time-Based Early Exit nel custom_stoploss.
- Nelle prime 3 ore del trade: stop molto più stretto (-2% position = -1% price)
- Questo intercetta i setup-failed INTRA-CANDELA prima del pHSL
- Dopo 3 ore: normale custom stoploss (trade stabilizzato = reversal confermato)

LOGICA:
- Trade valido: nelle prime 3h il prezzo NON dovrebbe scendere > 1% da entry
  (se il reversal è reale, il momentum è positivo fin da subito)
- Trade invalido: nelle prime 3h scende > 1% → setup fallito → exit rapido
  (invece di aspettare il pHSL a -5%)

ATTESO: i 6 hard stops da -5% ciascuno (-) diventano ~-2% (-.80) = +.20 improvement

BASE: identico v9 (meglio di tutte, +0.41%, 58.6% WR) + v12 exit signals
"""
import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from freqtrade.strategy import merge_informative_pair, stoploss_from_open, informative
from freqtrade.persistence import Trade


def williams_r(dataframe, period=14):
    highest = dataframe['high'].rolling(period).max()
    lowest = dataframe['low'].rolling(period).min()
    return ((highest - dataframe['close']) / (highest - lowest)) * -100


class MitragliereFuturesV13(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True
    minimal_roi = {"0": 0.03}
    stoploss = -0.08
    use_custom_stoploss = True
    trailing_stop = False
    ignore_roi_if_entry_signal = True
    position_adjustment_enable = False
    startup_candle_count = 0

    # === SHORT: RSI cross-below (peak confirmation, 2-candle) ===
    rsi_short_peak = IntParameter(55, 72, default=62, space='buy', optimize=True)

    # === LONG: BB lower extreme + reversal confirmation ===
    bb_long_factor = DecimalParameter(0.98, 1.00, default=0.998, decimals=3, space='buy', optimize=True)
    rsi_long_confirm = IntParameter(25, 45, default=38, space='buy', optimize=True)

    # Trend margin vs SMA50 4h
    trend_margin = DecimalParameter(0.00, 0.02, default=0.005, decimals=3, space='buy', optimize=True)

    # ATR filter
    atr_max_pct = DecimalParameter(0.008, 0.025, default=0.015, decimals=3, space='buy', optimize=True)

    # Volume
    vol_mult = DecimalParameter(0.5, 2.0, default=0.8, decimals=1, space='buy', optimize=True)

    # STOPLOSS standard
    pHSL = DecimalParameter(-0.08, -0.02, default=-0.05, decimals=3, space='sell', optimize=True)
    pPF_1 = DecimalParameter(0.010, 0.030, default=0.015, decimals=3, space='sell', optimize=True)
    pSL_1 = DecimalParameter(0.005, 0.015, default=0.010, decimals=3, space='sell', optimize=True)
    pPF_2 = DecimalParameter(0.025, 0.060, default=0.035, decimals=3, space='sell', optimize=True)
    pSL_2 = DecimalParameter(0.015, 0.050, default=0.025, decimals=3, space='sell', optimize=True)

    # Early exit: stop durante prime N ore del trade (setup validation)
    early_exit_hours = 3   # hours
    early_exit_stop = -0.02  # -2% position = -1% price con 2x leva

    # BB fail exit threshold (exit signal)
    bb_fail_factor = 0.990   # 1% sotto BB_lower

    max_same_direction = 2

    @informative('4h')
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sma50'] = dataframe['close'].rolling(50).mean()
        return dataframe

    @informative('1d')
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()
        dataframe['sma50'] = dataframe['close'].rolling(50).mean()
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        tr = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift()).abs(),
            (dataframe['low'] - dataframe['close'].shift()).abs()
        ], axis=1).max(axis=1)
        dataframe['atr'] = tr.ewm(alpha=1/14, min_periods=14).mean()
        dataframe['atr_pct'] = dataframe['atr'] / dataframe['close']

        delta = dataframe['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
        dataframe['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))

        dataframe['bb_mid'] = dataframe['close'].rolling(20).mean()
        dataframe['bb_std'] = dataframe['close'].rolling(20).std()
        dataframe['bb_upper'] = dataframe['bb_mid'] + 2 * dataframe['bb_std']
        dataframe['bb_lower'] = dataframe['bb_mid'] - 2 * dataframe['bb_std']

        dataframe['r_14'] = williams_r(dataframe, 14)
        dataframe['vol_ma'] = dataframe['volume'].rolling(20).mean()

        ema13 = dataframe['close'].ewm(span=13).mean()
        dataframe['sroc'] = ema13.pct_change(21) * 100

        dataframe['funding_rate'] = 0.0
        try:
            fr = self.dp.get_pair_dataframe(
                pair=metadata.get('pair', ''), timeframe='1h', candle_type='funding_rate'
            )
            if fr is not None and len(fr) > 0:
                fr = fr[['date', 'open']].copy()
                fr.columns = ['date', 'funding_rate']
                dataframe = merge_informative_pair(dataframe, fr, self.timeframe, '1h', ffill=True)
                if 'funding_rate_1h' in dataframe.columns:
                    dataframe['funding_rate'] = dataframe['funding_rate_1h']
        except Exception:
            pass

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        in_macro_bear = dataframe['close'] < dataframe['sma200_1d']
        in_macro_bull = dataframe['close'] > dataframe['sma200_1d']

        in_downtrend_4h = dataframe['close'] < dataframe['sma50_4h'] * (1 - self.trend_margin.value)
        below_sma50_4h = dataframe['close'] < dataframe['sma50_4h']

        low_volatility = dataframe['atr_pct'] < self.atr_max_pct.value
        vol_ok = dataframe['volume'] > dataframe['vol_ma'] * self.vol_mult.value
        no_neg_funding = dataframe['funding_rate'] >= -0.001

        rsi_peaked = (
            (dataframe['rsi'].shift(2) >= self.rsi_short_peak.value) &
            (dataframe['rsi'].shift(1) < self.rsi_short_peak.value) &
            (dataframe['rsi'] < dataframe['rsi'].shift(1))
        )
        enter_short = (
            in_macro_bear &
            in_downtrend_4h &
            rsi_peaked &
            (dataframe['close'] < dataframe['close'].shift(1)) &
            low_volatility &
            vol_ok &
            no_neg_funding
        )

        bb_was_touched = (
            (dataframe['close'] <= dataframe['bb_lower'] * self.bb_long_factor.value) |
            (dataframe['close'].shift(1) <= dataframe['bb_lower'].shift(1) * self.bb_long_factor.value)
        )
        rsi_rising = dataframe['rsi'] > dataframe['rsi'].shift(1)
        green_candle = dataframe['close'] > dataframe['open']

        enter_long = (
            in_macro_bull &
            below_sma50_4h &
            bb_was_touched &
            (dataframe['rsi'] <= self.rsi_long_confirm.value) &
            rsi_rising &
            green_candle &
            low_volatility &
            vol_ok
        )

        dataframe.loc[enter_long, 'enter_long'] = 1
        dataframe.loc[enter_short, 'enter_short'] = 1
        dataframe.loc[enter_long, 'enter_tag'] = 'long_confirmed_reversal'
        dataframe.loc[enter_short, 'enter_tag'] = 'short_bear_peak'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Long exit: price breaks 1% below BB_lower = reversal fallito
        dataframe.loc[
            dataframe['close'] < dataframe['bb_lower'] * self.bb_fail_factor,
            'exit_long'
        ] = 1

        # Short exit: RSI recovered = falso picco
        dataframe.loc[
            dataframe['rsi'] > self.rsi_short_peak.value + 3,
            'exit_short'
        ] = 1

        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float:
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value

        # === TIME-BASED EARLY EXIT ===
        # Durante le prime N ore: stop stretto per validare il setup
        # Se prezzo scende > early_exit_stop% → setup fallito → exit rapido
        trade_age_hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        if trade_age_hours <= self.early_exit_hours:
            if current_profit < self.early_exit_stop:
                return stoploss_from_open(
                    self.early_exit_stop, current_profit,
                    is_short=trade.is_short, leverage=trade.leverage
                )

        # === STANDARD CUSTOM STOPLOSS (da 3h in poi) ===
        if current_profit > PF_2:
            sl_profit = SL_2 + (current_profit - PF_2)
        elif current_profit > PF_1:
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            sl_profit = HSL

        # SROC bailout
        if current_profit < -0.02:
            try:
                df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
                if not df.empty and df.iloc[-1].get('sroc', 0) < -3.0:
                    return stoploss_from_open(0.01, current_profit,
                                              is_short=trade.is_short,
                                              leverage=trade.leverage)
            except Exception:
                pass

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

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float,
                 entry_tag: Optional[str], side: str, **kwargs) -> float:
        return 2.0

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: Optional[float],
                            max_stake: float, leverage: float, entry_tag: Optional[str],
                            side: str, **kwargs) -> float:
        return max_stake / self.config.get('max_open_trades', 4)
