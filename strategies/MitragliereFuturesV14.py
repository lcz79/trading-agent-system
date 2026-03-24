"""
MitragliereFutures v14 - Trend Following (approccio completamente nuovo)

INSIGHT CRITICO da 3 anni di backtesting:
- Mercato: +265.89% in 3 anni
- Mean-reversion con filtri stretti: +0.41% su 29 trade
- Short: sempre net negative in bull market
- Il problema NON è il risk management, è l'APPROCCIO: comprare dip in un trend
  che sale del 266% con target +3% = massimi profitti di 3% mentre rischi grandi perdite

NUOVO APPROCCIO: Trend Following
- Entra quando il prezzo ROMPE sopra SMA50_4h in macro bull (momentum)
- Escil quando il prezzo torna SOTTO SMA50_4h (trend finisce)
- Nessun target fisso: lascia correre il trend

ATTESO in 2023-2024 bull: trade che durano settimane/mesi, catturando +20-50% moves
ATTESO in 2025 bear: nessun long (sotto sma200_1d), pochi short in confirmed downtrend

ENTRY:
- LONG: fresh cross sopra sma50_4h (ieri sotto, oggi sopra) AND close > sma200_1d
  AND RSI > 50 (momentum già positivo) AND ATR < 2% (non troppo volatile)
- SHORT: fresh cross sotto sma50_4h AND close < sma200_1d 
  AND RSI < 50 AND ATR < 2%

EXIT:
- LONG: close < sma50_4h * 0.98 (crossed back below with margin) OR close < sma200_1d
- SHORT: close > sma50_4h * 1.02 OR close > sma200_1d

STOP: trailing stop 3% dal peak (non fixed, per lasciare correre)
"""
import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from freqtrade.strategy import merge_informative_pair, stoploss_from_open, informative
from freqtrade.persistence import Trade


class MitragliereFuturesV14(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True
    # No fixed ROI - let trends run
    minimal_roi = {"0": 100.0}
    stoploss = -0.10               # Hard floor: -5% price con 2x (ampio per trend following)
    use_custom_stoploss = False    # No custom stoploss: usiamo trailing stop
    trailing_stop = True
    trailing_stop_positive = 0.03  # Se profitto > offset, trail a 3% dal peak
    trailing_stop_positive_offset = 0.05  # Inizia a trailing da +5% profit
    trailing_only_offset_is_reached = True  # Non traila finché non > 5%
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False
    startup_candle_count = 0

    # Parametri entry
    trend_margin = DecimalParameter(0.00, 0.02, default=0.005, decimals=3, space='buy', optimize=True)
    rsi_long_min = IntParameter(45, 65, default=50, space='buy', optimize=True)
    rsi_short_max = IntParameter(35, 55, default=50, space='buy', optimize=True)
    atr_max_pct = DecimalParameter(0.008, 0.025, default=0.018, decimals=3, space='buy', optimize=True)
    vol_mult = DecimalParameter(0.5, 2.0, default=0.8, decimals=1, space='buy', optimize=True)

    # Exit margin
    exit_margin = DecimalParameter(0.01, 0.05, default=0.02, decimals=2, space='sell', optimize=True)

    max_same_direction = 2

    @informative('4h')
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sma50'] = dataframe['close'].rolling(50).mean()
        return dataframe

    @informative('1d')
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ATR
        tr = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift()).abs(),
            (dataframe['low'] - dataframe['close'].shift()).abs()
        ], axis=1).max(axis=1)
        dataframe['atr'] = tr.ewm(alpha=1/14, min_periods=14).mean()
        dataframe['atr_pct'] = dataframe['atr'] / dataframe['close']

        # RSI
        delta = dataframe['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
        dataframe['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))

        # Volume media
        dataframe['vol_ma'] = dataframe['volume'].rolling(20).mean()

        # Funding rate
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
        # Macro regime
        in_macro_bull = dataframe['close'] > dataframe['sma200_1d']
        in_macro_bear = dataframe['close'] < dataframe['sma200_1d']

        # Fresh cross sopra/sotto sma50_4h
        sma50_4h = dataframe['sma50_4h']
        crossed_above_4h = (
            (dataframe['close'].shift(1) < sma50_4h.shift(1)) &
            (dataframe['close'] > sma50_4h * (1 + self.trend_margin.value))
        )
        crossed_below_4h = (
            (dataframe['close'].shift(1) > sma50_4h.shift(1)) &
            (dataframe['close'] < sma50_4h * (1 - self.trend_margin.value))
        )

        low_volatility = dataframe['atr_pct'] < self.atr_max_pct.value
        vol_ok = dataframe['volume'] > dataframe['vol_ma'] * self.vol_mult.value
        no_neg_funding = dataframe['funding_rate'] >= -0.001

        # LONG: breakout sopra sma50_4h in macro bull
        enter_long = (
            in_macro_bull &
            crossed_above_4h &
            (dataframe['rsi'] > self.rsi_long_min.value) &
            low_volatility &
            vol_ok
        )

        # SHORT: breakdown sotto sma50_4h in macro bear
        enter_short = (
            in_macro_bear &
            crossed_below_4h &
            (dataframe['rsi'] < self.rsi_short_max.value) &
            low_volatility &
            vol_ok &
            no_neg_funding
        )

        dataframe.loc[enter_long, 'enter_long'] = 1
        dataframe.loc[enter_short, 'enter_short'] = 1
        dataframe.loc[enter_long, 'enter_tag'] = 'long_breakout'
        dataframe.loc[enter_short, 'enter_tag'] = 'short_breakdown'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        sma50_4h = dataframe['sma50_4h']

        # Exit LONG: prezzo torna sotto sma50_4h con margin, O macro bear
        dataframe.loc[
            (dataframe['close'] < sma50_4h * (1 - self.exit_margin.value)) |
            (dataframe['close'] < dataframe['sma200_1d'] * 0.98),
            'exit_long'
        ] = 1

        # Exit SHORT: prezzo torna sopra sma50_4h con margin, O macro bull
        dataframe.loc[
            (dataframe['close'] > sma50_4h * (1 + self.exit_margin.value)) |
            (dataframe['close'] > dataframe['sma200_1d'] * 1.02),
            'exit_short'
        ] = 1

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

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float,
                 entry_tag: Optional[str], side: str, **kwargs) -> float:
        return 2.0

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: Optional[float],
                            max_stake: float, leverage: float, entry_tag: Optional[str],
                            side: str, **kwargs) -> float:
        return max_stake / self.config.get('max_open_trades', 4)
