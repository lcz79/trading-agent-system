"""
RegimeAdaptive v2 - Trend + Range Dual Mode

Filosofia:
  Un trader esperto non usa la stessa strategia in ogni condizione di mercato.
  - Mercato in TREND (ADX > 22): segui il trend, ATR breakout 3h
  - Mercato in RANGE (ADX < 18): mean reversion, compra ai minimi, vendi ai massimi
  - Mercato INCERTO (18-22): niente posizioni

Trend regime:
  Entry: ATR 3h breakout (> 1.5x ATR) + direzione determinata da SMA200 + slope
  Long: solo se sopra SMA200 e slope positivo da N barre
  Short: solo se sotto SMA200 e slope negativo da N barre (più selettivi)
  SL: -3% fisso via custom_stoploss
  TP: trailing da +5%, trail 2.5% — gestito via custom_exit
  Max 3 posizioni

Range regime:
  Entry: BB(20,2) penetrazione + RSI estremo + candela di rimbalzo (bullish/bearish)
  Long: BB lower penetrata + RSI < 30 + close > open (candela verde = rimbalzo confermato)
  Short: BB upper penetrata + RSI > 70 + close < open
  TP fisso: +1.8% via custom_exit
  SL: -1.5% via custom_stoploss
  Max 4 posizioni

Key fix v2:
  - Trailing stop DISABILITATO a livello classe (gestito via custom_exit per soli trend trade)
  - ADX periodo 56 (equivalente ADX14 su 4h — meno noisy)
  - ATR breakout 1.5x (meno falsi segnali)
  - Range entry richiede candela di conferma (rimbalzo effettivo, non solo tocco)
  - RSI range più stretto (30/70 invece di 32/68)
  - SL global -5% (fallback)

DeepSeek gate: solo per trend regime
Leverage: trend 2x, range 1.5x
"""

import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from typing import Optional
import json
import os

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
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


