"""
FASE 2 Position Sizing Module - Risk-based Equity Position Sizing

This module provides risk-based position sizing calculations:
- position_size = risk_amount / stop_distance
- risk_amount = equity * risk_pct
- stop_distance based on ATR or percentage

Respects Bybit precision and minimum lot size requirements.
"""

from decimal import Decimal, ROUND_DOWN
from typing import Tuple, Optional


def calculate_position_size(
    equity: float,
    risk_pct: float,
    entry_price: float,
    stop_loss_price: float,
    leverage: float,
    qty_step: float,
    min_qty: float
) -> Tuple[float, dict]:
    """
    Calculate position size based on risk-based equity management.
    
    Formula:
    - risk_amount = equity * risk_pct
    - stop_distance = abs(entry_price - stop_loss_price)
    - position_value = risk_amount / (stop_distance / entry_price)
    - position_size_contracts = position_value / entry_price
    
    Args:
        equity: Current account equity (USDT)
        risk_pct: Risk percentage per trade (e.g., 0.003 for 0.3%)
        entry_price: Expected entry price
        stop_loss_price: Stop loss price
        leverage: Leverage to use
        qty_step: Minimum quantity step (from exchange)
        min_qty: Minimum quantity (from exchange)
    
    Returns:
        Tuple of (final_qty, sizing_info_dict)
    """
    sizing_info = {}
    
    # Calculate risk amount in USDT
    risk_amount = equity * risk_pct
    sizing_info['equity'] = equity
    sizing_info['risk_pct'] = risk_pct
    sizing_info['risk_amount_usdt'] = risk_amount
    
    # Calculate stop distance as percentage of entry price
    stop_distance_abs = abs(entry_price - stop_loss_price)
    stop_distance_pct = stop_distance_abs / entry_price
    sizing_info['stop_distance_abs'] = stop_distance_abs
    sizing_info['stop_distance_pct'] = stop_distance_pct
    
    # Position value that would lose risk_amount if SL is hit
    # If we lose stop_distance_pct with leverage, we need:
    # position_value * leverage * stop_distance_pct = risk_amount
    # position_value = risk_amount / (leverage * stop_distance_pct)
    if stop_distance_pct <= 0:
        # Invalid stop distance
        return min_qty, {**sizing_info, 'error': 'Invalid stop distance'}
    
    position_value = risk_amount / (leverage * stop_distance_pct)
    sizing_info['position_value'] = position_value
    
    # Convert position value to contracts
    qty_raw = position_value / entry_price
    sizing_info['qty_raw'] = qty_raw
    
    # Apply Bybit precision (round down to qty_step)
    d_qty = Decimal(str(qty_raw))
    d_step = Decimal(str(qty_step))
    steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
    final_qty_d = steps * d_step
    
    # Ensure minimum quantity
    if final_qty_d < Decimal(str(min_qty)):
        final_qty_d = Decimal(str(min_qty))
    
    final_qty = float("{:f}".format(final_qty_d.normalize()))
    sizing_info['qty_step'] = qty_step
    sizing_info['min_qty'] = min_qty
    sizing_info['final_qty'] = final_qty
    
    return final_qty, sizing_info


def calculate_stop_loss_from_atr(
    entry_price: float,
    atr: float,
    atr_multiplier: float,
    direction: str,
    min_sl_pct: float = 0.005,
    max_sl_pct: float = 0.10
) -> Tuple[float, dict]:
    """
    Calculate stop loss price based on ATR.
    
    Args:
        entry_price: Entry price
        atr: Average True Range value
        atr_multiplier: Multiplier for ATR (e.g., 1.2)
        direction: 'long' or 'short'
        min_sl_pct: Minimum SL distance as percentage (0.5%)
        max_sl_pct: Maximum SL distance as percentage (10%)
    
    Returns:
        Tuple of (stop_loss_price, sl_info_dict)
    """
    sl_info = {}
    
    # Calculate SL distance from ATR
    sl_distance = atr * atr_multiplier
    sl_distance_pct = sl_distance / entry_price
    
    # Clamp SL distance
    sl_distance_pct = max(min_sl_pct, min(max_sl_pct, sl_distance_pct))
    sl_info['atr'] = atr
    sl_info['atr_multiplier'] = atr_multiplier
    sl_info['sl_distance_pct'] = sl_distance_pct
    
    # Calculate SL price
    if direction == 'long':
        stop_loss_price = entry_price * (1 - sl_distance_pct)
    else:  # short
        stop_loss_price = entry_price * (1 + sl_distance_pct)
    
    sl_info['stop_loss_price'] = stop_loss_price
    sl_info['entry_price'] = entry_price
    sl_info['direction'] = direction
    
    return stop_loss_price, sl_info


