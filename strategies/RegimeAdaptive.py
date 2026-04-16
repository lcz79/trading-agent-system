"""
RegimeAdaptive - Strategia adattiva al regime di mercato

Rileva il regime di mercato ogni candle (4h timeframe come riferimento) e applica
la logica di trading appropriata:

REGIME TREND (ADX_4h > 25 + BB_width ampia):
  → ATR Breakout + trailing stop (cattura i movimenti direzionali)
  → Entry: market order al breakout ATR
  → Exit: trailing stop attivo da +8%, trail 5%

REGIME RANGE (ADX_4h < 20 + BB_width compressa):
  → RSI Mean Reversion agli estremi di Bollinger Band
  → Long: RSI < 35 AND close < BB_lower + buffer
  → Short: RSI > 65 AND close > BB_upper - buffer
  → Exit: ROI fisso +2% oppure stop -3%

REGIME VOLATILE (ATR > 2x media 20 periodi):
  → Nessun trade (mercato imprevedibile, troppo rischio)

LLM GATE (aggiornato ogni ora da llm_producer):
  → Claude analizza il contesto macro e conferma/rifiuta l'entry
  → Confidenza < 0.6 = skip trade
  → Segnale opposto alla direzione = skip trade

Leva: 2x su tutti i trade
Max 4 trade aperti, max 2 per direzione
"""

import os
import json
import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime, timezone
from typing import Optional

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from freqtrade.strategy import merge_informative_pair
from freqtrade.persistence import Trade


