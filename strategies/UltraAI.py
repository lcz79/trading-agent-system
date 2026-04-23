"""
UltraAI - Multi-Layer AI Trading Strategy

Architettura a 5 layer:
  Layer 1: Regime Detection (ADX + Bollinger Width + MA Slope)
           → sideways = no entry, bull = long ok, bear = short ok
  Layer 2: FreqAI LightGBM prediction
           → composite target = return × regime_weight × vol_adj
           → DI_threshold filtra outlier (dati anomali = no trade)
  Layer 3: LLM Signal (producer esterno via file JSON)
           → Claude analizza news + indicatori ogni ora
           → degradazione graceful se file non disponibile
  Layer 4: Confluenza tecnica
           → Supertrend x3 (periodi diversi) devono concordare
           → RSI in zona valida
           → Volume sopra media
  Layer 5: Limit entry su pullback + Trailing stop

Config richiesta: config_freqai.json
LLM producer: llm_producer/producer.py (servizio separato)
"""

import json
import os
import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime, timezone
from typing import Optional
from functools import reduce

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from freqtrade.persistence import Trade


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def calc_atr(df: DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def calc_supertrend(df: DataFrame, period: int = 7, multiplier: float = 3.0) -> pd.Series:
    """Supertrend vectorizzato. Ritorna Serie con 1=uptrend, -1=downtrend."""
    high = df['high'].values.copy()
    low = df['low'].values.copy()
    close = df['close'].values.copy()
    n = len(close)

    # ATR con EWM
    tr = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - np.concatenate([[close[0]], close[:-1]])),
            np.abs(low - np.concatenate([[close[0]], close[:-1]]))
        )
    )
    alpha = 1 / period
    atr = np.zeros(n)
    atr[0] = tr[0]
    for i in range(1, n):
        atr[i] = tr[i] * alpha + atr[i - 1] * (1 - alpha)

    hl2 = (high + low) / 2
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    final_upper = upper.copy()
    final_lower = lower.copy()
    direction = np.zeros(n)

    for i in range(1, n):
        final_upper[i] = upper[i] if (upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]) else final_upper[i - 1]
        final_lower[i] = lower[i] if (lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]) else final_lower[i - 1]

        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

    return pd.Series(direction, index=df.index)


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, min_periods=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, min_periods=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def resample_to_4h(df: DataFrame) -> DataFrame:
    df = df.copy().set_index('date')
    r = df.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum'
    }).dropna()
    r.index.name = 'date'
    return r.reset_index()


def load_llm_signal(pair: str, signal_file: str) -> float:
    """Legge il segnale LLM dal file JSON. Ritorna 1=long, -1=short, 0=neutral."""
    try:
        if not os.path.exists(signal_file):
            return 0.0
        with open(signal_file, 'r') as f:
            signals = json.load(f)
        data = signals.get(pair, {})
        # Scarta segnali più vecchi di 2 ore
        ts = datetime.fromisoformat(data.get('timestamp', '2000-01-01T00:00:00+00:00'))
        if (datetime.now(timezone.utc) - ts).total_seconds() > 7200:
            return 0.0
        return float(data.get('signal', 0.0))
    except Exception:
        return 0.0


# ─────────────────────────────────────────────
# Strategy
# ─────────────────────────────────────────────

