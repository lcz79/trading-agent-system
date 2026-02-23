"""
Enhanced Confluence Scoring System (0-100)

5-dimension scoring replaces the old binary trend check.
Used by the orchestrator for deterministic entry decisions.

Dimensions:
  1. Trend Alignment  (0-30) - Multi-TF trend agreement weighted by ADX
  2. Momentum Quality (0-20) - MACD histogram direction + RSI position
  3. Mean Reversion   (0-20) - Bollinger Band position + EMA20 distance
  4. Volume Confirm   (0-15) - Volume Z-score confirmation
  5. Key Level Prox   (0-15) - Price near Fibonacci / EMA support-resistance
"""

from typing import Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _safe(d: dict, *keys, default=None):
    """Nested dict get."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur


def _to_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# 1. Trend Alignment  (0-30)
# ---------------------------------------------------------------------------

def _trend_value(tf_data: dict) -> float:
    """Return +1 for bullish, -1 for bearish, 0 for unknown."""
    t = (tf_data.get("trend") or "").upper()
    if t == "BULLISH":
        return 1.0
    if t == "BEARISH":
        return -1.0
    return 0.0


def _adx_from_tf(tf_data: dict) -> float:
    """Extract ADX if available, else return 0."""
    return _to_float(tf_data.get("adx"), 0.0)


def score_trend_alignment(tech: dict, direction: str) -> float:
    """
    Multi-TF trend agreement (15m/1h/4h/1d) weighted by ADX strength.

    Each timeframe contributes a weighted share (15m=5, 1h=8, 4h=10, 1d=7).
    Score multiplied by min(adx/25, 1.0) so no trend = no score.
    Conflict penalty: if 1h and 4h disagree on direction, cap at 15.
    """
    tfs = tech.get("timeframes", {})
    weights = {"15m": 5, "1h": 8, "4h": 10, "1d": 7}  # sum = 30
    sign = 1.0 if direction == "long" else -1.0

    raw = 0.0
    for tf_name, w in weights.items():
        tf = tfs.get(tf_name, {})
        tv = _trend_value(tf) * sign  # +1 if aligned with direction
        if tv > 0:
            raw += w
        elif tv < 0:
            raw -= w * 0.5  # penalty for opposing TF

    raw = max(0.0, raw)

    # ADX weighting: use 1h ADX if available, else approximate
    adx = _adx_from_tf(tfs.get("1h", {}))
    if adx <= 0:
        adx = _adx_from_tf(tfs.get("4h", {}))
    if adx <= 0:
        # Approximate ADX from EMA50 distance: |(close - ema50)| / atr * 10
        tf_15m = tfs.get("15m", {})
        price = _to_float(tf_15m.get("price"))
        ema50 = _to_float(tf_15m.get("ema_50"))
        atr = _to_float(tf_15m.get("atr"))
        if price > 0 and ema50 > 0 and atr > 0:
            adx = min(50, abs(price - ema50) / atr * 10)
        else:
            adx = 15  # neutral default

    adx_factor = max(0.4, min(adx / 18.0, 1.0))  # floor=0.4, full credit at ADX=18
    score = raw * adx_factor

    # Conflict penalty: if 1h and 4h disagree, cap at 15
    tv_1h = _trend_value(tfs.get("1h", {}))
    tv_4h = _trend_value(tfs.get("4h", {}))
    if tv_1h != 0 and tv_4h != 0 and tv_1h != tv_4h:
        score = min(score, 15.0)

    return round(min(30.0, max(0.0, score)), 2)


# ---------------------------------------------------------------------------
# 2. Momentum Quality  (0-20)
# ---------------------------------------------------------------------------

def score_momentum(tech: dict, direction: str) -> float:
    """
    MACD histogram direction + RSI position (not overbought/oversold).

    MACD component (0-10):
      - histogram rising + aligned with direction = 10
      - histogram rising but neutral = 5
      - histogram falling against direction = 0

    RSI component (0-10):
      - RSI in sweet zone (40-60 for long, 40-60 for short) = 10
      - RSI mildly extended (30-40 or 60-70) = 5
      - RSI overbought (>70 for long) or oversold (<30 for short) = 0
    """
    tfs = tech.get("timeframes", {})
    tf_15m = tfs.get("15m", {})
    tf_1h = tfs.get("1h", {})

    # --- MACD component (0-10) ---
    macd_trend = (tf_15m.get("macd") or "").upper()
    macd_momentum = (tf_15m.get("macd_momentum") or "").upper()

    macd_score = 0.0
    if direction == "long":
        if macd_trend == "POSITIVE" and macd_momentum == "RISING":
            macd_score = 10.0
        elif macd_trend == "POSITIVE":
            macd_score = 6.0
        elif macd_momentum == "RISING":
            macd_score = 4.0
    else:  # short
        if macd_trend == "NEGATIVE" and macd_momentum == "FALLING":
            macd_score = 10.0
        elif macd_trend == "NEGATIVE":
            macd_score = 6.0
        elif macd_momentum == "FALLING":
            macd_score = 4.0

    # --- RSI component (0-10) ---
    rsi = _to_float(tf_1h.get("rsi"), 50)
    rsi_score = 0.0

    if direction == "long":
        if 35 <= rsi <= 55:
            rsi_score = 10.0  # sweet zone for long entry
        elif 25 <= rsi < 35:
            rsi_score = 7.0  # oversold = potential bounce
        elif 55 < rsi <= 65:
            rsi_score = 5.0  # slightly extended
        elif rsi > 70:
            rsi_score = 0.0  # overbought - bad for long entry
        else:
            rsi_score = 3.0
    else:  # short
        if 45 <= rsi <= 65:
            rsi_score = 10.0  # sweet zone for short entry
        elif 65 < rsi <= 75:
            rsi_score = 7.0  # overbought = potential reversal down
        elif 35 <= rsi < 45:
            rsi_score = 5.0  # slightly low
        elif rsi < 30:
            rsi_score = 0.0  # oversold - bad for short entry
        else:
            rsi_score = 3.0

    return round(min(20.0, macd_score + rsi_score), 2)


# ---------------------------------------------------------------------------
# 3. Mean Reversion  (0-20)
# ---------------------------------------------------------------------------

def score_mean_reversion(tech: dict, direction: str) -> float:
    """
    Bollinger Band position + distance from EMA20.

    Uses (close - EMA20) / ATR as magnitude measure.
    For LONG: want price below EMA20 (buying dip) -> positive score
    For SHORT: want price above EMA20 (selling rally) -> positive score

    Magnitude > 2 ATR = overextended, score drops.
    """
    tfs = tech.get("timeframes", {})
    tf_15m = tfs.get("15m", {})

    price = _to_float(tf_15m.get("price"))
    ema20 = _to_float(tf_15m.get("ema_20"))
    atr = _to_float(tf_15m.get("atr"))

    if price <= 0 or ema20 <= 0 or atr <= 0:
        return 0.0

    # Distance from EMA20 in ATR units
    dist_atr = (price - ema20) / atr

    score = 0.0

    if direction == "long":
        # Buying dip: price below EMA20 is good (negative dist_atr)
        if -2.0 <= dist_atr <= -0.3:
            score = 15.0 + min(5.0, abs(dist_atr) * 5)  # 15-20
        elif -0.3 < dist_atr <= 0.3:
            score = 13.0  # near EMA20, good trending entry
        elif 0.3 < dist_atr <= 1.0:
            score = 7.0  # slightly above, acceptable
        elif dist_atr > 1.0:
            score = 3.0  # extended above, mean reversion risk
        elif dist_atr < -2.0:
            score = 8.0  # very oversold, risky but possible bounce
    else:  # short
        # Selling rally: price above EMA20 is good (positive dist_atr)
        if 0.3 <= dist_atr <= 2.0:
            score = 15.0 + min(5.0, dist_atr * 5)  # 15-20
        elif -0.3 <= dist_atr < 0.3:
            score = 13.0  # near EMA20, good trending entry
        elif -1.0 <= dist_atr < -0.3:
            score = 7.0  # slightly below, acceptable
        elif dist_atr < -1.0:
            score = 3.0  # extended below, mean reversion risk
        elif dist_atr > 2.0:
            score = 8.0  # very overbought, risky

    return round(min(20.0, max(0.0, score)), 2)


# ---------------------------------------------------------------------------
# 4. Volume Confirmation  (0-15)
# ---------------------------------------------------------------------------

def score_volume(tech: dict) -> float:
    """
    Volume Z-score > 0.5 for confirmation.

    Uses volume_spike_Xtf from technical analyzer (current_vol / 20-bar avg).
    Spike > 1.5 = strong confirmation (15 pts)
    Spike 1.0-1.5 = moderate (10 pts)
    Spike 0.5-1.0 = weak (5 pts)
    """
    tfs = tech.get("timeframes", {})
    summary = tech.get("summary", {})

    # Try volume_spike_5m first, then 15m
    vol_spike = _to_float(summary.get("volume_spike_5m"), 0)
    if vol_spike <= 0:
        vol_spike = _to_float(tfs.get("15m", {}).get("volume_spike_15m"), 0)
    if vol_spike <= 0:
        vol_spike = _to_float(tfs.get("5m", {}).get("volume_spike_5m"), 0)

    # Also check volume_zscore (often available when spike is not)
    vol_zscore = _to_float(tfs.get("15m", {}).get("volume_zscore"), 0)
    if vol_zscore <= 0:
        vol_zscore = _to_float(tfs.get("1h", {}).get("volume_zscore"), 0)

    # Score from spike (primary)
    spike_score = 0.0
    if vol_spike >= 2.0:
        spike_score = 15.0
    elif vol_spike >= 1.5:
        spike_score = 12.0
    elif vol_spike >= 1.0:
        spike_score = 10.0
    elif vol_spike >= 0.5:
        spike_score = 7.0
    elif vol_spike >= 0.3:
        spike_score = 4.0

    # Score from zscore (secondary)
    zscore_score = 0.0
    if vol_zscore >= 2.0:
        zscore_score = 12.0
    elif vol_zscore >= 1.0:
        zscore_score = 8.0
    elif vol_zscore >= 0.5:
        zscore_score = 5.0
    elif vol_zscore >= 0.0:
        zscore_score = 3.0  # above average = some activity

    # Take the best of the two signals
    return min(15.0, max(spike_score, zscore_score))


# ---------------------------------------------------------------------------
# 5. Key Level Proximity  (0-15)
# ---------------------------------------------------------------------------

def score_key_levels(tech: dict, fib_data: dict, direction: str) -> float:
    """
    Price near Fibonacci / EMA support-resistance levels.

    For LONG: price near support levels = higher score
    For SHORT: price near resistance levels = higher score
    """
    tfs = tech.get("timeframes", {})
    tf_15m = tfs.get("15m", {})
    price = _to_float(tf_15m.get("price"))
    atr = _to_float(tf_15m.get("atr"))

    if price <= 0 or atr <= 0:
        return 0.0

    score = 0.0
    proximity_threshold = atr * 2  # within 2 ATR of a key level

    # --- EMA levels ---
    ema20 = _to_float(tf_15m.get("ema_20"))
    ema50 = _to_float(tf_15m.get("ema_50"))

    if direction == "long":
        # Support levels: EMA20, EMA50
        for ema_val in [ema20, ema50]:
            if ema_val > 0:
                dist = price - ema_val
                if 0 <= dist <= proximity_threshold:
                    # Price just above EMA (support holding)
                    score += 4.0
                elif -proximity_threshold <= dist < 0:
                    # Price just below EMA (potential bounce)
                    score += 3.0
    else:  # short
        # Resistance levels: EMA20, EMA50
        for ema_val in [ema20, ema50]:
            if ema_val > 0:
                dist = ema_val - price
                if 0 <= dist <= proximity_threshold:
                    # Price just below EMA (resistance holding)
                    score += 4.0
                elif -proximity_threshold <= dist < 0:
                    # Price just above EMA (potential rejection)
                    score += 3.0

    # --- Fibonacci levels ---
    fib_levels = fib_data.get("fib_levels", {})
    if fib_levels and price > 0:
        for level_name, level_price in fib_levels.items():
            lp = _to_float(level_price)
            if lp <= 0:
                continue

            dist_pct = abs(price - lp) / price

            if dist_pct > 0.005:  # more than 0.5% away, skip
                continue

            # Within 0.5% of a Fibonacci level
            if direction == "long":
                # Good if price is near support fibs (0.382, 0.5, 0.618)
                if "0.382" in level_name or "0.5" in level_name or "0.618" in level_name:
                    if price >= lp:  # bouncing off support
                        score += 5.0
                    else:
                        score += 3.0
            else:  # short
                # Good if price is near resistance fibs (0.618, 0.786, 1.0)
                if "0.618" in level_name or "0.786" in level_name or "1.0" in level_name:
                    if price <= lp:  # rejecting resistance
                        score += 5.0
                    else:
                        score += 3.0

    return round(min(15.0, score), 2)


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def calculate_confluence(tech: dict, fib_data: dict, direction: str) -> dict:
    """
    Calculate the full confluence score for a given direction.

    Args:
        tech: Technical analysis data from /analyze_multi_tf_full
        fib_data: Fibonacci data from /analyze_fib
        direction: 'long' or 'short'

    Returns:
        {
            "total": 0-100,
            "trend_alignment": 0-30,
            "momentum": 0-20,
            "mean_reversion": 0-20,
            "volume": 0-15,
            "key_levels": 0-15,
            "direction": "long" | "short"
        }
    """
    trend = score_trend_alignment(tech, direction)
    momentum = score_momentum(tech, direction)
    mean_rev = score_mean_reversion(tech, direction)
    volume = score_volume(tech)
    levels = score_key_levels(tech, fib_data or {}, direction)

    total = trend + momentum + mean_rev + volume + levels

    return {
        "total": round(min(100.0, total), 2),
        "trend_alignment": trend,
        "momentum": momentum,
        "mean_reversion": mean_rev,
        "volume": volume,
        "key_levels": levels,
        "direction": direction,
    }


def calculate_confluence_both(tech: dict, fib_data: dict) -> Tuple[dict, dict]:
    """
    Calculate confluence for both directions, return (long_score, short_score).
    """
    long_score = calculate_confluence(tech, fib_data, "long")
    short_score = calculate_confluence(tech, fib_data, "short")
    return long_score, short_score


def calculate_limit_price(
    price: float,
    direction: str,
    tech: dict,
    fib_data: dict,
    sniper_buffer_pct: float = 0.0008,
) -> float:
    """
    Calculate the limit order entry price.

    Priority order:
    1. Nearest Fibonacci level within 0.3% of current price
    2. EMA20 if within 0.2% of current price
    3. Fallback: current_price +/- SNIPER_BUFFER_PCT

    Args:
        price: Current price
        direction: 'long' or 'short'
        tech: Technical analysis data
        fib_data: Fibonacci data
        sniper_buffer_pct: Buffer percentage for fallback

    Returns:
        Limit order price
    """
    tfs = tech.get("timeframes", {})
    tf_15m = tfs.get("15m", {})
    ema20 = _to_float(tf_15m.get("ema_20"))

    # 1. Check Fibonacci levels within 0.3%
    fib_levels = fib_data.get("fib_levels", {}) if fib_data else {}
    best_fib = None
    best_fib_dist = float("inf")

    for level_name, level_price in fib_levels.items():
        lp = _to_float(level_price)
        if lp <= 0:
            continue

        dist_pct = abs(price - lp) / price

        if dist_pct > 0.003:  # more than 0.3%
            continue

        if direction == "long":
            # For LONG: want fib level below current price (support)
            if lp < price and dist_pct < best_fib_dist:
                # Prefer golden ratio levels
                if any(k in level_name for k in ["0.382", "0.5", "0.618"]):
                    best_fib = lp
                    best_fib_dist = dist_pct
                elif best_fib is None:
                    best_fib = lp
                    best_fib_dist = dist_pct
        else:  # short
            # For SHORT: want fib level above current price (resistance)
            if lp > price and dist_pct < best_fib_dist:
                if any(k in level_name for k in ["0.618", "0.786", "1.0"]):
                    best_fib = lp
                    best_fib_dist = dist_pct
                elif best_fib is None:
                    best_fib = lp
                    best_fib_dist = dist_pct

    if best_fib is not None:
        return round(best_fib, 8)

    # 2. Check EMA20 within 0.2%
    if ema20 > 0:
        ema_dist_pct = abs(price - ema20) / price
        if ema_dist_pct <= 0.002:
            if direction == "long" and ema20 < price:
                return round(ema20, 8)
            elif direction == "short" and ema20 > price:
                return round(ema20, 8)

    # 3. Fallback: sniper buffer
    if direction == "long":
        return round(price * (1 - sniper_buffer_pct), 8)
    else:
        return round(price * (1 + sniper_buffer_pct), 8)