class RegimeAdaptive(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '1h'
    informative_timeframe = '4h'
    can_short = True

    order_types = {
        'entry': 'market',
        'exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False
    }

    minimal_roi = {
        "0": 100  # Solo trailing stop e stoploss gestiscono le exit
    }

    # Stop loss fisso come rete di sicurezza
    stoploss = -0.07
    use_custom_stoploss = True  # gestione dinamica per regime

    # Trailing stop: attivo dopo +8%, trail 5%
    trailing_stop = True
    trailing_stop_positive = 0.05
    trailing_stop_positive_offset = 0.08
    trailing_only_offset_is_reached = True

    startup_candle_count = 250

    leverage_num = 2.0

    # --- Parametri regime ---
    adx_trend_threshold = DecimalParameter(20.0, 30.0, default=25.0, space='buy', optimize=False)
    adx_range_threshold = DecimalParameter(10.0, 22.0, default=18.0, space='buy', optimize=False)
    atr_volatile_mult = DecimalParameter(1.5, 3.0, default=2.0, space='buy', optimize=False)

    # --- Parametri TREND mode ---
    atr_mult_trend = DecimalParameter(1.0, 2.5, default=1.5, space='buy', optimize=False)

    # --- Parametri RANGE mode ---
    rsi_long_threshold = DecimalParameter(25.0, 40.0, default=35.0, space='buy', optimize=False)
    rsi_short_threshold = DecimalParameter(60.0, 75.0, default=65.0, space='buy', optimize=False)
    bb_buffer = DecimalParameter(0.001, 0.01, default=0.003, space='buy', optimize=False)

    # --- LLM gate ---
    llm_min_confidence = DecimalParameter(0.5, 0.8, default=0.6, space='buy', optimize=False)
    use_llm = True  # disabilitare se llm_producer non è attivo

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: Optional[str],
                 side: str) -> float:
        return min(self.leverage_num, max_leverage)

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float:
        """
        Sempre usa lo stoploss fisso. Non ritornare mai 1.0 (= stop a +100% = nessuno stop!)
        """
        return self.stoploss  # -0.07

    def _load_llm_signal(self, pair: str) -> dict:
        """Legge il segnale LLM dal file prodotto da llm_producer."""
        signal_file = os.getenv('SIGNAL_FILE', '/freqtrade/user_data/llm_signals.json')
        try:
            with open(signal_file, 'r') as f:
                signals = json.load(f)
            # Il producer usa USDC, noi usiamo USDT — normalizza
            pair_key = pair.replace('USDT', 'USDC')
            signal = signals.get(pair_key, signals.get(pair, {}))
            if not signal:
                return {'signal': 0, 'confidence': 0.0}
            # Verifica freschezza (< 4 ore)
            ts = signal.get('timestamp', '')
            if ts:
                from datetime import timezone
                sig_time = datetime.fromisoformat(ts)
                age_hours = (datetime.now(timezone.utc) - sig_time).total_seconds() / 3600
                if age_hours > 4:
                    return {'signal': 0, 'confidence': 0.0}
            return signal
        except Exception:
            return {'signal': 0, 'confidence': 0.0}

    def _llm_allows_entry(self, pair: str, direction: str) -> bool:
        """Verifica che il segnale LLM sia compatibile con la direzione del trade."""
        if not self.use_llm:
            return True
        llm = self._load_llm_signal(pair)
        signal = llm.get('signal', 0)
        confidence = llm.get('confidence', 0.0)
        # LLM segnale opposto → blocca
        if direction == 'long' and signal == -1:
            return False
        if direction == 'short' and signal == 1:
            return False
        # Confidenza troppo bassa se il segnale è neutro → permetti comunque
        # Confidenza bassa se il segnale è nella nostra direzione → blocca
        if direction == 'long' and signal == 1 and confidence < self.llm_min_confidence.value:
            return False
        if direction == 'short' and signal == -1 and confidence < self.llm_min_confidence.value:
            return False
        return True

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata['pair']

        # ── ATR 1h ──────────────────────────────────────────────────────────
        tr = pd.concat([
            dataframe['high'] - dataframe['low'],
            (dataframe['high'] - dataframe['close'].shift(1)).abs(),
            (dataframe['low'] - dataframe['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        dataframe['atr'] = tr.ewm(alpha=1/14, min_periods=14).mean()
        dataframe['atr_avg20'] = dataframe['atr'].rolling(20).mean()
        dataframe['atr_volatile'] = dataframe['atr'] > dataframe['atr_avg20'] * self.atr_volatile_mult.value

        # ── RSI 1h ───────────────────────────────────────────────────────────
        delta = dataframe['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
        dataframe['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

        # ── Bollinger Bands 1h (20 periodi, 2σ) ─────────────────────────────
        bb_mid = dataframe['close'].rolling(20).mean()
        bb_std = dataframe['close'].rolling(20).std()
        dataframe['bb_upper'] = bb_mid + 2 * bb_std
        dataframe['bb_lower'] = bb_mid - 2 * bb_std
        dataframe['bb_mid'] = bb_mid
        dataframe['bb_width'] = (dataframe['bb_upper'] - dataframe['bb_lower']) / bb_mid

        # ── SMA 200 1h (filtro macro direzionale) ───────────────────────────
        dataframe['sma200'] = dataframe['close'].rolling(200).mean()

        # ── ATR Breakout signal 1h ───────────────────────────────────────────
        # Breakout: close > high del candle precedente + ATR*mult (long)
        #           close < low del candle precedente - ATR*mult (short)
        mult = self.atr_mult_trend.value
        dataframe['breakout_long'] = (
            dataframe['close'] > dataframe['high'].shift(1) + dataframe['atr'].shift(1) * mult
        )
        dataframe['breakout_short'] = (
            dataframe['close'] < dataframe['low'].shift(1) - dataframe['atr'].shift(1) * mult
        )

        # ── Merge dati 4h per regime detection ──────────────────────────────
        informative = self.dp.get_pair_dataframe(pair=pair, timeframe='4h')

        # ADX 4h
        info_tr = pd.concat([
            informative['high'] - informative['low'],
            (informative['high'] - informative['close'].shift(1)).abs(),
            (informative['low'] - informative['close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        info_atr = info_tr.ewm(alpha=1/14, min_periods=14).mean()

        # DX → ADX
        up_move = informative['high'].diff()
        down_move = -informative['low'].diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        plus_di = 100 * pd.Series(plus_dm, index=informative.index).ewm(alpha=1/14, min_periods=14).mean() / info_atr.replace(0, np.nan)
        minus_di = 100 * pd.Series(minus_dm, index=informative.index).ewm(alpha=1/14, min_periods=14).mean() / info_atr.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        informative['adx'] = dx.ewm(alpha=1/14, min_periods=14).mean()

        # Bollinger Width 4h
        bb_mid_4h = informative['close'].rolling(20).mean()
        bb_std_4h = informative['close'].rolling(20).std()
        informative['bb_width_4h'] = (bb_mid_4h + 2*bb_std_4h - (bb_mid_4h - 2*bb_std_4h)) / bb_mid_4h

        # Regime: TREND=1, RANGE=2, VOLATILE=3, NEUTRAL=0
        informative['regime'] = 0
        adx_trend = self.adx_trend_threshold.value
        adx_range = self.adx_range_threshold.value
        informative.loc[informative['adx'] >= adx_trend, 'regime'] = 1   # TREND
        informative.loc[informative['adx'] < adx_range, 'regime'] = 2    # RANGE
        # Volatile override
        info_atr_avg = info_atr.rolling(20).mean()
        informative.loc[info_atr > info_atr_avg * self.atr_volatile_mult.value, 'regime'] = 3

        # Merge 4h → 1h
        informative['date'] = informative['date']
        dataframe = merge_informative_pair(
            dataframe, informative[['date', 'adx', 'bb_width_4h', 'regime']],
            self.timeframe, '4h', ffill=True
        )

        # ── Nessuna operazione nelle ore notturne (02-06 UTC) ────────────────
        dataframe['hour'] = dataframe['date'].dt.hour
        dataframe['no_trade_window'] = dataframe['hour'].between(2, 5)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata['pair']

        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0
        dataframe['enter_tag'] = ''

        # Nessun trade in regime volatile o ore notturne
        base_filter = (
            ~dataframe['no_trade_window'] &
            ~dataframe['atr_volatile'] &
            (dataframe['regime_4h'] != 3) &
            (dataframe['volume'] > 0)
        )

        # ── TREND REGIME: ATR Breakout ───────────────────────────────────────
        trend_filter = base_filter & (dataframe['regime_4h'] == 1)

        long_trend = (
            trend_filter &
            dataframe['breakout_long'] &
            (dataframe['close'] > dataframe['sma200'])  # solo long in macro uptrend
        )
        # SHORT solo in bear trend CONFERMATO:
        # - SMA200 in discesa (slope negativo su 10 periodi)
        # - Prezzo sotto SMA200
        # - ADX forte (trend confermato)
        sma200_slope = dataframe['sma200'] - dataframe['sma200'].shift(10)
        short_trend = (
            trend_filter &
            dataframe['breakout_short'] &
            (dataframe['close'] < dataframe['sma200']) &   # sotto macro trend
            (sma200_slope < 0)                              # SMA200 in discesa
        )

            # ── Applica segnali ───────────────────────────────────────────────────
        # Range trading rimosso: in range il bot aspetta senza fare nulla.
        # Solo trend trades — il range trading aveva 18% WR e distruggeva i profitti.
        dataframe.loc[long_trend, 'enter_tag'] = 'trend_long'
        dataframe.loc[short_trend, 'enter_tag'] = 'trend_short'

        dataframe.loc[long_trend, 'enter_long'] = 1
        dataframe.loc[short_trend, 'enter_short'] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Exit gestita da trailing stop e custom_stoploss. Nessun exit signal."""
        dataframe['exit_long'] = 0
        dataframe['exit_short'] = 0

        # Range trades: esci al BB middle (ROI dinamico)
        # Gestito da minimal_roi + custom_stoploss

        return dataframe

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: Optional[str], side: str, **kwargs) -> bool:
        """Verifica LLM gate prima di entrare."""
        if not self.use_llm:
            return True
        direction = 'long' if side == 'long' else 'short'
        if not self._llm_allows_entry(pair, direction):
            return False
        return True

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        """
        Nessuna exit custom — trailing stop e stoploss fisso gestiscono tutto.
        Non aggiungere exit che tagliano i winner.
        """
        return None
