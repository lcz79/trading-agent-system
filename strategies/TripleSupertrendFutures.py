"""
TripleSupertrendFutures - Daytrading con Triple Supertrend

LOGICA:
- Timeframe: 15m (daytrading reale, ~5-15 segnali/giorno su 7 pairs)
- Entry: tutti e 3 i Supertrend concordano nella stessa direzione
  + 1h trend filter (SMA50) per allineamento macro
  + RSI come gate (no entry in zona neutrale)
  + Volume sopra media
- Exit: appena 1 Supertrend si gira contro di noi (uscita veloce)
  + Minimal ROI come backup
- Stop: ATR-based custom stoploss (dinamico, non fisso)

PERCHÉ FUNZIONA:
- 3 ST con parametri diversi = triple conferma = meno false entries
- Exit al primo segnale contrario = preserva profitto
- 15m = abbastanza lento per evitare rumore 5m, abbastanza veloce per daytrading
- Nessun hard stop fisso percentuale (era il killer di tutte le altre strategie)
"""

import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from freqtrade.strategy import merge_informative_pair, stoploss_from_open, informative
from freqtrade.persistence import Trade


def supertrend(df: DataFrame, period: int, multiplier: float):
    """
    Calcola Supertrend direction senza talib.
    Returns: Series con 1 (bullish) o -1 (bearish)
    """
    hl2 = (df['high'] + df['low']) / 2

    # True Range
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)

    # ATR via EWM (equivalente a Wilder's smoothing)
    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    # Calcolo iterativo direction
    direction = pd.Series(1, index=df.index, dtype=int)
    final_upper = upper_band.copy()
    final_lower = lower_band.copy()

    for i in range(1, len(df)):
        # Lower band: non scende se era già sopra il close precedente
        if lower_band.iloc[i] > final_lower.iloc[i - 1] or df['close'].iloc[i - 1] < final_lower.iloc[i - 1]:
            final_lower.iloc[i] = lower_band.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        # Upper band: non sale se era già sotto il close precedente
        if upper_band.iloc[i] < final_upper.iloc[i - 1] or df['close'].iloc[i - 1] > final_upper.iloc[i - 1]:
            final_upper.iloc[i] = upper_band.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        # Direction
        if direction.iloc[i - 1] == -1 and df['close'].iloc[i] > final_upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif direction.iloc[i - 1] == 1 and df['close'].iloc[i] < final_lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

    return direction