class UltraAI(IStrategy):
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
    use_custom_stoploss = False

    trailing_stop = True
    trailing_stop_positive = 0.04
    trailing_stop_positive_offset = 0.08
    trailing_only_offset_is_reached = True

    ignore_roi_if_entry_signal = True
    position_adjustment_enable = False
    startup_candle_count = 300

    # Parametri ottimizzabili
    buy_threshold = DecimalParameter(0.01, 0.05, default=0.02, decimals=2, space='buy', optimize=True)
    sell_threshold = DecimalParameter(-0.05, -0.01, default=-0.02, decimals=2, space='sell', optimize=True)
    adx_trend_min = IntParameter(20, 35, default=25, space='buy', optimize=True)
    pullback_ratio = DecimalParameter(0.2, 0.6, default=0.4, decimals=1, space='buy', optimize=True)

    use_macro_filter = True
    use_llm_filter = True
    max_same_direction = 3

    LLM_SIGNAL_FILE = '/freqtrade/user_data/llm_signals.json'

    # ── FreqAI feature engineering ──────────────────

    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int,
                                        metadata: dict, **kwargs) -> DataFrame:
        """Feature espanse per ogni periodo e timeframe."""
        dataframe['%rsi'] = calc_rsi(dataframe['close'], period)
        dataframe['%atr'] = calc_atr(dataframe, period)
        dataframe['%atr_pct'] = dataframe['%atr'] / dataframe['close']

        # Bollinger Bands
        bb_mid = dataframe['close'].rolling(period).mean()
        bb_std = dataframe['close'].rolling(period).std()
        dataframe['%bb_upper'] = (bb_mid + 2 * bb_std - dataframe['close']) / dataframe['close']
        dataframe['%bb_lower'] = (dataframe['close'] - (bb_mid - 2 * bb_std)) / dataframe['close']
        dataframe['%bb_width'] = (4 * bb_std) / bb_mid

        # Momentum
        dataframe['%roc'] = dataframe['close'].pct_change(period)
        dataframe['%mom'] = dataframe['close'] - dataframe['close'].shift(period)

        # EMA ratio
        ema = dataframe['close'].ewm(span=period, adjust=False).mean()
        dataframe['%ema_ratio'] = dataframe['close'] / ema - 1

        # Stochastic
        lowest = dataframe['low'].rolling(period).min()
        highest = dataframe['high'].rolling(period).max()
        dataframe['%stoch_k'] = (dataframe['close'] - lowest) / (highest - lowest + 1e-9) * 100

        return dataframe

    def feature_engineering_expand_basic(self, dataframe: DataFrame,
                                          metadata: dict, **kwargs) -> DataFrame:
        """Feature base senza espansione."""
        dataframe['%pct_change'] = dataframe['close'].pct_change()
        dataframe['%volume_change'] = dataframe['volume'].pct_change()
        dataframe['%hl_ratio'] = (dataframe['high'] - dataframe['low']) / dataframe['close']
        dataframe['%close_raw'] = dataframe['close']
        dataframe['%volume_raw'] = dataframe['volume']

        # OBV
        obv = (np.sign(dataframe['close'].diff()) * dataframe['volume']).fillna(0).cumsum()
        dataframe['%obv_change'] = obv.pct_change(5)

        return dataframe

    def feature_engineering_standard(self, dataframe: DataFrame,
                                      metadata: dict, **kwargs) -> DataFrame:
        """Feature temporali e cross-pair (chiamata una volta)."""
        dataframe['%hour'] = dataframe['date'].dt.hour
        dataframe['%day_of_week'] = dataframe['date'].dt.dayofweek
        dataframe['%is_weekend'] = (dataframe['%day_of_week'] >= 5).astype(int)

        # MACD
        ema12 = dataframe['close'].ewm(span=12, adjust=False).mean()
        ema26 = dataframe['close'].ewm(span=26, adjust=False).mean()
        dataframe['%macd'] = (ema12 - ema26) / dataframe['close']
        dataframe['%macd_signal'] = dataframe['%macd'].ewm(span=9, adjust=False).mean()
        dataframe['%macd_hist'] = dataframe['%macd'] - dataframe['%macd_signal']

        # ADX (semplificato)
        plus_dm = dataframe['high'].diff().clip(lower=0)
        minus_dm = (-dataframe['low'].diff()).clip(lower=0)
        atr14 = calc_atr(dataframe, 14)
        plus_di = 100 * plus_dm.ewm(alpha=1/14).mean() / atr14
        minus_di = 100 * minus_dm.ewm(alpha=1/14).mean() / atr14
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
        dataframe['%adx'] = dx.ewm(alpha=1/14).mean()
        dataframe['%plus_di'] = plus_di
        dataframe['%minus_di'] = minus_di

        # Regime (1=bull, -1=bear, 0=sideways)
        sma50 = dataframe['close'].rolling(50).mean()
        sma200 = dataframe['close'].rolling(200).mean()
        bb_width = dataframe['close'].rolling(20).std() * 4 / dataframe['close'].rolling(20).mean()
        regime = np.where(
            (dataframe['%adx'] < 20) | (bb_width < 0.03), 0,   # sideways
            np.where(dataframe['close'] > sma50, 1, -1)          # bull/bear
        )
        dataframe['%regime'] = regime

        # 4h context (resample)
        df_4h = resample_to_4h(dataframe)
        df_4h['%rsi_4h'] = calc_rsi(df_4h['close'], 14)
        df_4h['%trend_4h'] = np.where(
            df_4h['close'] > df_4h['close'].ewm(span=21, adjust=False).mean(), 1, -1
        )
        df_4h = df_4h[['date', '%rsi_4h', '%trend_4h']].rename(
            columns={'%rsi_4h': 'pct_rsi_4h', '%trend_4h': 'pct_trend_4h'}
        )
        dataframe = pd.merge_asof(
            dataframe.sort_values('date'),
            df_4h.sort_values('date'),
            on='date', direction='backward'
        )
        dataframe['%rsi_4h'] = dataframe.get('pct_rsi_4h', 50)
        dataframe['%trend_4h'] = dataframe.get('pct_trend_4h', 0)
        dataframe.drop(columns=['pct_rsi_4h', 'pct_trend_4h'], errors='ignore', inplace=True)

        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """
        Target composito = future_return × regime_weight × vol_weight
        Il modello impara a prevedere non solo la direzione ma anche la qualità del move.
        """
        label_period = self.freqai_info['feature_parameters'].get('label_period_candles', 24)

        # Return futuro
        future_return = dataframe['close'].shift(-label_period) / dataframe['close'] - 1

        # Peso regime: muove in trend = segnale più forte
        adx_norm = (dataframe['%adx'].clip(0, 60) / 60) if '%adx' in dataframe else 0.5

        # Peso volatilità: normalizza per ATR
        atr_norm = calc_atr(dataframe, 14) / dataframe['close']
        vol_weight = 1 / (atr_norm.clip(0.001, 0.05) / 0.02)  # normalizza intorno a 2% ATR

        dataframe['&-target'] = future_return * (1 + adx_norm) * vol_weight.clip(0.5, 2.0)

        return dataframe

    # ── Indicatori principali ────────────────────────

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # FreqAI: genera predizioni ML
        dataframe = self.freqai.start(dataframe, metadata, self)

        # Supertrend x3 (periodi/multipli diversi per consenso)
        dataframe['st_fast'] = calc_supertrend(dataframe, period=7, multiplier=2.0)
        dataframe['st_mid'] = calc_supertrend(dataframe, period=10, multiplier=3.0)
        dataframe['st_slow'] = calc_supertrend(dataframe, period=14, multiplier=4.0)

        # Consenso Supertrend (-3 a +3)
        dataframe['st_consensus'] = (
            dataframe['st_fast'] + dataframe['st_mid'] + dataframe['st_slow']
        )

        # RSI 1h
        dataframe['rsi'] = calc_rsi(dataframe['close'], 14)

        # Volume sopra media
        dataframe['vol_ok'] = dataframe['volume'] > dataframe['volume'].rolling(20).mean() * 0.8

        # SMA200 per macro filter
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()

        # Regime da feature engineering (o ricalcolato)
        if '%regime' not in dataframe.columns:
            sma50 = dataframe['close'].rolling(50).mean()
            plus_dm = dataframe['high'].diff().clip(lower=0)
            minus_dm = (-dataframe['low'].diff()).clip(lower=0)
            atr14 = calc_atr(dataframe, 14)
            plus_di = 100 * plus_dm.ewm(alpha=1/14).mean() / atr14
            minus_di = 100 * minus_dm.ewm(alpha=1/14).mean() / atr14
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
            adx = dx.ewm(alpha=1/14).mean()
            dataframe['%regime'] = np.where(adx < self.adx_trend_min.value, 0,
                                             np.where(dataframe['close'] > sma50, 1, -1))

        # ATR per limit price
        dataframe['atr_1h'] = calc_atr(dataframe, 14)

        return dataframe

    # ── Entry ────────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata['pair']

        # ML: predizione e qualità
        ml_long = (
            (dataframe['do_predict'] == 1) &
            (dataframe['&-target'] > self.buy_threshold.value)
        )
        ml_short = (
            (dataframe['do_predict'] == 1) &
            (dataframe['&-target'] < self.sell_threshold.value)
        )

        # Regime: no trade in sideways
        regime_long = dataframe['%regime'] >= 1
        regime_short = dataframe['%regime'] <= -1

        # Supertrend: tutti e 3 concordano
        st_long = dataframe['st_consensus'] == 3
        st_short = dataframe['st_consensus'] == -3

        # RSI: non in zona esaurita
        rsi_ok_long = dataframe['rsi'] < 70
        rsi_ok_short = dataframe['rsi'] > 30

        # Volume
        vol = dataframe['vol_ok']

        # Segnale base
        long_signal = ml_long & regime_long & st_long & rsi_ok_long & vol
        short_signal = ml_short & regime_short & st_short & rsi_ok_short & vol

        # Macro filter (SMA200)
        if self.use_macro_filter:
            long_signal = long_signal & (dataframe['close'] > dataframe['sma200'])
            short_signal = short_signal & (dataframe['close'] < dataframe['sma200'])

        # LLM filter (opzionale — se il file non esiste, passa tutto)
        if self.use_llm_filter:
            llm_sig = load_llm_signal(pair, self.LLM_SIGNAL_FILE)
            if llm_sig != 0:
                long_signal = long_signal & (llm_sig > 0)
                short_signal = short_signal & (llm_sig < 0)

        dataframe.loc[long_signal, 'enter_long'] = 1
        dataframe.loc[short_signal, 'enter_short'] = 1
        dataframe.loc[long_signal, 'enter_tag'] = 'ultra_long'
        dataframe.loc[short_signal, 'enter_tag'] = 'ultra_short'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit solo da trailing stop — no exit signal prematuro
        return dataframe

    # ── Limit entry su pullback ──────────────────────

    def custom_entry_price(self, pair: str, trade: Optional[Trade],
                           current_time: datetime, proposed_rate: float,
                           entry_tag: Optional[str], side: str, **kwargs) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) == 0:
            return proposed_rate
        last = dataframe.iloc[-1]
        atr = float(last.get('atr_1h', proposed_rate * 0.02))
        ratio = self.pullback_ratio.value

        if side == 'long':
            return max(proposed_rate - atr * ratio, proposed_rate * 0.97)
        else:
            return min(proposed_rate + atr * ratio, proposed_rate * 1.03)

    # ── Risk management ──────────────────────────────

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: Optional[str], side: str, **kwargs) -> bool:
        if 2 <= current_time.hour < 6:
            return False
        is_short = (side == 'short')
        open_trades = Trade.get_open_trades()
        same_dir = sum(1 for t in open_trades if t.is_short == is_short)
        return same_dir < self.max_same_direction

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                             proposed_stake: float, min_stake: Optional[float],
                             max_stake: float, leverage: float, entry_tag: Optional[str],
                             side: str, **kwargs) -> float:
        return max_stake / self.config.get('max_open_trades', 4) * 0.5

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float,
                 entry_tag: Optional[str], side: str, **kwargs) -> float:
        return 2.0