def calculate_take_profit_from_atr(
    entry_price: float,
    atr: float,
    atr_multiplier: float,
    direction: str,
    regime: str = "RANGE",
    regime_multiplier_trend: float = 1.5,
    regime_multiplier_range: float = 1.0
) -> Tuple[float, dict]:
    """
    Calculate take profit price based on ATR and market regime.
    
    Args:
        entry_price: Entry price
        atr: Average True Range value
        atr_multiplier: Base multiplier for ATR (e.g., 2.4)
        direction: 'long' or 'short'
        regime: 'TREND' or 'RANGE'
        regime_multiplier_trend: Additional multiplier for TREND mode (1.5 = 50% more lenient)
        regime_multiplier_range: Additional multiplier for RANGE mode (1.0 = base)
    
    Returns:
        Tuple of (take_profit_price, tp_info_dict)
    """
    tp_info = {}
    
    # Apply regime multiplier
    regime_adj = regime_multiplier_trend if regime == "TREND" else regime_multiplier_range
    effective_multiplier = atr_multiplier * regime_adj
    
    # Calculate TP distance from ATR
    tp_distance = atr * effective_multiplier
    tp_distance_pct = tp_distance / entry_price
    
    tp_info['atr'] = atr
    tp_info['atr_multiplier_base'] = atr_multiplier
    tp_info['regime'] = regime
    tp_info['regime_multiplier'] = regime_adj
    tp_info['effective_multiplier'] = effective_multiplier
    tp_info['tp_distance_pct'] = tp_distance_pct
    
    # Calculate TP price
    if direction == 'long':
        take_profit_price = entry_price * (1 + tp_distance_pct)
    else:  # short
        take_profit_price = entry_price * (1 - tp_distance_pct)
    
    tp_info['take_profit_price'] = take_profit_price
    tp_info['entry_price'] = entry_price
    tp_info['direction'] = direction
    
    return take_profit_price, tp_info


def calculate_trailing_distance_from_atr(
    price: float,
    atr: float,
    atr_multiplier_base: float,
    regime: str = "RANGE",
    regime_multiplier_trend: float = 1.5,
    regime_multiplier_range: float = 1.0,
    min_distance_pct: float = 0.005,
    max_distance_pct: float = 0.08,
    min_atr_clamp: float = 0.0001
) -> Tuple[float, dict]:
    """
    Calculate trailing stop distance based on ATR and market regime.
    
    Formula: trailing_distance_pct = (ATR / price) * factor
    Factor varies by regime: TREND uses higher factor (more lenient), RANGE uses base factor.
    
    Args:
        price: Current price
        atr: Average True Range value
        atr_multiplier_base: Base multiplier for ATR (e.g., 1.2)
        regime: 'TREND' or 'RANGE'
        regime_multiplier_trend: Additional multiplier for TREND mode (1.5)
        regime_multiplier_range: Additional multiplier for RANGE mode (1.0)
        min_distance_pct: Minimum trailing distance (0.5%)
        max_distance_pct: Maximum trailing distance (8%)
        min_atr_clamp: Minimum ATR value to avoid division issues
    
    Returns:
        Tuple of (trailing_distance_pct, trail_info_dict)
    """
    trail_info = {}
    
    # Clamp ATR to avoid division issues
    atr_clamped = max(atr, min_atr_clamp)
    trail_info['atr_raw'] = atr
    trail_info['atr_clamped'] = atr_clamped
    
    # Apply regime multiplier
    regime_adj = regime_multiplier_trend if regime == "TREND" else regime_multiplier_range
    effective_multiplier = atr_multiplier_base * regime_adj
    
    # Calculate trailing distance
    trailing_distance_pct = (atr_clamped / price) * effective_multiplier
    
    # Clamp to min/max
    trailing_distance_pct = max(min_distance_pct, min(max_distance_pct, trailing_distance_pct))
    
    trail_info['price'] = price
    trail_info['atr_multiplier_base'] = atr_multiplier_base
    trail_info['regime'] = regime
    trail_info['regime_multiplier'] = regime_adj
    trail_info['effective_multiplier'] = effective_multiplier
    trail_info['trailing_distance_pct'] = trailing_distance_pct
    trail_info['min_distance_pct'] = min_distance_pct
    trail_info['max_distance_pct'] = max_distance_pct
    
    return trailing_distance_pct, trail_info
