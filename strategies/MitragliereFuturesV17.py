"""
MitragliereFutures v17 - Macro Trend Rider

RESET COMPLETO. Tutte le versioni precedenti erano sbagliate per lo stesso motivo:
market timing su 1h in un mercato che fa +265% in 3 anni.

VERITÀ MATEMATICA:
- Buy & hold BTC con 2x leva: +530% in 3 anni
- Le nostre strategie intelligenti: da -28% a +1.63%

Il problema non era il risk management, era l'IDEA DI BASE:
comprare e vendere ogni poche ore in un mercato che sale per anni.

NUOVO APPROCCIO: Macro Trend Rider
1. Entra LONG quando il macro trend è confermato bullish
2. Tieni la posizione per GIORNI/SETTIMANE mentre il trend dura
3. Trailing stop WIDE che non reagisce al normale rumore 1h

ENTRY (qualità > frequenza):
- close > sma200_1d (macro bull confermato)
- Prezzo appena sopra sma50_4h (fresh uptrend 4h)
- RSI 4h > 50 (momentum positivo)
- ATR basso (non in un crash/pump violento)

EXIT:
- Trailing stop: 6% dal picco dopo 5% di profitto
  → In un bull run da +50%, esci a +44% (eccellente)
  → In un falso segnale con -10%: hard stop

- Hard stop: -10% (5% price move con 2x) → protezione assoluta

ATTESO su 3 anni 2023-2026:
- 2023-2024 bull: poche entry (qualità), hold per settimane, +30-60% per trade
- 2025-2026 bear: nessun long (sotto sma200_1d), pochi short in downtrend confermato
"""
import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from freqtrade.strategy import merge_informative_pair, stoploss_from_open, informative
from freqtrade.persistence import Trade


class MitragliereFuturesV17(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True
    minimal_roi = {"0": 100}       # Nessun ROI fisso: il trailing stop gestisce tutto
    stoploss = -0.10               # Hard floor: -5% price con 2x leva
    use_custom_stoploss = False    # Trailing stop nativo di freqtrade (più robusto)
    trailing_stop = True
    trailing_stop_positive = 0.04  # Dopo aver guadagnato 5%+, trail a 6% dal picco
    trailing_stop_positive_offset = 0.05  # Inizia a trailing da +5% profit
    trailing_only_offset_is_reached = True
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False
    startup_candle_count = 200

    # Entry parameters
    trend_margin = DecimalParameter(0.00, 0.02, default=0.005, decimals=3, space='buy', optimize=True)
    atr_max_pct = DecimalParameter(0.010, 0.030, default=0.018, decimals=3, space='buy', optimize=True)
    vol_mult = DecimalParameter(0.3, 1.5, default=0.5, decimals=1, space='buy', optimize=True)
    rsi_long_min = IntParameter(40, 60, default=50, space='buy', optimize=True)
    rsi_short_max = IntParameter(40, 60, default=50, space='buy', optimize=True)

    max_same_direction = 3

    @informative('4h')
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sma50'] = dataframe['close'].rolling(50).mean()
        dataframe['rsi'] = self._compute_rsi(dataframe)
        return dataframe

    def _compute_rsi(self, df, period=14):
        delta = df['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/period, min_periods=period).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/period, min_periods=period).mean()
        return 100 - (100 / (1 + gain / (loss + 1e-9)))

    @informative('1d')
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()
        dataframe['sma50'] = dataframe['close'].rolling(50).mean()
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ATR 1h
        tr = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift()).abs(),
            (dataframe['low'] - dataframe['close'].shift()).abs()
        ], axis=1).max(axis=1)
        dataframe['atr'] = tr.ewm(alpha=1/14, min_periods=14).mean()
        dataframe['atr_pct'] = dataframe['atr'] / dataframe['close']

        # RSI 1h
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

        # 4h trend confermato
        above_sma50_4h = dataframe['close'] > dataframe['sma50_4h'] * (1 + self.trend_margin.value)
        below_sma50_4h = dataframe['close'] < dataframe['sma50_4h'] * (1 - self.trend_margin.value)

        # Fresh signal: era sotto sma50_4h nelle ultime 12h, ora sopra (recente breakout)
        was_below_4h = dataframe['close'].shift(12) < dataframe['sma50_4h'].shift(12)
        was_above_4h = dataframe['close'].shift(12) > dataframe['sma50_4h'].shift(12)

        # RSI 4h > soglia (momentum confermato)
        rsi_4h_bull = dataframe['rsi_4h'] > self.rsi_long_min.value
        rsi_4h_bear = dataframe['rsi_4h'] < self.rsi_short_max.value

        low_volatility = dataframe['atr_pct'] < self.atr_max_pct.value
        vol_ok = dataframe['volume'] > dataframe['vol_ma'] * self.vol_mult.value
        no_neg_funding = dataframe['funding_rate'] >= -0.001

        # LONG: macro bull + 4h breakout confermato + momentum positivo
        # Entry su fresh cross sopra sma50_4h in macro bull
        enter_long = (
            in_macro_bull &
            above_sma50_4h &
            was_below_4h &       # era sotto 12h fa = fresh uptrend
            rsi_4h_bull &        # RSI 4h positivo
            low_volatility &
            vol_ok
        )

        # SHORT: macro bear + 4h breakdown confermato + momentum negativo
        enter_short = (
            in_macro_bear &
            below_sma50_4h &
            was_above_4h &       # era sopra 12h fa = fresh downtrend
            rsi_4h_bear &
            low_volatility &
            vol_ok &
            no_neg_funding
        )

        dataframe.loc[enter_long, 'enter_long'] = 1
        dataframe.loc[enter_short, 'enter_short'] = 1
        dataframe.loc[enter_long, 'enter_tag'] = 'long_trend'
        dataframe.loc[enter_short, 'enter_tag'] = 'short_trend'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit LONG: macro turn (sotto sma200_1d)
        dataframe.loc[
            dataframe['close'] < dataframe['sma200_1d'] * 0.97,
            'exit_long'
        ] = 1

        # Exit SHORT: macro turn (sopra sma200_1d)
        dataframe.loc[
            dataframe['close'] > dataframe['sma200_1d'] * 1.03,
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