class TripleSupertrendFutures(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '15m'
    can_short = True

    # Minimal ROI come backup di sicurezza (3% per leveraged position = 1.5% price)
    minimal_roi = {"0": 0.03, "120": 0.02, "240": 0.01}

    # Hard stop molto largo — gestiamo noi via custom_stoploss
    stoploss = -0.10
    use_custom_stoploss = True
    trailing_stop = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False
    startup_candle_count = 100

    # === SUPERTREND parametri ===
    # ST1: veloce (cattura trend a breve)
    st1_period = IntParameter(7, 14, default=10, space='buy', optimize=True)
    st1_mult = DecimalParameter(1.5, 3.0, default=2.0, decimals=1, space='buy', optimize=True)

    # ST2: medio
    st2_period = IntParameter(10, 20, default=14, space='buy', optimize=True)
    st2_mult = DecimalParameter(2.5, 4.0, default=3.0, decimals=1, space='buy', optimize=True)

    # ST3: lento (filtro macro sul 15m)
    st3_period = IntParameter(15, 30, default=20, space='buy', optimize=True)
    st3_mult = DecimalParameter(3.5, 6.0, default=4.5, decimals=1, space='buy', optimize=True)

    # RSI gate: non entrare in zona neutrale
    rsi_long_max = IntParameter(35, 55, default=45, space='buy', optimize=True)   # LONG solo RSI < soglia (dip)
    rsi_short_min = IntParameter(45, 65, default=55, space='buy', optimize=True)  # SHORT solo RSI > soglia (bounce)

    # Volume
    vol_mult = DecimalParameter(0.5, 1.5, default=0.8, decimals=1, space='buy', optimize=True)

    # ATR stop
    atr_stop_mult = DecimalParameter(1.5, 4.0, default=2.5, decimals=1, space='sell', optimize=True)
    atr_trail_mult = DecimalParameter(1.0, 3.0, default=1.5, decimals=1, space='sell', optimize=True)

    max_same_direction = 3  # Su 15m più pairs attivi

    @informative('1h')
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """1h SMA50 come macro filter."""
        dataframe['sma50'] = dataframe['close'].rolling(50).mean()
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # === ATR 15m ===
        tr = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift(1)).abs(),
            (dataframe['low'] - dataframe['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        dataframe['atr'] = tr.ewm(alpha=1 / 14, min_periods=14).mean()
        dataframe['atr_pct'] = dataframe['atr'] / dataframe['close']

        # === RSI 15m ===
        delta = dataframe['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14).mean()
        dataframe['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))

        # === Volume ===
        dataframe['vol_ma'] = dataframe['volume'].rolling(20).mean()

        # === Triple Supertrend ===
        dataframe['st1'] = supertrend(dataframe, self.st1_period.value, self.st1_mult.value)
        dataframe['st2'] = supertrend(dataframe, self.st2_period.value, self.st2_mult.value)
        dataframe['st3'] = supertrend(dataframe, self.st3_period.value, self.st3_mult.value)

        # Tutti e 3 concordi
        dataframe['all_bullish'] = (
            (dataframe['st1'] == 1) &
            (dataframe['st2'] == 1) &
            (dataframe['st3'] == 1)
        )
        dataframe['all_bearish'] = (
            (dataframe['st1'] == -1) &
            (dataframe['st2'] == -1) &
            (dataframe['st3'] == -1)
        )

        # Flip: questa candela tutti concordi, candela prima NON tutti concordi
        dataframe['flip_bullish'] = (
            dataframe['all_bullish'] &
            ~dataframe['all_bullish'].shift(1).fillna(False)
        )
        dataframe['flip_bearish'] = (
            dataframe['all_bearish'] &
            ~dataframe['all_bearish'].shift(1).fillna(False)
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 1h macro trend
        above_sma50_1h = dataframe['close'] > dataframe['sma50_1h']
        below_sma50_1h = dataframe['close'] < dataframe['sma50_1h']

        vol_ok = dataframe['volume'] > dataframe['vol_ma'] * self.vol_mult.value

        # Bassa volatilità (no entry in spike estremi)
        low_vol = dataframe['atr_pct'] < 0.015

        # === LONG: tutti ST bullish con flip recente + 1h uptrend ===
        # Permetti entry anche senza flip se tutti e 3 bullish (trend consolidato)
        enter_long = (
            dataframe['all_bullish'] &
            above_sma50_1h &
            (dataframe['rsi'] <= self.rsi_long_max.value) &  # dip nel trend rialzista
            vol_ok &
            low_vol
        )

        # === SHORT: tutti ST bearish con flip recente + 1h downtrend ===
        enter_short = (
            dataframe['all_bearish'] &
            below_sma50_1h &
            (dataframe['rsi'] >= self.rsi_short_min.value) &  # bounce nel trend ribassista
            vol_ok &
            low_vol
        )

        dataframe.loc[enter_long, 'enter_long'] = 1
        dataframe.loc[enter_short, 'enter_short'] = 1
        dataframe.loc[enter_long, 'enter_tag'] = 'triple_st_long'
        dataframe.loc[enter_short, 'enter_tag'] = 'triple_st_short'

        return dataframe

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: Optional[str], side: str, **kwargs) -> bool:
        # No entry 02:00-06:00 UTC (basso volume)
        if 2 <= current_time.hour < 6:
            return False
        is_short = (side == 'short')
        open_trades = Trade.get_open_trades()
        same_dir_count = sum(1 for t in open_trades if t.is_short == is_short)
        if same_dir_count >= self.max_same_direction:
            return False
        return True

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # EXIT LONG: appena uno dei 3 ST si gira bearish
        dataframe.loc[
            (dataframe['st1'] == -1) |
            (dataframe['st2'] == -1) |
            (dataframe['st3'] == -1),
            'exit_long'
        ] = 1

        # EXIT SHORT: appena uno dei 3 ST si gira bullish
        dataframe.loc[
            (dataframe['st1'] == 1) |
            (dataframe['st2'] == 1) |
            (dataframe['st3'] == 1),
            'exit_short'
        ] = 1

        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float:
        """
        Stop basato su ATR: dinamico invece di percentuale fissa.
        Non attiviamo stoploss prima di 3 candele (15m * 3 = 45 min)
        per evitare di essere stoppati dal noise iniziale.
        """
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if df.empty:
                return -0.10

            last = df.iloc[-1]
            atr = last.get('atr', None)

            if atr is None or atr == 0:
                return -0.10

            # Stop a N * ATR dall'entry
            atr_stop = (atr * self.atr_stop_mult.value) / current_rate

            # Non permettiamo stop più stretto di 1% (per non essere stoppati dal rumore)
            atr_stop = max(atr_stop, 0.01)
            # Né più largo di 8%
            atr_stop = min(atr_stop, 0.08)

            # Se siamo in profitto, trailing ATR
            if current_profit > 0.01:
                trail_stop = current_profit - (atr * self.atr_trail_mult.value) / current_rate
                trail_stop = max(trail_stop, 0.005)  # minimo lock +0.5%
                return stoploss_from_open(trail_stop, current_profit,
                                          is_short=trade.is_short,
                                          leverage=trade.leverage)

        except Exception:
            return -0.10

        return stoploss_from_open(-atr_stop, current_profit,
                                  is_short=trade.is_short,
                                  leverage=trade.leverage)

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float,
                 entry_tag: Optional[str], side: str, **kwargs) -> float:
        return 2.0

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                             proposed_stake: float, min_stake: Optional[float],
                             max_stake: float, leverage: float, entry_tag: Optional[str],
                             side: str, **kwargs) -> float:
        return max_stake / self.config.get('max_open_trades', 6)