class RegimeAdaptive(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    can_short = True

    order_types = {
        'entry': 'limit',
        'exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False
    }

    unfilledtimeout = {'entry': 120, 'exit': 60, 'unit': 'minutes'}

    minimal_roi = {"0": 100}

    stoploss = -0.05
    use_custom_stoploss = True

    # Trailing DISABILITATO a livello classe — gestito via custom_exit solo per trend
    trailing_stop = False

    startup_candle_count = 250
    position_adjustment_enable = False

    # ─── Parametri regime ───────────────────────────────────────────────────
    adx_trend_min = DecimalParameter(20.0, 26.0, default=22.0, space='buy', optimize=False)
    adx_range_max = DecimalParameter(14.0, 20.0, default=18.0, space='buy', optimize=False)

    # ─── Parametri trend regime ─────────────────────────────────────────────
    trend_atr_mult = DecimalParameter(1.2, 2.0, default=1.5, space='buy', optimize=False)
    trend_pullback = DecimalParameter(0.3, 0.6, default=0.4, space='buy', optimize=False)
    trend_sl = DecimalParameter(0.02, 0.05, default=0.03, space='sell', optimize=False)
    trend_trail_offset = DecimalParameter(0.03, 0.08, default=0.05, space='sell', optimize=False)
    trend_trail_pct = DecimalParameter(0.01, 0.04, default=0.025, space='sell', optimize=False)
    sma200_slope_long_bars = IntParameter(5, 15, default=8, space='buy', optimize=False)
    sma200_slope_short_bars = IntParameter(10, 25, default=15, space='buy', optimize=False)

    # ─── Parametri range regime ─────────────────────────────────────────────
    range_rsi_long = DecimalParameter(22.0, 35.0, default=30.0, space='buy', optimize=False)
    range_rsi_short = DecimalParameter(65.0, 78.0, default=70.0, space='sell', optimize=False)
    range_tp = DecimalParameter(0.012, 0.025, default=0.018, space='sell', optimize=False)
    range_sl = DecimalParameter(0.01, 0.025, default=0.015, space='sell', optimize=False)

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: Optional[str],
                 side: str) -> float:
        if entry_tag and entry_tag.startswith('range_'):
            return min(1.5, max_leverage)
        return min(2.0, max_leverage)

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float:
        """
        Range: SL fisso -1.5%
        Trend: SL fisso -3%, trailing manuale via custom_exit
        """
        entry_tag = trade.enter_tag or ''
        if entry_tag.startswith('range_'):
            sl = -self.range_sl.value
            if current_profit <= sl:
                return -0.001
            return sl
        # Trend: -3%
        if current_profit <= -self.trend_sl.value:
            return -0.001
        return -self.trend_sl.value

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        """
        Range: TP fisso +1.8%
        Trend: trailing manuale dal +5% con trail 2.5%
        """
        entry_tag = trade.enter_tag or ''
        if entry_tag.startswith('range_'):
            if current_profit >= self.range_tp.value:
                return 'range_tp'
        elif entry_tag.startswith('trend_'):
            # Trailing manuale: attivo dopo trail_offset, trail dal massimo storico
            if current_profit >= self.trend_trail_offset.value:
                # Calcola massimo profitto raggiunto dalla trade
                max_profit = trade.max_rate / trade.open_rate - 1 if trade.is_open else 0
                if trade.trade_direction == 'short':
                    max_profit = 1 - trade.min_rate / trade.open_rate
                trail_sl = max_profit - self.trend_trail_pct.value
                if current_profit <= trail_sl and trail_sl > 0:
                    return 'trend_trail'
        return None

    def _read_deepseek_signal(self, pair: str) -> dict:
        signal_file = os.getenv('DEEPSEEK_SIGNAL_FILE',
                                '/freqtrade/user_data/deepseek_signals.json')
        try:
            with open(signal_file, 'r') as f:
                signals = json.load(f)
            key = f"{pair.split('/')[0]}/USDC:USDC"
            return signals.get(key, {})
        except Exception:
            return {}

    def _deepseek_allows_entry(self, pair: str, side: str) -> bool:
        """Solo per trend regime. Blocca se bias opposto con conf >= 0.65."""
        sig = self._read_deepseek_signal(pair)
        if not sig:
            return True
        bias = sig.get('bias', 'NEUTRAL')
        conf = float(sig.get('confidence', 0))
        if side == 'long' and bias == 'LONG_RISK' and conf >= 0.65:
            return False
        if side == 'short' and bias == 'SHORT_RISK' and conf >= 0.65:
            return False
        return True

    def _conviction_score(self, last_row, pair: str, side: str) -> float:
        """Score 0-1 basato su ADX, ATRx, DeepSeek (solo trend regime)."""
        score = 0.0
        adx = float(last_row.get('adx', 0))
        if adx >= 30:
            score += 0.30
        elif adx >= 25:
            score += 0.20
        elif adx >= 22:
            score += 0.10

        atr_x = float(last_row.get('atr_x', 0))
        if atr_x >= 2.0:
            score += 0.20
        elif atr_x >= 1.5:
            score += 0.15
        elif atr_x >= 1.2:
            score += 0.10

        sig = self._read_deepseek_signal(pair)
        if sig:
            bias = sig.get('bias', 'NEUTRAL')
            conf = float(sig.get('confidence', 0))
            if side == 'long' and bias == 'LONG_OK' and conf >= 0.70:
                score += 0.35
            elif side == 'long' and bias == 'LONG_OK' and conf >= 0.50:
                score += 0.20
            elif side == 'short' and bias == 'SHORT_OK' and conf >= 0.70:
                score += 0.35
            elif side == 'short' and bias == 'SHORT_OK' and conf >= 0.50:
                score += 0.20
            elif bias in ('LONG_RISK', 'SHORT_RISK'):
                score -= 0.30

        return max(0.0, min(1.0, score))

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ── SMA 200 ──────────────────────────────────────────────────────────
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()
        sma200_slope = dataframe['sma200'] - dataframe['sma200'].shift(1)

        # Candele consecutive con slope positivo: rolling sum degli ultimi N barre
        slope_pos = (sma200_slope > 0).astype(int)
        slope_neg = (sma200_slope < 0).astype(int)
        # Quante delle ultime N barre hanno slope positivo/negativo
        dataframe['slope_pos_10'] = slope_pos.rolling(10).sum()   # >= 8 = trend up forte
        dataframe['slope_neg_15'] = slope_neg.rolling(15).sum()   # >= 12 = trend down forte

        # ── RSI 14 ───────────────────────────────────────────────────────────
        delta = dataframe['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
        dataframe['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

        # ── Bollinger Bands (20, 2) per range regime ─────────────────────────
        bb_period = 20
        bb_std = 2.0
        dataframe['bb_mid'] = dataframe['close'].rolling(bb_period).mean()
        bb_std_val = dataframe['close'].rolling(bb_period).std()
        dataframe['bb_lower'] = dataframe['bb_mid'] - bb_std * bb_std_val
        dataframe['bb_upper'] = dataframe['bb_mid'] + bb_std * bb_std_val

        # ── ADX — periodo 56 (ADX14 equivalente su 4h, meno noise su 1h) ───
        up_move = dataframe['high'].diff()
        down_move = -dataframe['low'].diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift(1)).abs(),
            (dataframe['low'] - dataframe['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        period = 56
        atr_adx = tr.ewm(alpha=1/period, min_periods=period).mean()
        plus_di = 100 * pd.Series(plus_dm, index=dataframe.index).ewm(
            alpha=1/period, min_periods=period).mean() / atr_adx.replace(0, np.nan)
        minus_di = 100 * pd.Series(minus_dm, index=dataframe.index).ewm(
            alpha=1/period, min_periods=period).mean() / atr_adx.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        dataframe['adx'] = dx.ewm(alpha=1/period, min_periods=period).mean()

        # ── ATR Breakout 3h ──────────────────────────────────────────────────
        df_3h = resample_to_interval(dataframe, '3h')
        df_3h['atr_3h'] = calc_atr(df_3h)
        df_3h['close_change_3h'] = df_3h['close'].diff()
        df_3h = df_3h[['date', 'atr_3h', 'close_change_3h']]

        dataframe = pd.merge_asof(
            dataframe.sort_values('date'),
            df_3h.sort_values('date'),
            on='date', direction='backward'
        )

        atr_prev = dataframe['atr_3h'].shift(1)
        dataframe['atr_x'] = (dataframe['close_change_3h'].abs() / atr_prev.replace(0, np.nan)).fillna(0)

        # ── Regime ───────────────────────────────────────────────────────────
        dataframe['regime_trend'] = dataframe['adx'] >= self.adx_trend_min.value
        dataframe['regime_range'] = dataframe['adx'] <= self.adx_range_max.value

        # ── Segnali trend regime ─────────────────────────────────────────────
        strong_atr_threshold = atr_prev * self.trend_atr_mult.value

        # Long: breakout rialzista + SMA200 slope positivo (>= 8/10 barre) + sopra SMA200
        dataframe['trend_long'] = (
            dataframe['regime_trend'] &
            (dataframe['close_change_3h'] > strong_atr_threshold) &
            (dataframe['close'] > dataframe['sma200']) &
            (dataframe['slope_pos_10'] >= self.sma200_slope_long_bars.value)
        )
        # Short: breakout ribassista + SMA200 slope negativo (>= 12/15 barre) + sotto SMA200
        dataframe['trend_short'] = (
            dataframe['regime_trend'] &
            (dataframe['close_change_3h'] * -1 > strong_atr_threshold) &
            (dataframe['close'] < dataframe['sma200']) &
            (dataframe['slope_neg_15'] >= self.sma200_slope_short_bars.value)
        )

        # ── Segnali range regime ─────────────────────────────────────────────
        # Long: BB lower penetrata + RSI < 30 + candela verde (rimbalzo confermato)
        dataframe['range_long'] = (
            dataframe['regime_range'] &
            (dataframe['low'] < dataframe['bb_lower']) &      # lower band penetrata
            (dataframe['close'] > dataframe['open']) &         # candela verde (rimbalzo)
            (dataframe['close'] > dataframe['bb_lower']) &     # close sopra BB lower
            (dataframe['rsi'] < self.range_rsi_long.value)
        )
        # Short: BB upper penetrata + RSI > 70 + candela rossa
        dataframe['range_short'] = (
            dataframe['regime_range'] &
            (dataframe['high'] > dataframe['bb_upper']) &
            (dataframe['close'] < dataframe['open']) &
            (dataframe['close'] < dataframe['bb_upper']) &
            (dataframe['rsi'] > self.range_rsi_short.value)
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

        trend_long = base & dataframe['trend_long']
        trend_short = base & dataframe['trend_short']
        range_long = base & dataframe['range_long']
        range_short = base & dataframe['range_short']

        dataframe.loc[trend_long, 'enter_tag'] = 'trend_long'
        dataframe.loc[trend_short, 'enter_tag'] = 'trend_short'
        dataframe.loc[range_long, 'enter_tag'] = 'range_long'
        dataframe.loc[range_short, 'enter_tag'] = 'range_short'

        dataframe.loc[trend_long | range_long, 'enter_long'] = 1
        dataframe.loc[trend_short | range_short, 'enter_short'] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_short'] = 0
        return dataframe

    def custom_entry_price(self, pair: str, trade: Optional[Trade],
                           current_time: datetime, proposed_rate: float,
                           entry_tag: Optional[str], side: str, **kwargs) -> float:
        """
        Trend: limit con pullback 40% del breakout
        Range: entry diretta al prezzo proposto (la candela di rimbalzo è già confermata)
        """
        if not entry_tag:
            return proposed_rate

        if entry_tag.startswith('trend_'):
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe.empty:
                return proposed_rate
            last = dataframe.iloc[-1]
            close_change = abs(float(last.get('close_change_3h', 0)))
            pullback = close_change * self.trend_pullback.value
            if side == 'long':
                return proposed_rate - pullback
            else:
                return proposed_rate + pullback

        # Range: entry diretta (non aspettare pullback su mean reversion)
        return proposed_rate

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: Optional[str], side: str, **kwargs) -> bool:
        """
        Trend: max 3 posizioni + DeepSeek gate
        Range: max 4 posizioni (no DeepSeek)
        """
        tag = entry_tag or ''
        open_trades = Trade.get_open_trades()

        if tag.startswith('trend_'):
            trend_count = sum(1 for t in open_trades if (t.enter_tag or '').startswith('trend_'))
            if trend_count >= 3:
                return False
            if not self._deepseek_allows_entry(pair, side):
                return False

        elif tag.startswith('range_'):
            range_count = sum(1 for t in open_trades if (t.enter_tag or '').startswith('range_'))
            if range_count >= 4:
                return False

        return True

    def custom_stake_amount(self, current_time: datetime, current_rate: float,
                            current_profit: float, capital_available: float,
                            proposed_stake: float, min_stake: Optional[float],
                            max_stake: float, leverage: float, entry_tag: Optional[str],
                            side: str, **kwargs) -> float:
        """
        Range: 25% stake fisso (bassa leva, SL stretto)
        Trend: conviction-based sizing
        """
        tag = entry_tag or ''

        if tag.startswith('range_'):
            base = max_stake / 4  # 1/4 del max
            return max(min_stake or 0, min(base, max_stake))

        # Trend: conviction score
        try:
            pair = kwargs.get('pair', '')
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if not dataframe.empty:
                last = dataframe.iloc[-1]
                score = self._conviction_score(last, pair, side)
                if score >= 0.75:
                    multiplier = 1.5
                elif score >= 0.55:
                    multiplier = 1.0
                elif score >= 0.35:
                    multiplier = 0.6
                else:
                    multiplier = 0.3
                sized = proposed_stake * multiplier
                return max(min_stake or 0, min(sized, max_stake))
        except Exception:
            pass

        return proposed_stake
